"""Immutable cost tracking for LLM API calls.

Pattern adapted from ECC cost-aware-llm-pipeline:
  - Frozen dataclasses — each call returns a new tracker, never mutates state
  - Model-aware pricing — Flash vs Pro rates
  - Budget guardrails — fail fast before overspending
  - Global tracker for /health and monitoring endpoints

DeepSeek V4 pricing (per 1M tokens):
  - deepseek-chat (V4 Pro):  $0.42 input, $1.68 output
  - deepseek-v4-flash:       $0.14 input, $0.42 output  (~3-4x cheaper)
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Tuple


# ── Pricing ─────────────────────────────────────────────────────────

PRICING = {
    "deepseek-chat":       {"input": 0.42, "output": 1.68},   # V4 Pro
    "deepseek-v4-flash":   {"input": 0.14, "output": 0.42},   # V4 Flash
}

# Fallback for unknown models — assume most expensive to be safe
_FALLBACK_RATES = {"input": 0.42, "output": 1.68}


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a single LLM call."""
    rates = PRICING.get(model, _FALLBACK_RATES)
    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 8)


# ── Immutable records ──────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CostRecord:
    """One LLM API call — immutable."""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: float = field(default_factory=time.time)
    tool: str = ""


@dataclass(frozen=True, slots=True)
class CostTracker:
    """Cumulative cost tracker — immutable. add() returns a NEW tracker."""
    budget_limit: float = 1.00
    records: Tuple[CostRecord, ...] = ()

    def add(self, record: CostRecord) -> "CostTracker":
        """Return new tracker with added record. Never mutates self."""
        return CostTracker(
            budget_limit=self.budget_limit,
            records=(*self.records, record),
        )

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def over_budget(self) -> bool:
        return self.total_cost > self.budget_limit

    @property
    def call_count(self) -> int:
        return len(self.records)

    def stats(self) -> dict:
        """Export stats for monitoring endpoints."""
        by_model: dict = {}
        for r in self.records:
            key = r.model
            if key not in by_model:
                by_model[key] = {"calls": 0, "cost": 0.0, "tokens": 0}
            by_model[key]["calls"] += 1
            by_model[key]["cost"] += r.cost_usd
            by_model[key]["tokens"] += r.input_tokens + r.output_tokens

        return {
            "total_cost": round(self.total_cost, 6),
            "budget_limit": self.budget_limit,
            "over_budget": self.over_budget,
            "total_calls": self.call_count,
            "by_model": {k: {
                "calls": v["calls"],
                "cost": round(v["cost"], 6),
                "tokens": v["tokens"],
            } for k, v in by_model.items()},
        }


class BudgetExceededError(Exception):
    """Raised when cumulative cost exceeds budget limit."""
    def __init__(self, total_cost: float, budget_limit: float):
        self.total_cost = total_cost
        self.budget_limit = budget_limit
        super().__init__(
            f"Budget exceeded: ${total_cost:.4f} spent of ${budget_limit:.2f} limit"
        )


# ── Global tracker (session-scoped, for monitoring) ────────────────

_global_tracker: CostTracker = CostTracker()
_tracker_lock = threading.Lock()


def get_global_tracker() -> CostTracker:
    """Return current global tracker snapshot."""
    with _tracker_lock:
        return _global_tracker


def record_cost(record: CostRecord) -> None:
    """Record a cost to the global tracker."""
    global _global_tracker
    with _tracker_lock:
        _global_tracker = _global_tracker.add(record)


def reset_global_tracker() -> None:
    """Reset global tracker (used in tests)."""
    global _global_tracker
    with _tracker_lock:
        _global_tracker = CostTracker()


def get_budget_status() -> dict:
    """Return budget status for monitoring endpoints.

    Uses settings.llm_budget_limit_usd as the authoritative limit,
    falling back to the tracker's internal limit if settings is 0.
    """
    from app.config import settings

    tracker = get_global_tracker()
    limit = settings.llm_budget_limit_usd
    if limit <= 0:
        limit = tracker.budget_limit  # fallback to default $1.00

    spent = tracker.total_cost
    pct = int(spent / limit * 100) if limit > 0 else 0

    return {
        "total_spent_usd": round(spent, 6),
        "limit_usd": round(limit, 2),
        "over_budget": spent > limit,
        "pct_used": pct,
        "total_calls": tracker.call_count,
    }
