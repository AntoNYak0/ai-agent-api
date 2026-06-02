"""Tests for ECC defi-amm-security adaptation: slippage, flash loan detection,
oracle deviation, MEV scan, pool health, and full report builder.

All functions from app.services.amm_security are tested here.
AI prompt and MCP tool integration tested via real app smoke tests.
"""
import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.services.amm_security import (
    SlippageResult,
    FlashLoanCheckResult,
    OracleDeviationResult,
    MEVCheckResult,
    PoolHealthResult,
    AMMSecurityReport,
    calc_slippage,
    calc_slippage_uni_v3,
    detect_flash_loan,
    check_oracle_deviation,
    scan_mev_vulnerability,
    assess_pool_health,
    build_security_report,
)


# ═══════════════════════════════════════════════════════════════════════
# Slippage calculator tests
# ═══════════════════════════════════════════════════════════════════════

class TestSlippageCalculator:
    """Constant product AMM slippage formula."""

    def test_basic_swap_safe(self):
        """Small trade in deep pool → safe slippage."""
        r = calc_slippage(
            reserve_in=1_000_000,   # $1M USDC
            reserve_out=500,         # 500 ETH
            amount_in=1000,          # $1K swap
        )
        assert r.amount_out_expected > 0
        assert r.slippage_pct < 0.5
        assert r.is_safe
        assert r.warning == ""

    def test_large_trade_unsafe(self):
        """Large trade relative to pool → high slippage."""
        r = calc_slippage(
            reserve_in=10000,
            reserve_out=5000,
            amount_in=5000,  # Half the pool!
            max_slippage_bps=50,
        )
        assert r.slippage_pct > 1.0
        assert not r.is_safe
        assert "CRITICAL" in r.warning or "HIGH" in r.warning

    def test_extreme_trade_critical(self):
        """Swap 20% of pool → very high slippage."""
        r = calc_slippage(
            reserve_in=10000,
            reserve_out=10000,
            amount_in=2000,
        )
        assert r.slippage_pct > 5.0
        assert not r.is_safe
        assert "CRITICAL" in r.warning

    def test_zero_reserves_error(self):
        """Zero reserves should return error result."""
        r = calc_slippage(reserve_in=0, reserve_out=100, amount_in=10)
        assert r.slippage_pct == 100.0
        assert not r.is_safe
        assert "Invalid" in r.warning

    def test_zero_amount_error(self):
        r = calc_slippage(reserve_in=100, reserve_out=100, amount_in=0)
        assert not r.is_safe

    def test_custom_fee(self):
        """1% fee pool should have lower output."""
        r_default = calc_slippage(100000, 50000, 1000, fee_bps=30)
        r_high_fee = calc_slippage(100000, 50000, 1000, fee_bps=100)
        assert r_high_fee.amount_out_expected < r_default.amount_out_expected

    def test_constant_product_invariant(self):
        """After swap, x*y should approximately hold (adjusted for fee)."""
        x, y = 100000, 50000
        amount_in = 100
        r = calc_slippage(x, y, amount_in, fee_bps=0)
        # No fee: (x+dx)*(y-dy) should equal x*y
        new_x = x + amount_in
        new_y = y - r.amount_out_expected
        # Allow small rounding difference
        assert abs(new_x * new_y - x * y) < 0.01

    def test_slippage_monotonic(self):
        """Larger trades should have higher slippage."""
        small = calc_slippage(100000, 50000, 10)
        large = calc_slippage(100000, 50000, 1000)
        assert large.slippage_pct > small.slippage_pct

    def test_v3_approximation(self):
        """Uniswap V3 approximation should produce reasonable results."""
        r = calc_slippage_uni_v3(
            current_price=2000,  # 1 ETH = 2000 USDC
            amount_in=2000,
            liquidity=1_000_000,
        )
        assert r.amount_out_expected > 0
        assert r.slippage_pct > 0


# ═══════════════════════════════════════════════════════════════════════
# Flash loan detection tests
# ═══════════════════════════════════════════════════════════════════════

class TestFlashLoanDetection:
    def test_no_suspicious_pattern(self):
        """Normal transaction — no flash loan."""
        r = detect_flash_loan(
            borrow_amount=50000,
            same_block=False,
            pools_involved=1,
            price_change_pct=0.5,
            has_collateral=True,
        )
        assert not r.is_suspicious
        assert r.risk_score < 30
        assert len(r.patterns_detected) == 0

    def test_classic_flash_loan(self):
        """Same-block borrow+repay with zero collateral."""
        r = detect_flash_loan(
            borrow_amount=1_000_000,
            same_block=True,
            pools_involved=1,
            has_collateral=False,
        )
        assert r.is_suspicious
        assert "same_block_borrow_repay" in r.patterns_detected
        assert "zero_collateral_borrow" in r.patterns_detected

    def test_multi_pool_attack(self):
        """3+ pools in one tx + price swing → likely attack."""
        r = detect_flash_loan(
            borrow_amount=500_000,
            same_block=True,
            pools_involved=4,
            price_change_pct=7.0,
            has_collateral=False,
        )
        assert r.is_suspicious
        assert r.risk_score >= 60
        assert "large_price_swing" in r.patterns_detected
        assert "multi_pool_arbitrage" in r.patterns_detected

    def test_sandwich_within_flash(self):
        """Flash loan + sandwich pattern."""
        r = detect_flash_loan(
            borrow_amount=200_000,
            same_block=True,
            pools_involved=2,
            price_change_pct=3.0,
            has_collateral=False,
        )
        assert "sandwich_within_flash" in r.patterns_detected
        assert r.risk_score >= 30

    def test_moderate_price_swing(self):
        """2% price change is suspicious but not critical."""
        r = detect_flash_loan(
            price_change_pct=2.5,
            pools_involved=1,
        )
        assert "large_price_swing" in r.patterns_detected
        assert r.risk_score < 60  # Not high enough for critical

    def test_no_data_clean(self):
        """No suspicious data — clean result."""
        r = detect_flash_loan()
        assert not r.is_suspicious
        assert r.risk_score == 0
        assert "No flash loan attack patterns" in r.reasoning

    def test_score_capped_at_100(self):
        """All patterns together shouldn't exceed 100."""
        r = detect_flash_loan(
            borrow_amount=10_000_000,
            same_block=True,
            pools_involved=5,
            price_change_pct=20.0,
            has_collateral=False,
        )
        assert r.risk_score <= 100

    def test_governance_pattern_not_yet_detected(self):
        """Governance attack pattern requires specific data not checked here."""
        r = detect_flash_loan(
            borrow_amount=100_000,
            same_block=True,
        )
        # governance_attack is in FLASH_LOAN_PATTERNS but not auto-detected
        # (requires governance-specific context)
        assert "governance_attack" not in r.patterns_detected


# ═══════════════════════════════════════════════════════════════════════
# Oracle deviation tests
# ═══════════════════════════════════════════════════════════════════════

class TestOracleDeviation:
    def test_all_sources_aligned(self):
        """All sources within 1% — no manipulation."""
        r = check_oracle_deviation({
            "chainlink": 1.00,
            "uniswap_v3": 1.005,
            "pyth": 0.998,
        })
        assert not r.is_suspicious
        assert r.max_deviation_pct < 5.0
        assert r.manipulated_source is None

    def test_one_manipulated_source(self):
        """Uniswap price 15% off — likely manipulation."""
        r = check_oracle_deviation({
            "chainlink": 1.00,
            "uniswap_v3": 1.15,
            "pyth": 0.99,
        })
        assert r.is_suspicious
        assert r.manipulated_source == "uniswap_v3"
        assert r.max_deviation_pct > 10.0

    def test_single_source(self):
        """One source only — can't check deviation."""
        r = check_oracle_deviation({"chainlink": 1.0})
        assert not r.is_suspicious
        assert "need at least 2" in r.reasoning.lower()

    def test_empty_prices(self):
        """No price data."""
        r = check_oracle_deviation({})
        assert not r.is_suspicious
        assert "No price data" in r.reasoning

    def test_even_number_sources(self):
        """Median with even number of sources."""
        r = check_oracle_deviation({
            "a": 1.0,
            "b": 1.1,
            "c": 1.2,
            "d": 3.0,  # outlier
        }, max_allowed_deviation_pct=20.0)
        # Median of [1.0, 1.1, 1.2, 3.0] = (1.1+1.2)/2 = 1.15
        assert r.median_price == 1.15
        assert r.manipulated_source == "d"

    def test_custom_threshold(self):
        """Custom deviation threshold — tight."""
        r = check_oracle_deviation(
            {"a": 1.0, "b": 1.05},  # 5% difference
            max_allowed_deviation_pct=2.0,
        )
        assert r.is_suspicious  # ~2.44% > 2%

    def test_zero_price_handling(self):
        """Zero price in one source shouldn't crash."""
        r = check_oracle_deviation({"a": 0.0, "b": 1.0})
        assert r.median_price > 0


# ═══════════════════════════════════════════════════════════════════════
# MEV vulnerability scanner tests
# ═══════════════════════════════════════════════════════════════════════

class TestMEVScanner:
    def test_fully_protected(self):
        """Private mempool + timelock + commit-reveal = safe."""
        r = scan_mev_vulnerability(
            has_slippage_protection=True,
            slippage_tolerance_bps=50,
            uses_commit_reveal=True,
            has_timelock=True,
            is_public_mempool=False,
            has_deadline=True,
            deadline_minutes=20,
        )
        assert not r.vulnerable_to_sandwich
        assert not r.vulnerable_to_frontrun
        assert not r.vulnerable_to_backrun
        assert r.risk_score == 0
        assert "No significant MEV vulnerabilities" in r.findings[0]

    def test_no_protection_public_mempool(self):
        """No protection, public mempool = sandwichable."""
        r = scan_mev_vulnerability(
            has_slippage_protection=False,
            is_public_mempool=True,
        )
        assert r.vulnerable_to_sandwich
        assert r.risk_score >= 30
        assert any("slippage" in f.lower() for f in r.findings)

    def test_high_slippage_tolerance(self):
        """500 bps = 5% slippage — very sandwichable."""
        r = scan_mev_vulnerability(
            has_slippage_protection=True,
            slippage_tolerance_bps=500,
            is_public_mempool=True,
        )
        assert r.vulnerable_to_sandwich
        assert any("Very high slippage" in f for f in r.findings)

    def test_large_value_frontrun(self):
        """$10K tx on public mempool → front-running target."""
        r = scan_mev_vulnerability(
            is_public_mempool=True,
            tx_value_usd=10000,
            uses_commit_reveal=False,
        )
        assert r.vulnerable_to_frontrun
        assert any("Large tx" in f for f in r.findings)

    def test_no_deadline_backrun(self):
        """No deadline → back-running possible."""
        r = scan_mev_vulnerability(
            is_public_mempool=True,
            has_deadline=False,
        )
        assert r.vulnerable_to_backrun
        assert any("deadline" in f.lower() for f in r.findings)

    def test_very_long_deadline(self):
        """120 min deadline → excessive backrun window."""
        r = scan_mev_vulnerability(
            is_public_mempool=True,
            has_deadline=True,
            deadline_minutes=120,
        )
        assert any("Very long deadline" in f for f in r.findings)

    def test_mitigations_provided(self):
        """Mitigations should be suggested for vulnerable config."""
        r = scan_mev_vulnerability(
            is_public_mempool=True,
            has_slippage_protection=False,
            tx_value_usd=5000,
            has_deadline=False,
        )
        assert len(r.mitigations) > 0
        assert any("Flashbots" in m or "private" in m.lower() for m in r.mitigations)

    def test_full_safety_features(self):
        """All protections in place."""
        r = scan_mev_vulnerability(
            has_slippage_protection=True,
            slippage_tolerance_bps=30,
            uses_commit_reveal=True,
            has_timelock=True,
            is_public_mempool=False,
            has_deadline=True,
            deadline_minutes=10,
        )
        assert r.risk_score == 0


# ═══════════════════════════════════════════════════════════════════════
# Pool health tests
# ═══════════════════════════════════════════════════════════════════════

class TestPoolHealth:
    def test_healthy_pool(self):
        """Large TVL, balanced reserves, verified, oracle, old — healthy."""
        r = assess_pool_health(
            tvl_usd=50_000_000,
            volume_24h_usd=5_000_000,
            reserve0_usd=25_000_000,
            reserve1_usd=25_000_000,
            has_oracle=True,
            is_verified=True,
            age_days=365,
        )
        assert r.health_score >= 75
        assert r.concentration_risk == "low"
        assert r.il_risk == "low"
        assert len(r.warnings) == 0

    def test_dangerous_pool(self):
        """Very low TVL, unbalanced, no oracle, not verified, new."""
        r = assess_pool_health(
            tvl_usd=5000,
            volume_24h_usd=10,
            reserve0_usd=4500,
            reserve1_usd=500,
            has_oracle=False,
            is_verified=False,
            age_days=2,
        )
        assert r.health_score < 50
        assert r.concentration_risk == "high"
        assert r.il_risk == "high"
        assert len(r.warnings) >= 2

    def test_dead_pool(self):
        """Zero volume = dead."""
        r = assess_pool_health(
            tvl_usd=100_000,
            volume_24h_usd=500,  # 0.005x ratio
        )
        assert any("dead" in w.lower() for w in r.warnings)

    def test_wash_trading_suspicion(self):
        """Volume 10x TVL = suspicious."""
        r = assess_pool_health(
            tvl_usd=100_000,
            volume_24h_usd=1_000_000,  # 10x ratio
        )
        assert any("wash" in w.lower() for w in r.warnings)

    def test_fee_apy_calculation(self):
        """0.3% fee, 0.5x vol/TVL daily → ~54.75% APY."""
        r = assess_pool_health(
            tvl_usd=1_000_000,
            volume_24h_usd=500_000,
            fee_bps=30,
        )
        assert r.fee_apy_estimate is not None
        assert r.fee_apy_estimate > 0

    def test_volume_to_tvl_healthy_range(self):
        """0.1-2.0 vol/TVL → healthy."""
        r = assess_pool_health(
            tvl_usd=1_000_000,
            volume_24h_usd=500_000,
            has_oracle=True,
            is_verified=True,
        )
        assert r.health_score >= 60

    def test_no_optional_data(self):
        """Works with minimal data."""
        r = assess_pool_health(tvl_usd=50000)
        assert r.health_score > 0
        assert r.volume_to_tvl_ratio is None
        assert r.concentration_risk == "unknown"


# ═══════════════════════════════════════════════════════════════════════
# Full report builder tests
# ═══════════════════════════════════════════════════════════════════════

class TestBuildSecurityReport:
    def test_full_report_all_checks(self):
        """All parameters → all sections filled."""
        report = build_security_report(
            pool_address="0xpool123",
            chain="ethereum",
            tokens=["USDC", "ETH"],
            slippage_params={
                "reserve_in": 1_000_000,
                "reserve_out": 500,
                "amount_in": 1000,
            },
            flash_loan_params={
                "borrow_amount": 100_000,
                "same_block": True,
                "pools_involved": 2,
                "has_collateral": False,
            },
            oracle_prices={"chainlink": 1.0, "uniswap": 1.01, "pyth": 0.99},
            mev_params={
                "has_slippage_protection": True,
                "slippage_tolerance_bps": 50,
                "uses_commit_reveal": False,
                "is_public_mempool": True,
                "tx_value_usd": 2000,
                "has_deadline": True,
                "deadline_minutes": 20,
            },
            health_params={
                "tvl_usd": 5_000_000,
                "volume_24h_usd": 1_000_000,
                "reserve0_usd": 2_500_000,
                "reserve1_usd": 2_500_000,
                "has_oracle": True,
                "is_verified": True,
                "age_days": 200,
            },
        )
        assert report.pool_address == "0xpool123"
        assert report.slippage is not None
        assert report.flash_loan is not None
        assert report.oracle is not None
        assert report.mev is not None
        assert report.health is not None
        assert 0 <= report.overall_score <= 100

    def test_minimal_report(self):
        """No parameters → empty report, no errors."""
        report = build_security_report()
        assert report.pool_address == ""
        assert report.slippage is None
        assert report.flash_loan is None
        assert report.oracle is None
        assert report.mev is None
        assert report.health is None
        assert report.overall_score == 0
        assert report.critical_findings == []

    def test_report_with_critical_findings(self):
        """High risk params → critical findings populated."""
        report = build_security_report(
            slippage_params={
                "reserve_in": 10000,
                "reserve_out": 5000,
                "amount_in": 5000,  # 50% of pool!
            },
            flash_loan_params={
                "borrow_amount": 5_000_000,
                "same_block": True,
                "pools_involved": 4,
                "price_change_pct": 10.0,
                "has_collateral": False,
            },
            oracle_prices={"a": 1.0, "b": 1.25},  # 25% deviation
            mev_params={
                "has_slippage_protection": False,
                "is_public_mempool": True,
                "tx_value_usd": 10000,
                "has_deadline": False,
            },
            health_params={
                "tvl_usd": 8000,
                "has_oracle": False,
                "is_verified": False,
                "age_days": 1,
            },
        )
        assert report.overall_score < 50
        assert len(report.critical_findings) >= 2

    def test_report_types(self):
        """All result fields have correct types."""
        report = build_security_report(
            slippage_params={
                "reserve_in": 100000,
                "reserve_out": 50000,
                "amount_in": 100,
            },
            flash_loan_params={"same_block": True, "borrow_amount": 10000},
            oracle_prices={"a": 1.0, "b": 1.005},
            mev_params={"is_public_mempool": True},
            health_params={"tvl_usd": 500000},
        )
        assert isinstance(report.slippage, SlippageResult)
        assert isinstance(report.flash_loan, FlashLoanCheckResult)
        assert isinstance(report.oracle, OracleDeviationResult)
        assert isinstance(report.mev, MEVCheckResult)
        assert isinstance(report.health, PoolHealthResult)


# ═══════════════════════════════════════════════════════════════════════
# Integration: MCP tool via real app
# ═══════════════════════════════════════════════════════════════════════

class TestAMMSecurityMCPIntegration:
    """Smoke tests for the MCP tool presence and schema."""

    @pytest.fixture
    def client(self):
        """We test via HTTP directly — MCP tools are not REST routes.
        These tests verify the service is properly registered in pricing."""
        return None

    def test_service_registered_in_pricing(self):
        """amm_security is in AI_UPTO_SERVICES."""
        from app.pricing import AI_UPTO_SERVICES, _TOOL_NAMES
        assert "amm_security" in AI_UPTO_SERVICES
        svc = AI_UPTO_SERVICES["amm_security"]
        assert svc["max_price"] == "$0.05"
        assert svc["max_tokens"] == 4000
        assert "amm-security-check" in _TOOL_NAMES
        assert _TOOL_NAMES["amm-security-check"] == "amm_security"

    def test_service_in_max_tokens(self):
        """get_max_tokens works for amm-security."""
        from app.pricing import get_max_tokens, get_upto_caps
        assert get_max_tokens("amm-security-check") == 4000
        assert get_max_tokens("amm_security") == 4000
        caps = get_upto_caps("amm-security-check")
        assert caps is not None
        base, max_mu = caps
        assert base == 25000  # 0.025 USDC
        assert max_mu == 50000  # 0.05 USDC

    def test_prompt_loaded(self):
        """AMM_SECURITY_PROMPT is non-empty and contains expected sections."""
        from app.prompts.amm_security import AMM_SECURITY_PROMPT
        assert len(AMM_SECURITY_PROMPT) > 500
        assert "ROLE:" in AMM_SECURITY_PROMPT
        assert "OUTPUT_SCHEMA:" in AMM_SECURITY_PROMPT
        assert "slippage" in AMM_SECURITY_PROMPT.lower()
        assert "flash_loan" in AMM_SECURITY_PROMPT.lower()

    def test_mcp_tool_registered(self):
        """amm-security-check is registered in mcp_server tools."""
        from app.mcp_server import mcp
        # FastMCP stores tools in _tool_manager
        tool_names = []
        if hasattr(mcp, '_tool_manager'):
            tool_names = list(mcp._tool_manager._tools.keys()) if hasattr(mcp._tool_manager, '_tools') else []
        # Fallback: check via __dict__
        if not tool_names and hasattr(mcp, '_tools'):
            tool_names = list(mcp._tools.keys())
        assert "amm-security-check" in tool_names, f"Tool not found. Available: {tool_names}"

    def test_prices_dict_has_amm_security(self):
        """PRICES dict has amm-security entry."""
        from app.mcp_server import PRICES, AMOUNTS
        assert "amm-security-check" in PRICES
        assert "amm-security-check" in AMOUNTS
        # base is $0.025 (25000 microunits), displayed as "$0.03–$0.05" due to rounding
        assert "$0.05" in PRICES["amm-security-check"]
        assert AMOUNTS["amm-security-check"] == "50000"


# ═══════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_very_small_trade(self):
        """Dust trade — near-zero price impact, but fee still applies."""
        r = calc_slippage(1_000_000, 500_000, 0.001)
        # 0.3% fee dominates for dust trades; slippage ≈ 0.3%
        assert 0 < r.slippage_pct < 0.5  # fee impact only, negligible price movement
        assert r.is_safe

    def test_negative_reserves(self):
        """Negative reserves → error."""
        r = calc_slippage(-100, 100, 10)
        assert not r.is_safe

    def test_extreme_price_deviation(self):
        """One source 2.5x off → clearly manipulated."""
        r = check_oracle_deviation({
            "chainlink": 1.0,
            "pyth": 1.0,
            "hacked_uniswap": 2.5,
        })
        assert r.is_suspicious
        assert r.manipulated_source == "hacked_uniswap"
        assert r.max_deviation_pct > 60  # (2.5-1.0)/1.0 = 150%

    def test_pool_health_score_bounds(self):
        """Health score must be 0-100."""
        # Extremely unhealthy
        r1 = assess_pool_health(
            tvl_usd=100,
            volume_24h_usd=0.1,
            reserve0_usd=99,
            reserve1_usd=1,
            has_oracle=False,
            is_verified=False,
            age_days=0,
        )
        assert 0 <= r1.health_score <= 100

        # Extremely healthy
        r2 = assess_pool_health(
            tvl_usd=100_000_000,
            volume_24h_usd=50_000_000,
            reserve0_usd=50_000_000,
            reserve1_usd=50_000_000,
            has_oracle=True,
            is_verified=True,
            age_days=1000,
        )
        assert 0 <= r2.health_score <= 100

    def test_flash_loan_negative_score(self):
        """Flash loan risk score should never be negative."""
        r = detect_flash_loan()
        assert r.risk_score >= 0

    def test_mev_mitigations_no_duplicates(self):
        """Mitigations list should not have duplicates."""
        r = scan_mev_vulnerability(
            has_slippage_protection=False,
            is_public_mempool=True,
            tx_value_usd=5000,
            has_deadline=False,
        )
        assert len(r.mitigations) == len(set(r.mitigations))

    def test_report_overall_score_bounds(self):
        """Overall score 0-100."""
        r1 = build_security_report()
        assert 0 <= r1.overall_score <= 100
        # High risk
        r2 = build_security_report(
            slippage_params={"reserve_in": 100, "reserve_out": 100, "amount_in": 90},
            flash_loan_params={"same_block": True, "borrow_amount": 1_000_000, "has_collateral": False},
            oracle_prices={"a": 1.0, "b": 5.0},
            mev_params={"has_slippage_protection": False, "is_public_mempool": True},
            health_params={"tvl_usd": 100},
        )
        assert 0 <= r2.overall_score <= 100
