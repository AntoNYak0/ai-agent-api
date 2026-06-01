"""MCP server — exposes paid AI tools to other AI agents via x402.

29 tools: 18 upto services + 6 micro-tasks + 4 composite skills + run-workflow.
AI services use upto (usage-based) pricing; micro-tasks use exact (flat) pricing.
All priced for machine-to-machine economy ($0.001–$1.00 USDC).
"""
import logging
from mcp.server.fastmcp import FastMCP
from app.config import settings
from app.services.deepseek import deepseek_completion
from app.services.replay_guard import is_replay
from app.pricing import (
    round_up_cents, PER_1K_TOKENS_MICROUNITS, CREDIT_MULTIPLIER, get_max_tokens,
    AI_UPTO_SERVICES as _AI_UPTO, EXACT_SERVICES as _EXACT, COMPOSITE_SKILLS as _COMPOSITE,
    _TOOL_NAMES, calc_upto_cost,
)
from app.services import credits
from app.prompts.audit import AUDIT_SYSTEM_PROMPT
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT
from app.prompts.docs import DOCS_SYSTEM_PROMPT
from app.prompts.defi import DEFI_SYSTEM_PROMPT
from app.prompts.trading import TRADING_SYSTEM_PROMPT
from app.prompts.solidity_scan import SOLIDITY_SCAN_PROMPT
from app.prompts.micro import (
    VALIDATE_JSON_PROMPT, CLASSIFY_TEXT_PROMPT, EXTRACT_DATA_PROMPT,
    TRANSLATE_CODE_PROMPT, GENERATE_REGEX_PROMPT, FORMAT_DATA_PROMPT,
    SUMMARIZE_PROMPT, NL_TO_SQL_PROMPT, SQL_TO_NL_PROMPT, GIT_SUMMARIZE_PROMPT,
    DEBUG_LOG_PROMPT,
)
from app.prompts.defi_signals import WHALE_TRACKER_PROMPT, SMART_MONEY_PROMPT, PRICE_FEED_PROMPT
from app.prompts.security import AGENT_AUDIT_PROMPT, CONTRACT_VERIFY_PROMPT, SECURITY_SCORE_PROMPT
from app.prompts.data_feed import DATA_FEED_PROMPT
from app.services import workflow_registry, workflow_analytics
from x402.http.facilitator_client import HTTPFacilitatorClient, FacilitatorConfig
from app.facilitator import DirectFacilitator, TronFacilitator, TRON_NETWORK, USDT_TRC20_CONTRACT
from mcp.server.fastmcp.server import TransportSecuritySettings

logger = logging.getLogger("mcp_server")

mcp = FastMCP(
    name="ai-agent-api",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True),
    instructions="""
AI Agent API — 16 pay-per-call tools for developers and AI agents via x402.

Complex services (upto pricing — pay per usage):
- audit ($0.01–$0.05 USDC) — security scan with OWASP + SWC taxonomy
- refactor ($0.01–$0.05 USDC) — legacy code modernization (DRY, SOLID)
- docs ($0.005–$0.03 USDC) — technical documentation from code
- defi ($0.01–$0.04 USDC) — DeFi protocol analysis
- trading ($0.005–$0.03 USDC) — crypto market analysis (training data only)
- solidity-scan ($0.02–$0.08 USDC) — specialized Solidity vulnerability scanner

SQL services (upto pricing):
- nl-to-sql ($0.005–$0.03 USDC) — natural language to SQL
- sql-to-nl ($0.005–$0.02 USDC) — SQL to plain English
- translate-code ($0.01–$0.05 USDC) — code translation between languages

Dev tools (upto pricing):
- git-summarize ($0.005–$0.02 USDC) — git diff to PR description

Micro-tasks (exact pricing):
- validate-json ($0.001 USDC) — validate JSON/YAML
- classify-text ($0.001 USDC) — sentiment + category
- extract-data ($0.005 USDC) — extract structured data from text
- generate-regex ($0.002 USDC) — regex from description
- format-data ($0.003 USDC) — convert CSV/JSON/YAML
- summarize ($0.002 USDC) — summarize to N words

Payment: USDC on Base/Arbitrum/Optimism or USDT on Tron.
Send USDC/USDT, then call tool with payment_tx=<transaction-hash>.
Wallet EVM: 0xdE7eb04faE758055642f67f30D246CcB7136C95E
""",
)

mode = settings.facilitator_mode

if mode == "cdp" and settings.cdp_api_key_id and settings.cdp_api_key_secret:
    from app.cdp_auth import create_cdp_auth_provider
    auth_provider = create_cdp_auth_provider(settings.cdp_api_key_id, settings.cdp_api_key_secret)
    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(
            url="https://api.cdp.coinbase.com/platform/v2/x402",
            timeout=30.0,
            auth_provider=auth_provider,
            identifier="cdp",
        )
    )
    logger.info("MCP: using CDP Facilitator (agentic.market listing enabled)")
elif mode == "payai_auth" and settings.payai_api_key_id and settings.payai_api_key_secret:
    from app.payai_auth import create_payai_auth_provider
    auth_provider = create_payai_auth_provider(settings.payai_api_key_id, settings.payai_api_key_secret)
    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(
            url="https://facilitator.payai.network",
            timeout=30.0,
            auth_provider=auth_provider,
            identifier="payai",
        )
    )
    logger.info("MCP: using PayAI Facilitator (registered merchant, Bazaar visible)")
elif mode == "payai":
    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(
            url="https://facilitator.payai.network",
            timeout=30.0,
            identifier="payai",
        )
    )
    logger.info("MCP: using PayAI Facilitator (no KYC, free)")
elif mode == "chaoschain":
    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(
            url="https://facilitator.chaoscha.in",
            timeout=30.0,
            identifier="chaoschain",
        )
    )
    logger.info("MCP: using ChaosChain Facilitator (BFT-verified, ERC-8004 identity)")
elif settings.testnet:
    facilitator = DirectFacilitator(testnet=True, pay_to=settings.pay_to_address_evm)
    logger.info("MCP: using DirectFacilitator (testnet mode)")
else:
    facilitator = DirectFacilitator(testnet=False, pay_to=settings.pay_to_address_evm)
    logger.info("MCP: using DirectFacilitator (mainnet — onchain RPC)")

# Separate TRON facilitator (Dexter doesn't support TRON)
tron_facilitator = None
if settings.pay_to_address_tron:
    tron_facilitator = TronFacilitator(pay_to_tron=settings.pay_to_address_tron)
    logger.info("MCP: TRON enabled via TronFacilitator -> %s", settings.pay_to_address_tron)

PAY_TO = settings.pay_to_address_evm
PAY_TO_TRON = settings.pay_to_address_tron

# Network CAIP-2 → USDC asset contract on each supported chain
_NETWORK_ASSETS = {
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",    # Base USDC
    "eip155:42161": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",   # Arbitrum USDC
    "eip155:10": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",     # Optimism USDC
    "eip155:56": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",     # BNB Chain USDC
}

def _credits_cost_cents(microunits: int) -> int:
    """Convert microunits to credit cents with 1.5x multiplier, min 1 cent."""
    cents = (microunits / 10000) * CREDIT_MULTIPLIER
    return round_up_cents(cents)


def _safe_summarize_prompt(max_length: int = 100) -> str:
    """Safely inject max_length into SUMMARIZE_PROMPT. Falls back gracefully."""
    if "__MAX_LENGTH__" in SUMMARIZE_PROMPT:
        return SUMMARIZE_PROMPT.replace("__MAX_LENGTH__", str(max_length))
    return SUMMARIZE_PROMPT


def _deduct_credits(api_key: str, cost_cents: int, tool_name: str = "unknown") -> bool:
    """Deduct credits and log if it fails. Returns True if deduction succeeded."""
    ok = credits.spend_credits(api_key, cost_cents)
    if not ok:
        logger.warning("spend_credits failed: tool=%s key=%s... cents=%s",
                       tool_name, api_key[:10], cost_cents)
    return ok

# ── Pricing tables (built from pricing.py single source of truth) ──

def _parse_price_to_microunits(price_str: str) -> int:
    """Parse "$0.05" → 50000 microunits."""
    return int(float(price_str.replace("$", "").replace(",", "")) * 1_000_000)

# Build reverse: pricing_key → MCP tool name
_pricing_to_mcp = {v: k for k, v in _TOOL_NAMES.items() if v is not None}

PRICES: dict[str, str] = {}
AMOUNTS: dict[str, str] = {}

# AI upto services
for pricing_key, svc in _AI_UPTO.items():
    mcp_name = _pricing_to_mcp.get(pricing_key)
    if mcp_name is None:
        continue
    base = svc["base_microunits"]
    max_mu = _parse_price_to_microunits(svc["max_price"])
    base_usd = base / 1_000_000
    if base_usd >= 0.01:
        base_str = f"${base_usd:.2f}"
    else:
        base_str = f"${base_usd:.3f}"
    PRICES[mcp_name] = f"{base_str}–{svc['max_price']}"
    AMOUNTS[mcp_name] = str(max_mu)

# Micro-tasks (exact pricing)
for pricing_key, svc in _EXACT.items():
    mcp_name = _pricing_to_mcp.get(pricing_key)
    if mcp_name is None:
        continue
    PRICES[mcp_name] = svc["price"]
    AMOUNTS[mcp_name] = str(svc["microunits"])

# Composite skills
for pricing_key, svc in _COMPOSITE.items():
    mcp_name = pricing_key.replace("_", "-")
    microunits = _parse_price_to_microunits(svc["price"])
    PRICES[mcp_name] = svc["price"]
    AMOUNTS[mcp_name] = str(microunits)


async def _verify_payment(payment_tx: str, amount: str, tool_name: str = "unknown", api_key: str = "", network: str = "eip155:8453") -> tuple[bool, str]:
    """Verify payment (x402 or API key credits). Returns (is_valid, info_message)."""
    # 1. API key credits (human developers)
    if api_key:
        balance = credits.get_balance(api_key)
        if not balance:
            return False, f"Invalid API key: {api_key[:10]}..."
        cost_cents = _credits_cost_cents(int(amount))
        cost_credits = cost_cents * 10  # 10 credits per cent
        if balance["credits"] < cost_credits:
            return False, f"API key needs {cost_credits} credits, has {balance['credits']}. Top up at /billing/top-up"
        return True, f"credits:{api_key}"

    # 2. x402 crypto payment (AI agents)
    if settings.testnet:
        return True, "testnet"

    if not payment_tx:
        usdc_amount = int(amount) / 1e6
        tron_note = f" or USDT to {PAY_TO_TRON} on Tron" if PAY_TO_TRON else ""
        return False, (
            f"Payment required: send {usdc_amount} USDC to {PAY_TO} "
            f"on Base/Arbitrum/Optimism{tron_note}, then call with payment_tx=<hash>"
        )

    # Replay protection
    if is_replay(payment_tx, tool_name):
        return False, "Payment already used. Each transaction can only be used once per tool."

    from x402.schemas import PaymentPayload, PaymentRequirements, ResourceInfo

    resource_info = ResourceInfo(
        url="https://agent-api-ai.duckdns.org/mcp/sse",
        mime_type="text/event-stream",
        service_name="AI Agent API MCP",
    )

    payload = PaymentPayload(
        x402_version=2,
        payload={"transactionHash": payment_tx, "payer": "mcp-client"},
        accepted=PaymentRequirements(
            scheme="exact",
            network=network,
            asset=_NETWORK_ASSETS.get(network, _NETWORK_ASSETS["eip155:8453"]),
            amount=amount,
            pay_to=PAY_TO,
            max_timeout_seconds=300,
        ),
        resource=resource_info,
    )
    requirements = PaymentRequirements(
        scheme="exact",
        network=network,
        asset=_NETWORK_ASSETS.get(network, _NETWORK_ASSETS["eip155:8453"]),
        amount=amount,
        pay_to=PAY_TO,
        max_timeout_seconds=300,
    )

    try:
        result = await facilitator.verify(payload, requirements)
    except Exception as e:
        logger.error("Payment verification failed for tx %s...: %s", payment_tx[:16], e)
        return False, f"Payment verification service unavailable. Try again shortly."

    if result.is_valid:
        logger.info("Payment verified: tool=%s tx=%s...", tool_name, payment_tx[:16])
        return True, result.payer or "verified"
    logger.warning(
        "Payment rejected: tool=%s tx=%s... reason=%s",
        tool_name, payment_tx[:16], result.invalid_reason,
    )
    return False, result.invalid_message or "Payment verification failed"


def _payment_help(service: str) -> str:
    tron_part = f" or USDT to {PAY_TO_TRON} on Tron" if PAY_TO_TRON else ""
    return (
        f"To use this tool, send {PRICES[service]} USDC to {PAY_TO} "
        f"on Base (eip155:8453), Arbitrum (eip155:42161), Optimism (eip155:10), BNB Chain (eip155:56){tron_part}, "
        f"then call again with payment_tx=<transaction-hash>"
    )


def _calc_upto_amount(service: str, tokens_used: int) -> int:
    """Calculate actual cost for upto service using complexity-based pricing.
    Simple (<500 tokens): 0.5x multiplier, Normal (500-3000): 1.0x, Complex (>3000): 1.5x.
    Result is capped at the service's max_price.
    """
    pricing_key = _TOOL_NAMES.get(service)
    svc = _AI_UPTO.get(pricing_key) if pricing_key else None
    if svc is None:
        return int((tokens_used / 1000) * PER_1K_TOKENS_MICROUNITS)
    base = svc["base_microunits"]
    max_amount = _parse_price_to_microunits(svc["max_price"])
    microunits, _, _ = calc_upto_cost(base, tokens_used, max_amount)
    return microunits


async def _settle_payment(payment_tx: str, actual_amount: int, network: str = "eip155:8453"):
    """Settle upto payment with actual usage amount."""
    if settings.testnet:
        return
    try:
        from x402.schemas import PaymentPayload, PaymentRequirements, ResourceInfo
        resource_info = ResourceInfo(
            url="https://agent-api-ai.duckdns.org/mcp/sse",
            mime_type="text/event-stream",
            service_name="AI Agent API MCP",
        )
        payload = PaymentPayload(
            x402_version=2,
            payload={"transactionHash": payment_tx, "payer": "mcp-client"},
            accepted=PaymentRequirements(
                scheme="exact",
                network=network,
                asset=_NETWORK_ASSETS.get(network, _NETWORK_ASSETS["eip155:8453"]),
                amount=str(actual_amount),
                pay_to=PAY_TO,
                max_timeout_seconds=300,
            ),
            resource=resource_info,
        )
        await facilitator.settle(payload, payload.accepted)
    except Exception as e:
        logger.warning(f"Settle failed (non-critical): {e}")


# ── Complex services (upto pricing) ─────────────────────────────

@mcp.tool(name="audit", description=f"Security scan with OWASP + SWC taxonomy. Price: {PRICES['audit']} USDC.")
async def audit_tool(code: str, context: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["audit"], "audit", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('audit')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(AUDIT_SYSTEM_PROMPT, code, context or None, json_mode=True, max_tokens=get_max_tokens("audit"))
    actual = _calc_upto_amount("audit", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="refactor", description=f"Refactor legacy code (DRY, SOLID). Price: {PRICES['refactor']} USDC.")
async def refactor_tool(code: str, instructions: str = "", context: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["refactor"], "refactor", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('refactor')}"
    use_credits = info.startswith("credits:")
    user_content = f"Instructions: {instructions}\n\nCode:\n{code}" if instructions else code
    result, tokens, _ = await deepseek_completion(REFACTOR_SYSTEM_PROMPT, user_content, context or None, json_mode=True, max_tokens=get_max_tokens("refactor"))
    actual = _calc_upto_amount("refactor", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="docs", description=f"Generate technical docs from code. Price: {PRICES['docs']} USDC.")
async def docs_tool(code: str, context: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["docs"], "docs", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('docs')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(DOCS_SYSTEM_PROMPT, code, context or None, json_mode=True, max_tokens=get_max_tokens("docs"))
    actual = _calc_upto_amount("docs", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="defi", description=f"DeFi protocol analysis. Price: {PRICES['defi']} USDC.")
async def defi_tool(protocol: str, chain: str = "Ethereum", details: str = "", onchain_data: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["defi"], "defi", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('defi')}"
    use_credits = info.startswith("credits:")
    user_content = f"Protocol: {protocol}\nBlockchain: {chain}"
    if details:
        user_content += f"\n\nDetails: {details}"
    if onchain_data:
        user_content += f"\n\nProvided onchain data:\n{onchain_data}"
    result, tokens, _ = await deepseek_completion(DEFI_SYSTEM_PROMPT, user_content, json_mode=True, max_tokens=get_max_tokens("defi"))
    actual = _calc_upto_amount("defi", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="trading", description=f"Crypto trading analytics. Price: {PRICES['trading']} USDC.")
async def trading_tool(asset: str, timeframe: str = "daily", additional_info: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["trading"], "trading", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('trading')}"
    use_credits = info.startswith("credits:")
    user_content = f"Asset: {asset}\nTimeframe: {timeframe}"
    if additional_info:
        user_content += f"\n\nAdditional info: {additional_info}"
    result, tokens, _ = await deepseek_completion(TRADING_SYSTEM_PROMPT, user_content, json_mode=True, max_tokens=get_max_tokens("trading"))
    actual = _calc_upto_amount("trading", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── DeFi Signals (upto pricing) ──────────────────────────────────

@mcp.tool(name="whale-tracker", description=f"Track whale wallet movements for an asset. Price: {PRICES['whale-tracker']} USDC.")
async def whale_tracker_tool(asset: str, wallet_address: str = "", timeframe: str = "24h", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["whale-tracker"], "whale-tracker", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('whale-tracker')}"
    use_credits = info.startswith("credits:")
    content = f"Asset: {asset}\nTimeframe: {timeframe}"
    if wallet_address:
        content += f"\nWallet: {wallet_address}"
    result, tokens, _ = await deepseek_completion(WHALE_TRACKER_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("whale-tracker"))
    actual = _calc_upto_amount("whale-tracker", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="smart-money", description=f"Analyze smart money wallet behavior. Price: {PRICES['smart-money']} USDC.")
async def smart_money_tool(wallet_address: str, chain: str = "ethereum", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["smart-money"], "smart-money", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('smart-money')}"
    use_credits = info.startswith("credits:")
    content = f"Wallet: {wallet_address}\nChain: {chain}"
    result, tokens, _ = await deepseek_completion(SMART_MONEY_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("smart-money"))
    actual = _calc_upto_amount("smart-money", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="price-feed", description=f"Get token price and market data. Price: {PRICES['price-feed']} USDC.")
async def price_feed_tool(token: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["price-feed"], "price-feed", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('price-feed')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(PRICE_FEED_PROMPT, token, json_mode=True, max_tokens=get_max_tokens("price-feed"))
    actual = _calc_upto_amount("price-feed", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── Solidity scanner (upto pricing) ──────────────────────────────

@mcp.tool(name="solidity-scan", description=f"Solidity vulnerability scanner (SWC Registry). Price: {PRICES['solidity-scan']} USDC.")
async def solidity_scan_tool(code: str, context: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["solidity-scan"], "solidity-scan", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('solidity-scan')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(SOLIDITY_SCAN_PROMPT, code, context or None, json_mode=True, max_tokens=get_max_tokens("solidity-scan"))
    actual = _calc_upto_amount("solidity-scan", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── Security tools (upto pricing) ─────────────────────────────────

@mcp.tool(name="agent-audit", description=f"Audit AI agent code for safety and compliance. Price: {PRICES['agent-audit']} USDC.")
async def agent_audit_tool(agent_code: str, behavior_description: str = "", agent_name: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["agent-audit"], "agent-audit", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('agent-audit')}"
    use_credits = info.startswith("credits:")
    content = f"Agent: {agent_name or 'unnamed'}\nBehavior: {behavior_description or 'not specified'}\n\nCode:\n{agent_code}"
    result, tokens, _ = await deepseek_completion(AGENT_AUDIT_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("agent-audit"))
    actual = _calc_upto_amount("agent-audit", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="contract-verify", description=f"Verify smart contract against known vulnerabilities. Price: {PRICES['contract-verify']} USDC.")
async def contract_verify_tool(contract_code: str, contract_name: str = "", chain: str = "ethereum", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["contract-verify"], "contract-verify", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('contract-verify')}"
    use_credits = info.startswith("credits:")
    content = f"Contract: {contract_name or 'unnamed'}\nChain: {chain}\n\nCode:\n{contract_code}"
    result, tokens, _ = await deepseek_completion(CONTRACT_VERIFY_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("contract-verify"))
    actual = _calc_upto_amount("contract-verify", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="security-score", description=f"Score code security posture. Price: {PRICES['security-score']} USDC.")
async def security_score_tool(code: str, description: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["security-score"], "security-score", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('security-score')}"
    use_credits = info.startswith("credits:")
    content = f"Description: {description or 'code analysis'}\n\nCode:\n{code}"
    result, tokens, _ = await deepseek_completion(SECURITY_SCORE_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("security-score"))
    actual = _calc_upto_amount("security-score", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── SQL services (upto pricing) ──────────────────────────────────

@mcp.tool(name="nl-to-sql", description=f"Natural language to SQL. Price: {PRICES['nl-to-sql']} USDC.")
async def nl_to_sql_tool(query: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["nl-to-sql"], "nl-to-sql", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('nl-to-sql')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(NL_TO_SQL_PROMPT, query, json_mode=True, max_tokens=get_max_tokens("nl-to-sql"))
    actual = _calc_upto_amount("nl-to-sql", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="sql-to-nl", description=f"SQL to plain English explanation. Price: {PRICES['sql-to-nl']} USDC.")
async def sql_to_nl_tool(sql: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["sql-to-nl"], "sql-to-nl", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('sql-to-nl')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(SQL_TO_NL_PROMPT, sql, json_mode=True, max_tokens=get_max_tokens("sql-to-nl"))
    actual = _calc_upto_amount("sql-to-nl", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── Dev tools (upto pricing) ─────────────────────────────────────

@mcp.tool(name="git-summarize", description=f"Git diff to PR description. Price: {PRICES['git-summarize']} USDC.")
async def git_summarize_tool(diff: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["git-summarize"], "git-summarize", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('git-summarize')}"
    use_credits = info.startswith("credits:")
    result, tokens, _ = await deepseek_completion(GIT_SUMMARIZE_PROMPT, diff, json_mode=True, max_tokens=get_max_tokens("git-summarize"))
    actual = _calc_upto_amount("git-summarize", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="translate-code", description=f"Translate code between languages. Price: {PRICES['translate-code']} USDC.")
async def translate_code_tool(code: str, source_lang: str, target_lang: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["translate-code"], "translate-code", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('translate-code')}"
    use_credits = info.startswith("credits:")
    prompt = TRANSLATE_CODE_PROMPT.replace("__SOURCE_LANG__", source_lang).replace("__TARGET_LANG__", target_lang)
    result, tokens, _ = await deepseek_completion(prompt, code, json_mode=True, max_tokens=get_max_tokens("translate-code"))
    actual = _calc_upto_amount("translate-code", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── Data tools (upto pricing) ─────────────────────────────────────

@mcp.tool(name="data-feed", description=f"Fetch structured data feed on any topic. Price: {PRICES['data-feed']} USDC.")
async def data_feed_tool(topic: str, format: str = "json", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["data-feed"], "data-feed", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('data-feed')}"
    use_credits = info.startswith("credits:")
    content = f"Topic: {topic}\nFormat: {format}"
    result, tokens, _ = await deepseek_completion(DATA_FEED_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("data-feed"))
    actual = _calc_upto_amount("data-feed", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


@mcp.tool(name="debug-log", description=f"Analyze error logs and suggest fixes. Price: {PRICES['debug-log']} USDC.")
async def debug_log_tool(log: str, context: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["debug-log"], "debug-log", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('debug-log')}"
    use_credits = info.startswith("credits:")
    content = f"Context: {context or 'application error'}\n\nError log:\n{log}"
    result, tokens, _ = await deepseek_completion(DEBUG_LOG_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("debug-log"))
    actual = _calc_upto_amount("debug-log", tokens)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual, network)
    return result


# ── Micro-tasks (exact pricing) ──────────────────────────────────

@mcp.tool(name="validate-json", description=f"Validate JSON/YAML structure. Price: {PRICES['validate-json']} USDC.")
async def validate_json_tool(data: str, schema: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["validate-json"], "validate-json", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('validate-json')}"
    use_credits = info.startswith("credits:")
    content = f"Target schema:\n{schema}\n\nData:\n{data}" if schema else data
    result, _, _ = await deepseek_completion(VALIDATE_JSON_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("validate-json"))
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(int(AMOUNTS["validate-json"])))
    else:
        await _settle_payment(payment_tx, int(AMOUNTS["validate-json"]), network)
    return result


@mcp.tool(name="classify-text", description=f"Classify text sentiment/category. Price: {PRICES['classify-text']} USDC.")
async def classify_text_tool(text: str, categories: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["classify-text"], "classify-text", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('classify-text')}"
    use_credits = info.startswith("credits:")
    content = f"Categories hint: {categories or 'auto-detect'}\n\nText:\n{text}"
    result, _, _ = await deepseek_completion(CLASSIFY_TEXT_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("classify-text"))
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(int(AMOUNTS["classify-text"])))
    else:
        await _settle_payment(payment_tx, int(AMOUNTS["classify-text"]), network)
    return result


@mcp.tool(name="extract-data", description=f"Extract structured data from text. Price: {PRICES['extract-data']} USDC.")
async def extract_data_tool(text: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["extract-data"], "extract-data", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('extract-data')}"
    use_credits = info.startswith("credits:")
    result, _, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, text, json_mode=True, max_tokens=get_max_tokens("extract-data"))
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(int(AMOUNTS["extract-data"])))
    else:
        await _settle_payment(payment_tx, int(AMOUNTS["extract-data"]), network)
    return result


@mcp.tool(name="generate-regex", description=f"Generate regex from description. Price: {PRICES['generate-regex']} USDC.")
async def generate_regex_tool(description: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["generate-regex"], "generate-regex", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('generate-regex')}"
    use_credits = info.startswith("credits:")
    result, _, _ = await deepseek_completion(GENERATE_REGEX_PROMPT, description, json_mode=True, max_tokens=get_max_tokens("generate-regex"))
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(int(AMOUNTS["generate-regex"])))
    else:
        await _settle_payment(payment_tx, int(AMOUNTS["generate-regex"]), network)
    return result


@mcp.tool(name="format-data", description=f"Convert data CSV/JSON/YAML. Price: {PRICES['format-data']} USDC.")
async def format_data_tool(data: str, source_format: str, target_format: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["format-data"], "format-data", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('format-data')}"
    use_credits = info.startswith("credits:")
    prompt = FORMAT_DATA_PROMPT.replace("__SOURCE_FORMAT__", source_format).replace("__TARGET_FORMAT__", target_format)
    result, _, _ = await deepseek_completion(prompt, data, json_mode=True, max_tokens=get_max_tokens("format-data"))
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(int(AMOUNTS["format-data"])))
    else:
        await _settle_payment(payment_tx, int(AMOUNTS["format-data"]), network)
    return result


@mcp.tool(name="summarize", description=f"Summarize text to N words. Price: {PRICES['summarize']} USDC.")
async def summarize_tool(text: str, max_length: int = 100, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["summarize"], "summarize", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('summarize')}"
    use_credits = info.startswith("credits:")
    prompt = _safe_summarize_prompt(max_length)
    result, _, _ = await deepseek_completion(prompt, text, json_mode=True)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(int(AMOUNTS["summarize"])))
    else:
        await _settle_payment(payment_tx, int(AMOUNTS["summarize"]), network)
    return result


# ── Composite skills (multi-step workflows) ────────────────────

# Composite skill prices — derived from pricing.py COMPOSITE_SKILLS
_skill_prices = {
    pricing_key.replace("_", "-"): _parse_price_to_microunits(svc["price"])
    for pricing_key, svc in _COMPOSITE.items()
}


@mcp.tool(name="defi-research", description="Full DeFi research: extract on-chain data → analyze protocol → summarize. Price: $0.08 USDC.")
async def defi_research_tool(protocol: str, chain: str = "ethereum", onchain_data: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, _skill_prices["defi-research"], "defi-research", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('defi-research')}"
    use_credits = info.startswith("credits:")
    # Step 1: Extract structured data
    extracted, _, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, onchain_data or f"Protocol: {protocol}\nChain: {chain}", json_mode=True)
    # Step 2: DeFi analysis
    analyzed, _, _ = await deepseek_completion(DEFI_SYSTEM_PROMPT, f"Protocol: {protocol}\nBlockchain: {chain}\n\nData:\n{extracted}", json_mode=True)
    # Step 3: Summarize
    result, _, _ = await deepseek_completion(_safe_summarize_prompt(200), analyzed, json_mode=True)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(_skill_prices["defi-research"]))
    else:
        await _settle_payment(payment_tx, _skill_prices["defi-research"], network)
    return result


@mcp.tool(name="code-health-check", description="Complete code health: security audit → refactor → generate docs. Price: $0.10 USDC.")
async def code_health_check_tool(code: str, instructions: str = "", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, _skill_prices["code-health-check"], "code-health-check", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('code-health-check')}"
    use_credits = info.startswith("credits:")
    audited, _, _ = await deepseek_completion(AUDIT_SYSTEM_PROMPT, code, json_mode=True)
    refactored, _, _ = await deepseek_completion(REFACTOR_SYSTEM_PROMPT, f"Code:\n{code}\n\nAudit findings:\n{audited}", json_mode=True)
    result, _, _ = await deepseek_completion(DOCS_SYSTEM_PROMPT, refactored, json_mode=True)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(_skill_prices["code-health-check"]))
    else:
        await _settle_payment(payment_tx, _skill_prices["code-health-check"], network)
    return result


@mcp.tool(name="smart-contract-audit", description="Solidity audit + documentation: scan vulnerabilities → generate audit report. Price: $0.10 USDC.")
async def smart_contract_audit_tool(code: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, _skill_prices["smart-contract-audit"], "smart-contract-audit", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('smart-contract-audit')}"
    use_credits = info.startswith("credits:")
    scanned, _, _ = await deepseek_completion(SOLIDITY_SCAN_PROMPT, code, json_mode=True)
    result, _, _ = await deepseek_completion(DOCS_SYSTEM_PROMPT, f"Solidity audit results:\n{scanned}", json_mode=True)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(_skill_prices["smart-contract-audit"]))
    else:
        await _settle_payment(payment_tx, _skill_prices["smart-contract-audit"], network)
    return result


@mcp.tool(name="data-pipeline", description="Data processing pipeline: extract entities → convert format → summarize. Price: $0.05 USDC.")
async def data_pipeline_tool(text: str, target_format: str = "json", payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    valid, info = await _verify_payment(payment_tx, _skill_prices["data-pipeline"], "data-pipeline", api_key, network)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('data-pipeline')}"
    use_credits = info.startswith("credits:")
    extracted, _, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, text, json_mode=True)
    formatted, _, _ = await deepseek_completion(FORMAT_DATA_PROMPT.replace("__SOURCE_FORMAT__", "json").replace("__TARGET_FORMAT__", target_format), extracted, json_mode=True)
    result, _, _ = await deepseek_completion(_safe_summarize_prompt(150), formatted, json_mode=True)
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(_skill_prices["data-pipeline"]))
    else:
        await _settle_payment(payment_tx, _skill_prices["data-pipeline"], network)
    return result


# ── Workflow dispatch (run-workflow) ─────────────────────────────

# Maps pricing_key → (system_prompt, json_mode)
_WORKFLOW_DISPATCH: dict[str, tuple[str, bool]] = {
    "audit": (AUDIT_SYSTEM_PROMPT, True),
    "refactor": (REFACTOR_SYSTEM_PROMPT, True),
    "docs": (DOCS_SYSTEM_PROMPT, True),
    "defi_analyze": (DEFI_SYSTEM_PROMPT, True),
    "trading_signal": (TRADING_SYSTEM_PROMPT, True),
    "solidity_scan": (SOLIDITY_SCAN_PROMPT, True),
    "nl_to_sql": (NL_TO_SQL_PROMPT, True),
    "sql_to_nl": (SQL_TO_NL_PROMPT, True),
    "git_summarize": (GIT_SUMMARIZE_PROMPT, True),
    "validate_json": (VALIDATE_JSON_PROMPT, True),
    "classify_text": (CLASSIFY_TEXT_PROMPT, True),
    "extract_data": (EXTRACT_DATA_PROMPT, True),
    "generate_regex": (GENERATE_REGEX_PROMPT, True),
    "debug_log": (DEBUG_LOG_PROMPT, True),
    "whale_tracker": (WHALE_TRACKER_PROMPT, True),
    "smart_money": (SMART_MONEY_PROMPT, True),
    "price_feed": (PRICE_FEED_PROMPT, True),
    "agent_audit": (AGENT_AUDIT_PROMPT, True),
    "contract_verify": (CONTRACT_VERIFY_PROMPT, True),
    "security_score": (SECURITY_SCORE_PROMPT, True),
    "data_feed": (DATA_FEED_PROMPT, True),
}


def _resolve_prompt(tool_name: str) -> str | None:
    """Get system prompt for a tool by pricing_key name.
    Format-string prompts get sensible defaults for workflow chains.
    """
    entry = _WORKFLOW_DISPATCH.get(tool_name)
    if entry is None:
        return None
    prompt, _ = entry
    # Inject placeholders via replace() — prompts contain JSON braces
    # that would cause KeyError with .format()
    if tool_name == "translate_code":
        return prompt.replace("__SOURCE_LANG__", "auto").replace("__TARGET_LANG__", "python")
    if tool_name == "format_data":
        return prompt.replace("__SOURCE_FORMAT__", "json").replace("__TARGET_FORMAT__", "json")
    if tool_name == "summarize":
        return prompt.replace("__MAX_LENGTH__", "150")
    return prompt


@mcp.tool(name="run-workflow", description="Execute a user-defined composite workflow chain. Browse available workflows at /api/workflows")
async def run_workflow_tool(workflow_id: str, input_text: str, payment_tx: str = "", api_key: str = "", network: str = "eip155:8453") -> str:
    """Execute a registered composite workflow. Pays rev-share to the workflow author."""
    import time as _time

    wf = workflow_registry.get_workflow(workflow_id)
    if not wf:
        return f"Workflow not found: {workflow_id}. Browse available workflows at /api/workflows"
    if not wf.get("enabled", True):
        return f"Workflow '{wf['name']}' is currently disabled."

    chain = wf["chain"]
    price_cents = wf["price_cents"]
    platform_percent = wf.get("platform_percent", 15)

    # Verify payment — flat price per workflow execution
    microunits = price_cents * 10_000
    valid, info = await _verify_payment(payment_tx, str(microunits), "run-workflow", api_key, network)
    if not valid:
        tool_list = " → ".join(chain)
        return (
            f"Payment required: {info}\n\n"
            f"Workflow: {wf['name']} ({tool_list})\n"
            f"Price: ${price_cents / 100:.2f} USDC\n"
            f"Send USDC to {PAY_TO} on Base/Arbitrum/Optimism, then call again with payment_tx=<hash>"
        )
    use_credits = info.startswith("credits:")

    # Execute chain sequentially — each step's output is fed as input to the next
    t_start = _time.time()
    total_tokens = 0
    current_input = input_text
    chain_ok = True

    for i, tool_name in enumerate(chain):
        prompt = _resolve_prompt(tool_name)
        if prompt is None:
            chain_ok = False
            current_input = f"Error: tool '{tool_name}' is not available for workflow execution. Supported tools: {sorted(_WORKFLOW_DISPATCH.keys())}"
            break

        try:
            result_text, tokens, _ = await deepseek_completion(prompt, current_input, json_mode=True)
            total_tokens += tokens
            current_input = result_text
        except Exception as e:
            logger.error("Workflow %s step %d/%d (%s) failed: %s", workflow_id, i + 1, len(chain), tool_name, e)
            chain_ok = False
            current_input = f"Error executing step {i + 1}/{len(chain)} ({tool_name}): {e}"
            break

    latency_ms = int((_time.time() - t_start) * 1000)

    # Payment settlement
    if use_credits:
        _deduct_credits(api_key, _credits_cost_cents(microunits))
    else:
        await _settle_payment(payment_tx, microunits, network)

    # Rev-share to author
    author_key = wf.get("author_api_key", "")
    author_earnings_cents = price_cents * (100 - platform_percent) // 100
    if author_key and author_earnings_cents > 0:
        credits.credit_rev_share(author_key, author_earnings_cents)

    # Log analytics
    workflow_registry.increment_executions()
    workflow_analytics.log_execution(
        workflow_id=workflow_id,
        success=chain_ok,
        latency_ms=latency_ms,
        tokens_used=total_tokens,
        revenue_cents=price_cents,
        author_earnings_cents=author_earnings_cents,
    )

    return current_input
