"""Tests for cost-aware LLM pipeline — cost tracker + model routing.

Adapted from ECC cost-aware-llm-pipeline patterns.
"""
import pytest
from app.services.cost_tracker import (
    BudgetExceededError,
    CostRecord,
    CostTracker,
    calc_cost,
    PRICING,
    record_cost,
    reset_global_tracker,
    get_global_tracker,
)
from app.services.deepseek import (
    MODEL_PRO,
    MODEL_FLASH,
    select_model,
)


# ═══════════════════════════════════════════════════════════════════
# CostRecord
# ═══════════════════════════════════════════════════════════════════

class TestCostRecord:
    def test_immutable(self):
        r = CostRecord(model=MODEL_PRO, input_tokens=1000, output_tokens=500, cost_usd=0.001)
        with pytest.raises(Exception):
            r.cost_usd = 0.002  # frozen dataclass

    def test_defaults(self):
        r = CostRecord(model=MODEL_FLASH, input_tokens=100, output_tokens=50, cost_usd=0.0001)
        assert r.tool == ""
        assert r.timestamp > 0

    def test_with_tool(self):
        r = CostRecord(model=MODEL_PRO, input_tokens=500, output_tokens=200,
                       cost_usd=0.0005, tool="audit")
        assert r.tool == "audit"


# ═══════════════════════════════════════════════════════════════════
# CostTracker — immutable + cumulative
# ═══════════════════════════════════════════════════════════════════

class TestCostTracker:
    def test_empty_tracker(self):
        t = CostTracker()
        assert t.total_cost == 0.0
        assert t.call_count == 0
        assert not t.over_budget

    def test_add_returns_new_tracker(self):
        t1 = CostTracker(budget_limit=0.10)
        r = CostRecord(model=MODEL_PRO, input_tokens=1000, output_tokens=500, cost_usd=0.002)
        t2 = t1.add(r)

        # t1 unchanged
        assert t1.total_cost == 0.0
        assert t1.call_count == 0

        # t2 has the new record
        assert t2.total_cost == 0.002
        assert t2.call_count == 1

    def test_cumulative_cost(self):
        t = CostTracker(budget_limit=1.00)
        t = t.add(CostRecord(model=MODEL_PRO, input_tokens=1000, output_tokens=500, cost_usd=0.003))
        t = t.add(CostRecord(model=MODEL_FLASH, input_tokens=2000, output_tokens=100, cost_usd=0.0005))
        t = t.add(CostRecord(model=MODEL_PRO, input_tokens=3000, output_tokens=1000, cost_usd=0.005))

        assert t.call_count == 3
        assert t.total_cost == 0.0085
        assert not t.over_budget

    def test_over_budget(self):
        t = CostTracker(budget_limit=0.01)
        t = t.add(CostRecord(model=MODEL_PRO, input_tokens=10000, output_tokens=5000, cost_usd=0.015))
        assert t.over_budget
        assert t.total_cost == 0.015

    def test_stats(self):
        t = CostTracker(budget_limit=0.50)
        t = t.add(CostRecord(model=MODEL_PRO, input_tokens=1000, output_tokens=500,
                             cost_usd=0.001, tool="audit"))
        t = t.add(CostRecord(model=MODEL_FLASH, input_tokens=500, output_tokens=100,
                             cost_usd=0.0001, tool="classify-text"))

        s = t.stats()
        assert s["total_calls"] == 2
        assert s["over_budget"] is False
        assert MODEL_PRO in s["by_model"]
        assert MODEL_FLASH in s["by_model"]
        assert s["by_model"][MODEL_PRO]["calls"] == 1
        assert s["by_model"][MODEL_FLASH]["calls"] == 1


class TestBudgetExceededError:
    def test_error_message(self):
        err = BudgetExceededError(total_cost=0.052, budget_limit=0.05)
        assert "0.0520" in str(err)
        assert "0.05" in str(err)
        assert err.total_cost == 0.052
        assert err.budget_limit == 0.05


# ═══════════════════════════════════════════════════════════════════
# calc_cost
# ═══════════════════════════════════════════════════════════════════

class TestCalcCost:
    def test_pro_pricing(self):
        cost = calc_cost(MODEL_PRO, input_tokens=1_000_000, output_tokens=1_000_000)
        # $0.42/M input + $1.68/M output = $2.10
        assert cost == pytest.approx(2.10, rel=0.01)

    def test_flash_pricing(self):
        cost = calc_cost(MODEL_FLASH, input_tokens=1_000_000, output_tokens=1_000_000)
        # $0.14/M input + $0.42/M output = $0.56
        assert cost == pytest.approx(0.56, rel=0.01)

    def test_flash_is_cheaper(self):
        pro_cost = calc_cost(MODEL_PRO, input_tokens=50000, output_tokens=10000)
        flash_cost = calc_cost(MODEL_FLASH, input_tokens=50000, output_tokens=10000)
        assert flash_cost < pro_cost
        # Flash should be ~3-4x cheaper
        ratio = pro_cost / flash_cost
        assert 2.5 < ratio < 4.5

    def test_zero_tokens(self):
        cost = calc_cost(MODEL_PRO, input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_unknown_model_fallback(self):
        cost = calc_cost("unknown-model", input_tokens=1_000_000, output_tokens=1_000_000)
        # Falls back to Pro pricing
        assert cost == pytest.approx(2.10, rel=0.01)


# ═══════════════════════════════════════════════════════════════════
# Global Tracker
# ═══════════════════════════════════════════════════════════════════

class TestGlobalTracker:
    def test_reset(self):
        record_cost(CostRecord(model=MODEL_PRO, input_tokens=100, output_tokens=50, cost_usd=0.0001))
        assert get_global_tracker().call_count >= 1
        reset_global_tracker()
        assert get_global_tracker().call_count == 0
        assert get_global_tracker().total_cost == 0.0


# ═══════════════════════════════════════════════════════════════════
# Model Routing
# ═══════════════════════════════════════════════════════════════════

class TestSelectModel:
    def test_simple_task_uses_flash(self):
        # Small max_tokens + short input → Flash
        assert select_model(max_tokens=500, input_length=100) == MODEL_FLASH

    def test_complex_task_uses_pro(self):
        # Large max_tokens → Pro
        assert select_model(max_tokens=4000, input_length=100) == MODEL_PRO

    def test_long_input_uses_pro(self):
        # Exceeds _FLASH_INPUT_CHARS threshold (5000)
        assert select_model(max_tokens=1000, input_length=6000) == MODEL_PRO

    def test_force_model_overrides(self):
        assert select_model(max_tokens=500, input_length=100, force_model=MODEL_PRO) == MODEL_PRO
        assert select_model(max_tokens=4000, input_length=10000, force_model=MODEL_FLASH) == MODEL_FLASH

    def test_defaults_to_pro(self):
        # No args → Pro (safe default)
        assert select_model() == MODEL_PRO

    def test_boundary_max_tokens(self):
        """Exactly 1500 max_tokens → Flash (≤ threshold)."""
        assert select_model(max_tokens=1500, input_length=100) == MODEL_FLASH
        # 1501 → Pro
        assert select_model(max_tokens=1501, input_length=100) == MODEL_PRO

    def test_boundary_input_length(self):
        """Exactly 5000 chars → Flash (≤ threshold)."""
        assert select_model(max_tokens=500, input_length=5000) == MODEL_FLASH
        # 5001 → Pro
        assert select_model(max_tokens=500, input_length=5001) == MODEL_PRO


# ═══════════════════════════════════════════════════════════════════
# Service catalog routing — verify correct model per service
# ═══════════════════════════════════════════════════════════════════

class TestServiceModelRouting:
    """Verify that each service type gets the right model based on pricing.py thresholds."""

    @pytest.mark.parametrize("max_tokens,expected", [
        # EXACT_SERVICES (all ≤1500) → Flash
        (500, MODEL_FLASH),    # validate-json
        (500, MODEL_FLASH),    # classify-text
        (1500, MODEL_FLASH),   # extract-data
        (800, MODEL_FLASH),    # generate-regex
        (800, MODEL_FLASH),    # format-data
        (1000, MODEL_FLASH),   # summarize
        # Simple upto (≤1500) → Flash
        (1500, MODEL_FLASH),   # nl-to-sql
        (1500, MODEL_FLASH),   # sql-to-nl
        # Complex upto (>1500) → Pro
        (2000, MODEL_PRO),     # data-feed, price-feed, git-summarize
        (2500, MODEL_PRO),     # trading, whale, smart-money, debug-log, security-score
        (4000, MODEL_PRO),     # audit, defi
        (6000, MODEL_PRO),     # refactor, docs, solidity, agent-audit, translate-code
        (8000, MODEL_PRO),     # contract-verify
    ])
    def test_routing_by_max_tokens(self, max_tokens, expected):
        assert select_model(max_tokens=max_tokens, input_length=100) == expected
