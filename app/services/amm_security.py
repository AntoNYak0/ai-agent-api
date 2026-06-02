"""AMM Security — deterministic DeFi safety checks.

ECC defi-amm-security pattern adapted for agent-api:
  - Slippage calculator (constant product AMM math)
  - Flash loan attack detector (heuristic: borrow+repay same block)
  - Oracle deviation checker (multi-source price comparison)
  - MEV vulnerability scanner (sandwich/frontrunning patterns)
  - Pool health scoring (TVL concentration, IL risk, fee sustainability)

All functions are synchronous and deterministic — no DB, no network, no AI.
The AI prompt layer (amm_security.py in prompts/) calls these and interprets results.
"""

import math
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SlippageResult:
    """Result of a slippage calculation."""
    amount_in: float
    amount_out_expected: float
    amount_out_min: float          # after slippage
    slippage_pct: float            # e.g. 0.5 = 0.5%
    price_impact_pct: float        # price movement caused by trade
    is_safe: bool                  # True if slippage ≤ threshold
    warning: str = ""


@dataclass
class FlashLoanCheckResult:
    """Result of flash loan attack heuristic check."""
    is_suspicious: bool
    risk_score: int                # 0–100
    patterns_detected: list[str]   # e.g. ["same_block_borrow_repay", "large_price_swing"]
    reasoning: str


@dataclass
class OracleDeviationResult:
    """Result of oracle price deviation check."""
    prices: dict[str, float]       # source → price
    median_price: float
    max_deviation_pct: float       # max deviation from median
    manipulated_source: str | None # source with highest deviation, if suspicious
    is_suspicious: bool
    reasoning: str


@dataclass
class MEVCheckResult:
    """Result of MEV vulnerability scan."""
    vulnerable_to_sandwich: bool
    vulnerable_to_frontrun: bool
    vulnerable_to_backrun: bool
    risk_score: int                # 0–100
    findings: list[str]
    mitigations: list[str]


@dataclass
class PoolHealthResult:
    """Overall pool health assessment."""
    health_score: int              # 0–100, higher = safer
    tvl_usd: float
    volume_24h_usd: float | None
    volume_to_tvl_ratio: float | None
    concentration_risk: str        # "low" | "medium" | "high"
    il_risk: str                   # "low" | "medium" | "high"
    fee_apy_estimate: float | None
    warnings: list[str]
    recommendations: list[str]


@dataclass
class AMMSecurityReport:
    """Full AMM security report combining all checks."""
    pool_address: str
    chain: str
    tokens: list[str]
    slippage: SlippageResult | None = None
    flash_loan: FlashLoanCheckResult | None = None
    oracle: OracleDeviationResult | None = None
    mev: MEVCheckResult | None = None
    health: PoolHealthResult | None = None
    overall_score: int = 0         # 0–100
    critical_findings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# Slippage calculator — constant product AMM (x*y=k)
# ═══════════════════════════════════════════════════════════════════════

def calc_slippage(
    reserve_in: float,
    reserve_out: float,
    amount_in: float,
    fee_bps: float = 30,           # default 0.3% (Uniswap V2)
    max_slippage_bps: float = 50,  # default 0.5% max acceptable slippage
) -> SlippageResult:
    """Calculate expected output and slippage for a constant-product AMM swap.

    Formula: amount_out = (amount_in * (1 - fee) * reserve_out) / (reserve_in + amount_in * (1 - fee))

    Args:
        reserve_in: Pool reserve of input token
        reserve_out: Pool reserve of output token
        amount_in: Amount of input token being swapped
        fee_bps: Fee in basis points (30 = 0.3%)
        max_slippage_bps: Maximum acceptable slippage in bps
    """
    if reserve_in <= 0 or reserve_out <= 0 or amount_in <= 0:
        return SlippageResult(
            amount_in=amount_in,
            amount_out_expected=0,
            amount_out_min=0,
            slippage_pct=100.0,
            price_impact_pct=100.0,
            is_safe=False,
            warning="Invalid reserves or amount: all values must be positive",
        )

    fee_multiplier = 1.0 - (fee_bps / 10_000)

    # Expected output from constant product formula
    amount_out = (amount_in * fee_multiplier * reserve_out) / (reserve_in + amount_in * fee_multiplier)

    # Spot price before trade
    spot_price = reserve_out / reserve_in

    # Effective price after trade
    effective_price = amount_out / amount_in

    # Price impact (how much the trade moves the price)
    price_impact = abs(spot_price - effective_price) / spot_price
    price_impact_pct = price_impact * 100

    # Slippage from price impact — larger trades get worse execution
    slippage_pct = price_impact_pct * (1 + amount_in / reserve_in)

    # Minimum output after slippage
    slippage_factor = 1.0 - (max_slippage_bps / 10_000)
    amount_out_min = amount_out * slippage_factor

    is_safe = slippage_pct <= (max_slippage_bps / 100)

    warning = ""
    if not is_safe:
        if slippage_pct > 5.0:
            warning = f"CRITICAL: {slippage_pct:.1f}% slippage — trade size too large for pool depth"
        elif slippage_pct > 2.0:
            warning = f"HIGH: {slippage_pct:.1f}% slippage — consider splitting into smaller trades"
        else:
            warning = f"Moderate slippage ({slippage_pct:.2f}%) — adjust max_slippage or reduce trade size"

    return SlippageResult(
        amount_in=amount_in,
        amount_out_expected=round(amount_out, 6),
        amount_out_min=round(amount_out_min, 6),
        slippage_pct=round(slippage_pct, 4),
        price_impact_pct=round(price_impact_pct, 4),
        is_safe=is_safe,
        warning=warning,
    )


def calc_slippage_uni_v3(
    current_price: float,
    amount_in: float,
    liquidity: float,
    fee_bps: float = 30,
    max_slippage_bps: float = 50,
) -> SlippageResult:
    """Approximate Uniswap V3 slippage (concentrated liquidity).

    Simplified model: treats concentrated position as V2 pool with
    adjusted depth proportional to liquidity at current tick.
    """
    # Approximate reserves at current price
    reserve_out = liquidity / math.sqrt(current_price) if current_price > 0 else 0
    reserve_in = liquidity * math.sqrt(current_price) if current_price > 0 else 0

    return calc_slippage(reserve_in, reserve_out, amount_in, fee_bps, max_slippage_bps)


# ═══════════════════════════════════════════════════════════════════════
# Flash loan attack detector
# ═══════════════════════════════════════════════════════════════════════

FLASH_LOAN_PATTERNS = [
    ("same_block_borrow_repay", "Borrow and repay in the same block — classic flash loan signature"),
    ("large_price_swing", "Large price movement immediately after borrow — possible oracle manipulation"),
    ("multi_pool_arbitrage", "Interaction with 3+ pools in single transaction — could be attack routing"),
    ("zero_collateral_borrow", "Borrow without collateral deposit — flash loan characteristic"),
    ("sandwich_within_flash", "Flash loan + sandwich pattern — amplified MEV attack"),
    ("governance_attack", "Flash loan to acquire governance tokens → pass malicious proposal"),
    ("vault_drain", "Share price manipulation → disproportionate withdraw"),
]


def detect_flash_loan(
    transaction_data: dict | None = None,
    borrow_amount: float = 0,
    repay_amount: float = 0,
    same_block: bool = False,
    pools_involved: int = 1,
    price_change_pct: float = 0,
    has_collateral: bool = True,
) -> FlashLoanCheckResult:
    """Heuristic flash loan attack detection.

    Checks known attack patterns based on transaction characteristics.
    All parameters are optional — only checks what's provided.
    """
    patterns: list[str] = []
    score = 0

    # Pattern 1: Same-block borrow+repay
    if same_block and borrow_amount > 0:
        patterns.append(FLASH_LOAN_PATTERNS[0][0])
        score += 25

    # Pattern 2: Large price swing
    if price_change_pct > 5.0:
        patterns.append(FLASH_LOAN_PATTERNS[1][0])
        score += 30
    elif price_change_pct > 2.0:
        patterns.append(FLASH_LOAN_PATTERNS[1][0])
        score += 15

    # Pattern 3: Multi-pool routing
    if pools_involved >= 3:
        patterns.append(FLASH_LOAN_PATTERNS[2][0])
        score += 20

    # Pattern 4: Zero collateral
    if not has_collateral and borrow_amount > 0:
        patterns.append(FLASH_LOAN_PATTERNS[3][0])
        score += 20

    # Pattern 5: Sandwich + flash loan (requires same_block + multi_pool + price_swing)
    if same_block and pools_involved >= 2 and price_change_pct > 1.0:
        patterns.append(FLASH_LOAN_PATTERNS[4][0])
        score += 30

    # Build reasoning
    if not patterns:
        reasoning = "No flash loan attack patterns detected based on provided data."
    else:
        pattern_names = [p for p, _desc in FLASH_LOAN_PATTERNS if p in patterns]
        reasoning = f"Detected {len(patterns)} suspicious patterns: {', '.join(pattern_names)}. "

        if score >= 60:
            reasoning += "HIGH probability of flash loan attack. Immediate investigation required."
        elif score >= 30:
            reasoning += "MODERATE probability — unusual activity, manual review recommended."
        else:
            reasoning += "LOW probability but warrants monitoring."

    return FlashLoanCheckResult(
        is_suspicious=score >= 30,
        risk_score=min(score, 100),
        patterns_detected=patterns,
        reasoning=reasoning,
    )


# ═══════════════════════════════════════════════════════════════════════
# Oracle deviation checker
# ═══════════════════════════════════════════════════════════════════════

def check_oracle_deviation(
    prices: dict[str, float],
    max_allowed_deviation_pct: float = 5.0,
) -> OracleDeviationResult:
    """Check price deviation across multiple oracle sources.

    Calculates median price and flags sources that deviate beyond threshold.
    This detects oracle manipulation where one feed is artificially inflated/deflated.

    Args:
        prices: Dict of source_name → price (e.g. {"chainlink": 1.0, "uniswap_v3": 1.15, "pyth": 1.02})
        max_allowed_deviation_pct: Maximum acceptable deviation from median
    """
    if not prices:
        return OracleDeviationResult(
            prices={},
            median_price=0,
            max_deviation_pct=0,
            manipulated_source=None,
            is_suspicious=False,
            reasoning="No price data provided — cannot check oracle deviation",
        )

    if len(prices) == 1:
        source, price = next(iter(prices.items()))
        return OracleDeviationResult(
            prices=prices,
            median_price=price,
            max_deviation_pct=0,
            manipulated_source=None,
            is_suspicious=False,
            reasoning=f"Only one price source ({source}) — need at least 2 for deviation check",
        )

    # Calculate median
    sorted_prices = sorted(prices.values())
    n = len(sorted_prices)
    if n % 2 == 0:
        median = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2
    else:
        median = sorted_prices[n // 2]

    # Find max deviation
    deviations = {}
    for source, price in prices.items():
        if median > 0:
            deviations[source] = abs(price - median) / median * 100
        else:
            deviations[source] = 0

    max_deviation = max(deviations.values()) if deviations else 0
    manipulated = max(deviations, key=deviations.get) if deviations else None

    is_suspicious = max_deviation > max_allowed_deviation_pct

    if not is_suspicious:
        reasoning = f"All {len(prices)} sources within {max_allowed_deviation_pct}% of median. Max deviation: {max_deviation:.2f}% ({manipulated})."
    else:
        source_price = prices.get(manipulated, 0)
        reasoning = (
            f"SUSPICIOUS: {manipulated} deviates {max_deviation:.2f}% from median price ${median:.4f}. "
            f"Its price (${source_price:.4f}) vs median (${median:.4f}). "
            f"Possible oracle manipulation or stale feed."
        )

    return OracleDeviationResult(
        prices=prices,
        median_price=round(median, 6),
        max_deviation_pct=round(max_deviation, 4),
        manipulated_source=manipulated if is_suspicious else None,
        is_suspicious=is_suspicious,
        reasoning=reasoning,
    )


# ═══════════════════════════════════════════════════════════════════════
# MEV vulnerability scanner
# ═══════════════════════════════════════════════════════════════════════

def scan_mev_vulnerability(
    has_slippage_protection: bool = False,
    slippage_tolerance_bps: float | None = None,
    uses_commit_reveal: bool = False,
    has_timelock: bool = False,
    is_public_mempool: bool = True,
    tx_value_usd: float = 0,
    has_deadline: bool = False,
    deadline_minutes: int | None = None,
) -> MEVCheckResult:
    """Scan for MEV vulnerability patterns.

    Checks common DeFi MEV attack surfaces:
    - Sandwich attacks: front-run + victim + back-run in same block
    - Front-running: seeing pending tx and submitting yours first with higher gas
    - Back-running: submitting tx immediately after to extract value

    Args are booleans/values describing the transaction or protocol configuration.
    """
    findings: list[str] = []
    mitigations: list[str] = []
    score = 0

    # Sandwich vulnerability
    sandwich_vuln = False
    if is_public_mempool and not has_slippage_protection:
        sandwich_vuln = True
        findings.append("No slippage protection on public mempool — trivial to sandwich")
        mitigations.append("Set max_slippage in swap parameters (recommended: 0.5% = 50 bps)")
        score += 35
    elif is_public_mempool and slippage_tolerance_bps and slippage_tolerance_bps > 200:
        sandwich_vuln = True
        findings.append(f"Very high slippage tolerance ({slippage_tolerance_bps} bps = {slippage_tolerance_bps/100:.1f}%) — sandwich profitable even with fees")
        mitigations.append("Reduce slippage tolerance to ≤100 bps (1%)")
        score += 25
    elif is_public_mempool and slippage_tolerance_bps and slippage_tolerance_bps > 100:
        findings.append(f"Moderate slippage tolerance ({slippage_tolerance_bps} bps) — sandwich possible in volatile conditions")
        mitigations.append("Consider reducing to 50 bps or using Flashbots/private relay")
        score += 10

    # Front-running vulnerability
    frontrun_vuln = False
    if is_public_mempool and not uses_commit_reveal and tx_value_usd > 1000:
        frontrun_vuln = True
        findings.append(f"Large tx (${tx_value_usd:,.0f}) visible in public mempool without commit-reveal")
        mitigations.append("Use commit-reveal scheme or submit via Flashbots/private relay")
        score += 30
    elif is_public_mempool and not uses_commit_reveal and tx_value_usd > 100:
        findings.append(f"Tx value (${tx_value_usd:,.0f}) visible in mempool — front-running possible")
        mitigations.append("Consider private relay for value-bearing transactions")
        score += 15

    # Back-running vulnerability
    backrun_vuln = False
    if is_public_mempool and not has_deadline:
        backrun_vuln = True
        findings.append("No transaction deadline — can be held and back-run at attacker's convenience")
        mitigations.append("Set a transaction deadline (recommended: 20 minutes)")
        score += 20
    elif deadline_minutes and deadline_minutes > 60:
        findings.append(f"Very long deadline ({deadline_minutes} min) — back-running window is excessive")
        mitigations.append("Reduce deadline to ≤30 minutes")
        score += 10

    # Positive indicators (reduce score)
    if has_timelock:
        mitigations.append("Timelock in place — good protection against governance MEV")
    if uses_commit_reveal:
        mitigations.append("Commit-reveal scheme — good front-running protection")
    if not is_public_mempool:
        mitigations.append("Private mempool/Flashbots — reduces MEV surface")

    # Deduplicate mitigations
    mitigations = list(dict.fromkeys(mitigations))

    if not findings:
        findings.append("No significant MEV vulnerabilities detected")

    return MEVCheckResult(
        vulnerable_to_sandwich=sandwich_vuln,
        vulnerable_to_frontrun=frontrun_vuln,
        vulnerable_to_backrun=backrun_vuln,
        risk_score=min(score, 100),
        findings=findings,
        mitigations=mitigations[:5],
    )


# ═══════════════════════════════════════════════════════════════════════
# Pool health scoring
# ═══════════════════════════════════════════════════════════════════════

def assess_pool_health(
    tvl_usd: float,
    volume_24h_usd: float | None = None,
    fee_bps: float = 30,
    reserve0_usd: float | None = None,
    reserve1_usd: float | None = None,
    has_oracle: bool = False,
    is_verified: bool = False,
    age_days: int | None = None,
) -> PoolHealthResult:
    """Assess AMM pool health and risk factors.

    Scoring dimensions:
    - TVL depth (liquidity)
    - Volume/TVL ratio (capital efficiency)
    - Reserve concentration (balanced pool = lower IL risk)
    - Oracle presence (price manipulation resistance)
    - Contract verification
    - Pool age (established vs new)
    """
    warnings: list[str] = []
    recommendations: list[str] = []
    score = 50  # Start neutral

    # TVL depth
    if tvl_usd >= 10_000_000:
        score += 15
    elif tvl_usd >= 1_000_000:
        score += 10
    elif tvl_usd >= 100_000:
        score += 5
    elif tvl_usd >= 10_000:
        warnings.append(f"Low TVL (${tvl_usd:,.0f}) — susceptible to price manipulation")
        score -= 5
    else:
        warnings.append(f"Very low TVL (${tvl_usd:,.0f}) — extreme manipulation risk, do NOT trade large amounts")
        score -= 15

    # Volume/TVL ratio
    vol_tvl = None
    if volume_24h_usd and tvl_usd > 0:
        vol_tvl = volume_24h_usd / tvl_usd
        if 0.1 <= vol_tvl <= 2.0:
            score += 10  # Healthy activity
        elif vol_tvl > 5.0:
            warnings.append(f"Very high volume/TVL ratio ({vol_tvl:.1f}x) — possible wash trading or extreme volatility")
            score -= 5
        elif vol_tvl < 0.01:
            warnings.append(f"Very low volume/TVL ({vol_tvl:.4f}x) — dead pool, LPs earning nothing")
            score -= 5

    # Reserve concentration (IL risk)
    concentration_risk = "low"
    il_risk = "low"
    if reserve0_usd is not None and reserve1_usd is not None and (reserve0_usd + reserve1_usd) > 0:
        ratio = min(reserve0_usd, reserve1_usd) / max(reserve0_usd, reserve1_usd) if max(reserve0_usd, reserve1_usd) > 0 else 0
        if ratio > 0.8:
            concentration_risk = "low"
            il_risk = "low"
            score += 10
        elif ratio > 0.5:
            concentration_risk = "medium"
            il_risk = "medium"
            warnings.append(f"Unbalanced reserves ({ratio:.1%} ratio) — moderate impermanent loss risk")
        else:
            concentration_risk = "high"
            il_risk = "high"
            warnings.append(f"Highly unbalanced pool ({ratio:.1%} ratio) — extreme IL risk for LPs")
            score -= 10
    else:
        concentration_risk = "unknown"
        il_risk = "unknown"

    # Oracle / price feed
    if has_oracle:
        score += 5
    else:
        warnings.append("No oracle — pool price can be manipulated via flash loans")
        recommendations.append("Integrate Chainlink/Pyth oracle or use TWAP for price discovery")

    # Contract verification
    if is_verified:
        score += 5
    else:
        warnings.append("Contract not verified — cannot audit for hidden backdoors")
        recommendations.append("Verify contract on block explorer")

    # Pool age
    if age_days is not None:
        if age_days >= 180:
            score += 5  # Battle-tested
        elif age_days < 7:
            warnings.append(f"New pool ({age_days} days) — limited track record, higher risk")
            score -= 5

    # Fee APY estimate
    fee_apy = None
    if vol_tvl is not None and vol_tvl > 0:
        # Annualized: daily_volume * fee_rate * 365 / tvl
        fee_apy = vol_tvl * (fee_bps / 10_000) * 365 * 100

    # Clamp
    score = max(0, min(100, score))

    return PoolHealthResult(
        health_score=score,
        tvl_usd=tvl_usd,
        volume_24h_usd=volume_24h_usd,
        volume_to_tvl_ratio=round(vol_tvl, 4) if vol_tvl is not None else None,
        concentration_risk=concentration_risk,
        il_risk=il_risk,
        fee_apy_estimate=round(fee_apy, 2) if fee_apy is not None else None,
        warnings=warnings,
        recommendations=recommendations,
    )


# ═══════════════════════════════════════════════════════════════════════
# Full report aggregator
# ═══════════════════════════════════════════════════════════════════════

def build_security_report(
    pool_address: str = "",
    chain: str = "ethereum",
    tokens: list[str] | None = None,
    slippage_params: dict | None = None,
    flash_loan_params: dict | None = None,
    oracle_prices: dict[str, float] | None = None,
    mev_params: dict | None = None,
    health_params: dict | None = None,
) -> AMMSecurityReport:
    """Build a complete AMM security report by running all relevant checks.

    Pass only the data you have — checks without data are skipped (set to None).
    """
    tokens = tokens or []
    report = AMMSecurityReport(pool_address=pool_address, chain=chain, tokens=tokens)

    # Slippage check
    if slippage_params:
        reserve_in = slippage_params.get("reserve_in", 0)
        reserve_out = slippage_params.get("reserve_out", 0)
        amount_in = slippage_params.get("amount_in", 0)
        if reserve_in > 0 and reserve_out > 0 and amount_in > 0:
            report.slippage = calc_slippage(
                reserve_in=reserve_in,
                reserve_out=reserve_out,
                amount_in=amount_in,
                fee_bps=slippage_params.get("fee_bps", 30),
                max_slippage_bps=slippage_params.get("max_slippage_bps", 50),
            )

    # Flash loan check
    if flash_loan_params:
        report.flash_loan = detect_flash_loan(
            borrow_amount=flash_loan_params.get("borrow_amount", 0),
            repay_amount=flash_loan_params.get("repay_amount", 0),
            same_block=flash_loan_params.get("same_block", False),
            pools_involved=flash_loan_params.get("pools_involved", 1),
            price_change_pct=flash_loan_params.get("price_change_pct", 0),
            has_collateral=flash_loan_params.get("has_collateral", True),
        )

    # Oracle check
    if oracle_prices:
        report.oracle = check_oracle_deviation(oracle_prices)

    # MEV check
    if mev_params:
        report.mev = scan_mev_vulnerability(
            has_slippage_protection=mev_params.get("has_slippage_protection", False),
            slippage_tolerance_bps=mev_params.get("slippage_tolerance_bps"),
            uses_commit_reveal=mev_params.get("uses_commit_reveal", False),
            has_timelock=mev_params.get("has_timelock", False),
            is_public_mempool=mev_params.get("is_public_mempool", True),
            tx_value_usd=mev_params.get("tx_value_usd", 0),
            has_deadline=mev_params.get("has_deadline", False),
            deadline_minutes=mev_params.get("deadline_minutes"),
        )

    # Health check
    if health_params:
        report.health = assess_pool_health(
            tvl_usd=health_params.get("tvl_usd", 0),
            volume_24h_usd=health_params.get("volume_24h_usd"),
            fee_bps=health_params.get("fee_bps", 30),
            reserve0_usd=health_params.get("reserve0_usd"),
            reserve1_usd=health_params.get("reserve1_usd"),
            has_oracle=health_params.get("has_oracle", False),
            is_verified=health_params.get("is_verified", False),
            age_days=health_params.get("age_days"),
        )

    # Compute overall score
    scores = []
    critical: list[str] = []

    if report.slippage and not report.slippage.is_safe:
        scores.append(max(0, 100 - report.slippage.slippage_pct * 2))
        if report.slippage.slippage_pct > 2.0:
            critical.append(f"Slippage: {report.slippage.slippage_pct:.1f}% — {report.slippage.warning}")
    elif report.slippage:
        scores.append(90)

    if report.flash_loan:
        scores.append(100 - report.flash_loan.risk_score)
        if report.flash_loan.risk_score >= 60:
            critical.append(f"Flash loan risk: {report.flash_loan.risk_score}/100 — {report.flash_loan.reasoning}")

    if report.oracle and report.oracle.is_suspicious:
        scores.append(max(0, 100 - report.oracle.max_deviation_pct * 10))
        critical.append(f"Oracle deviation: {report.oracle.max_deviation_pct:.1f}% — {report.oracle.reasoning}")
    elif report.oracle:
        scores.append(95)

    if report.mev:
        scores.append(100 - report.mev.risk_score)
        if report.mev.risk_score >= 50:
            critical.append(f"MEV risk: {report.mev.risk_score}/100 — {', '.join(report.mev.findings[:2])}")

    if report.health:
        scores.append(report.health.health_score)
        for w in report.health.warnings[:2]:
            if "critical" in w.lower() or "extreme" in w.lower():
                critical.append(f"Pool health: {w}")

    if scores:
        report.overall_score = round(sum(scores) / len(scores))
        report.overall_score = max(0, min(100, report.overall_score))

    report.critical_findings = critical
    return report
