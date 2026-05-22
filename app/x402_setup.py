import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from x402 import x402ResourceServer
from x402.http import (
    RouteConfig,
    PaymentOption,
)
from x402.http.middleware.fastapi import (
    payment_middleware,
    PaywallConfig,
)
from x402.mechanisms.evm.exact import register_exact_evm_server

from x402.http.facilitator_client import HTTPFacilitatorClient, FacilitatorConfig
from app.facilitator import DirectFacilitator
from app.config import settings

logger = logging.getLogger("x402")

CDP_FACILITATOR_URL = "https://api.cdp.coinbase.com/platform/v2/x402"
PAYAI_FACILITATOR_URL = "https://facilitator.payai.network"
CHAOSCHAIN_FACILITATOR_URL = "https://facilitator.chaoscha.in"

# Token rate: $0.003 per 1K tokens (DeepSeek cost ~$0.0014/1K, x2 margin)
PER_1K_TOKENS_MICROUNITS = 3000


def validate_min_price(request, min_microunits: int):
    """Check x402 payment has sufficient authorized amount BEFORE calling AI.
    Returns (ok: bool, error_json: dict | None).
    Call BEFORE deepseek_completion in upto routes to avoid wasting tokens on underpayment.
    """
    # API key users have their own credit system — skip check
    if hasattr(request.state, "human_api_key"):
        return True, None

    # No payment info at all — fail closed, don't silently allow free AI calls
    if not hasattr(request.state, "payment_requirements"):
        return False, {
            "error": "payment_required",
            "message": "x402 payment data missing. Ensure payment-signature header is present.",
        }

    try:
        authorized = int(request.state.payment_requirements.amount)
    except (ValueError, TypeError):
        return True, None

    if authorized < min_microunits:
        mins = min_microunits / 1e6
        auths = authorized / 1e6
        return False, {
            "error": "insufficient_payment",
            "message": f"Payment authorized ${auths:.4f}, minimum ${mins:.4f}. Please authorize at least ${mins:.4f} USDC.",
            "authorized_microunits": authorized,
            "min_required_microunits": min_microunits,
            "retry_with_higher_amount": True,
        }
    return True, None


async def settle_actual_usage(request, actual_microunits: int):
    """Mark actual settlement amount for upto pricing.

    Does NOT call facilitator.settle() — the x402 middleware handles settlement
    via Settlement-Overrides header (set in x402_response_header_middleware).
    """
    # Only for real x402 payments (not API keys)
    if hasattr(request.state, "human_api_key"):
        return
    if not hasattr(request.state, "payment_payload"):
        return

    request.state.x402_settled = True
    request.state.x402_settled_amount = actual_microunits
    logger.info("Settlement queued: %d microunits (~$%.4f)",
        actual_microunits, actual_microunits / 1e6)

# Solana mainnet (reserved for future use)
SOLANA_NET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# AI services: upto pricing (pay per actual usage)
_UPTO_SERVICES = {
    "POST /api/audit":          ("$0.05", "Security scan with OWASP Top 10 + SWC Registry taxonomy"),
    "POST /api/refactor":       ("$0.05", "Refactor legacy code — DRY, SOLID, modern patterns"),
    "POST /api/docs":           ("$0.03", "Generate technical docs with architecture, signatures, examples"),
    "POST /api/defi-analyze":   ("$0.04", "DeFi protocol analysis: risks, tokenomics, architecture"),
    "POST /api/trading-signal": ("$0.03", "Crypto trading analytics — qualitative, NOT financial advice"),
    "POST /api/solidity-scan":  ("$0.08", "Solidity vulnerability scanner — 36 SWC checks + DeFi exploits"),
    "POST /api/nl-to-sql":      ("$0.03", "Convert natural language descriptions to SQL queries"),
    "POST /api/sql-to-nl":      ("$0.02", "Explain SQL queries in plain English"),
    "POST /api/git-summarize":  ("$0.02", "Summarize git diff into PR description"),
    "POST /api/translate-code": ("$0.05", "Translate code between languages (Python, TS, Rust, Go, Solidity)"),
    "POST /api/whale-tracker":   ("$0.03", "Whale movement analysis — large USDC transfers on Base/Arbitrum"),
    "POST /api/smart-money":     ("$0.05", "Smart money wallet analysis — win rate, patterns, profitability"),
    "POST /api/price-feed":      ("$0.02", "AI-enhanced token price analysis with support/resistance levels"),
    "POST /api/agent-audit":     ("$0.50", "Full AI agent security audit — code, behavior, trust score"),
    "POST /api/contract-verify": ("$1.00", "Smart contract formal verification — 36 SWC + DeFi exploits"),
    "POST /api/security-score":  ("$0.10", "Rapid security assessment — quick score and risk level"),
    "POST /api/data-feed":       ("$0.02", "Structured data feed on any topic — machine-readable JSON"),
    "POST /api/debug-log":       ("$0.03", "CI/CD error log analysis — root cause and fix suggestions"),
}

# Micro-tasks: exact pricing (flat fee)
_EXACT_SERVICES = {
    "POST /api/validate-json":  ("$0.0005", "Validate JSON/YAML structure, schema, types"),
    "POST /api/classify-text":  ("$0.001",  "Classify text: sentiment, category, keywords, language"),
    "POST /api/extract-data":   ("$0.005",  "Extract structured data: names, emails, phones, URLs, dates"),
    "POST /api/generate-regex": ("$0.002",  "Generate regex pattern from description with test cases"),
    "POST /api/format-data":    ("$0.003",  "Convert data: CSV to JSON, JSON to YAML, etc."),
    "POST /api/summarize":      ("$0.002",  "Summarize text to N words, extract key points"),
}

# Input schemas for Bazaar discovery
_SCHEMAS = {
    "POST /api/audit":          {"code": "string", "context": "string (optional)"},
    "POST /api/refactor":       {"code": "string", "instructions": "string (optional)", "context": "string (optional)"},
    "POST /api/docs":           {"code": "string", "context": "string (optional)"},
    "POST /api/defi-analyze":   {"protocol": "string", "chain": "string (optional)", "details": "string (optional)", "onchain_data": "string (optional)"},
    "POST /api/trading-signal": {"asset": "string", "timeframe": "string (optional)", "additional_info": "string (optional)"},
    "POST /api/solidity-scan":  {"code": "string", "context": "string (optional)"},
    "POST /api/nl-to-sql":      {"query": "string"},
    "POST /api/sql-to-nl":      {"sql": "string"},
    "POST /api/git-summarize":  {"diff": "string"},
    "POST /api/translate-code": {"code": "string", "source_lang": "string", "target_lang": "string"},
    "POST /api/validate-json":  {"data": "string", "schema": "string (optional)"},
    "POST /api/classify-text":  {"text": "string", "categories": "string (optional)"},
    "POST /api/extract-data":   {"text": "string"},
    "POST /api/generate-regex": {"description": "string"},
    "POST /api/format-data":    {"data": "string", "source_format": "csv|json|yaml", "target_format": "csv|json|yaml"},
    "POST /api/summarize":      {"text": "string", "max_length": "integer (optional)"},
    "POST /api/whale-tracker": {"asset": "string", "wallet_address": "string (optional)", "timeframe": "string (optional)"},
    "POST /api/smart-money":   {"wallet_address": "string", "chain": "string (optional)"},
    "POST /api/price-feed":    {"token": "string"},
    "POST /api/agent-audit": {"agent_code": "string", "behavior_description": "string (optional)", "agent_name": "string (optional)"},
    "POST /api/contract-verify": {"contract_code": "string", "contract_name": "string (optional)", "network": "string (optional)"},
    "POST /api/security-score": {"code": "string", "description": "string (optional)"},
    "POST /api/data-feed":  {"topic": "string", "format": "string (optional)"},
    "POST /api/debug-log":  {"log": "string", "context": "string (optional)"},
}


def configure_x402(
    app: FastAPI,
    pay_to_evm: str,
    pay_to_tron: str | None,
    testnet: bool = True,
) -> None:
    mode = settings.facilitator_mode

    if mode == "cdp":
        # CDP Facilitator — required for agentic.market listing (needs Coinbase KYC)
        if not settings.cdp_api_key_id or not settings.cdp_api_key_secret:
            logger.warning(
                "facilitator_mode=cdp but CDP_API_KEY_ID/CDP_API_KEY_SECRET not set. "
                "Falling back to PayAI."
            )
            mode = "payai"

    if mode == "payai_auth":
        # PayAI Facilitator with merchant API key — registered merchant, visible on Bazaar
        if not settings.payai_api_key_id or not settings.payai_api_key_secret:
            logger.warning(
                "facilitator_mode=payai_auth but PAYAI_API_KEY_ID/PAYAI_API_KEY_SECRET not set. "
                "Falling back to unauthenticated payai."
            )
            mode = "payai"

    if mode == "cdp":
        from app.cdp_auth import create_cdp_auth_provider

        auth_provider = create_cdp_auth_provider(
            settings.cdp_api_key_id,
            settings.cdp_api_key_secret,
        )
        facilitator = HTTPFacilitatorClient(
            FacilitatorConfig(
                url=CDP_FACILITATOR_URL,
                timeout=30.0,
                auth_provider=auth_provider,
                identifier="cdp",
            )
        )
        logger.info("x402: using CDP Facilitator at %s (agentic.market listing enabled)", CDP_FACILITATOR_URL)
    elif mode == "payai_auth":
        from app.payai_auth import create_payai_auth_provider
        auth_provider = create_payai_auth_provider(
            settings.payai_api_key_id,
            settings.payai_api_key_secret,
        )
        facilitator = HTTPFacilitatorClient(
            FacilitatorConfig(
                url=PAYAI_FACILITATOR_URL,
                timeout=30.0,
                auth_provider=auth_provider,
                identifier="payai",
            )
        )
        logger.info("x402: using PayAI Facilitator at %s (registered merchant, Bazaar visible)", PAYAI_FACILITATOR_URL)
    elif mode == "payai":
        facilitator = HTTPFacilitatorClient(
            FacilitatorConfig(
                url=PAYAI_FACILITATOR_URL,
                timeout=30.0,
                identifier="payai",
            )
        )
        logger.info("x402: using PayAI Facilitator at %s (no KYC, free)", PAYAI_FACILITATOR_URL)
    elif mode == "chaoschain":
        facilitator = HTTPFacilitatorClient(
            FacilitatorConfig(
                url=CHAOSCHAIN_FACILITATOR_URL,
                timeout=30.0,
                identifier="chaoschain",
            )
        )
        logger.info("x402: using ChaosChain Facilitator at %s (BFT-verified, ERC-8004 identity)", CHAOSCHAIN_FACILITATOR_URL)
    elif testnet:
        facilitator = DirectFacilitator(testnet=True, pay_to=pay_to_evm)
        logger.info("x402: using DirectFacilitator (testnet mode)")
    else:
        facilitator = DirectFacilitator(testnet=False, pay_to=pay_to_evm)
        logger.info("x402: using DirectFacilitator (mainnet — onchain RPC verification)")

    server = x402ResourceServer(facilitator)

    if testnet:
        evm_networks = [
            "eip155:84532",      # Base Sepolia
            "eip155:421614",     # Arbitrum Sepolia
            "eip155:11155420",   # Optimism Sepolia
        ]
    else:
        evm_networks = [
            "eip155:8453",       # Base mainnet
            "eip155:42161",      # Arbitrum mainnet
            "eip155:10",         # Optimism mainnet
        ]
    register_exact_evm_server(server, evm_networks)

    # Store facilitator on app.state so routes can call settle() with actual usage
    app.state.x402_facilitator = facilitator
    app.state.x402_pay_to = pay_to_evm
    logger.info("x402: facilitator stored on app.state — routes will settle with actual usage")

    # PayAI and ChaosChain only support Base; Direct supports all 3 EVM networks
    if mode in ("payai", "payai_auth", "chaoschain"):
        common_networks = ["eip155:8453"] if not testnet else ["eip155:84532"]
    else:
        common_networks = list(evm_networks)

    def make_upto_option(network: str, max_price: str) -> PaymentOption:
        """AI services: agent authorizes max price (exact), we settle actual usage."""
        return PaymentOption(
            scheme="exact",
            pay_to=pay_to_evm,
            price=max_price,       # max authorized amount (settled at actual)
            network=network,
        )

    def make_exact_option(network: str, price: str) -> PaymentOption:
        """Exact/flat pricing: fixed micro-fee for micro-tasks."""
        return PaymentOption(
            scheme="exact",
            pay_to=pay_to_evm,
            price=price,
            network=network,
        )

    def _bazaar_schema(route_key: str) -> dict:
        """Build Bazaar extension inputSchema for PayAI validation."""
        props = _SCHEMAS.get(route_key, {})
        required = [k for k, v in props.items() if "optional" not in v.lower()]
        schema_props = {}
        for k, v in props.items():
            type_str = "string"
            if "integer" in v.lower():
                type_str = "integer"
            elif "boolean" in v.lower():
                type_str = "boolean"
            desc = v.replace(" (optional)", "").replace("(optional)", "")
            schema_props[k] = {"type": type_str, "description": desc.strip()}
        return {
            "type": "object",
            "properties": schema_props,
            "required": required,
        }

    routes: dict[str, RouteConfig] = {}

    for route_key, (price, desc) in _UPTO_SERVICES.items():
        routes[route_key] = RouteConfig(
            accepts=[make_upto_option(net, price) for net in common_networks],
            description=desc,
            mime_type="application/json",
            extensions={"bazaar": {"discoverable": True, "info": {"input": {"type": "http"}}}},
        )

    for route_key, (price, desc) in _EXACT_SERVICES.items():
        routes[route_key] = RouteConfig(
            accepts=[make_exact_option(net, price) for net in common_networks],
            description=desc,
            mime_type="application/json",
            extensions={"bazaar": {"discoverable": True, "info": {"input": {"type": "http"}}}},
        )

    paywall = PaywallConfig(
        app_name="AI Agent API — 16 pay-per-call services ($0.0005–$0.08 USDC)",
    )

    from app.services import analytics

    x402_mw = payment_middleware(routes, server, paywall_config=paywall)

    networks_help = "Base, Arbitrum, or Optimism"
    PAYMENT_HELP = (
        "To use this API, send USDC to {pay_to} on {nets}, "
        "then retry with header payment-signature: <base64-json>. "
        "MCP: https://agent-api-ai.duckdns.org/mcp/sse "
        "Docs: https://github.com/AntoNYak0/ai-agent-api"
    ).format(pay_to=pay_to_evm, nets=networks_help)

    @app.middleware("http")
    async def x402_response_header_middleware(request, call_next):
        """Add PAYMENT-RESPONSE + Settlement-Overrides headers (INNER — runs before x402 settlement)."""
        response = await call_next(request)
        if hasattr(request.state, "x402_settled") and request.state.x402_settled:
            amount = getattr(request.state, "x402_settled_amount", 0)
            response.headers["PAYMENT-RESPONSE"] = "true"
            response.headers["X-Payment-Amount"] = f"${amount / 1e6:.6f} USDC"
            response.headers["Settlement-Overrides"] = __import__("json").dumps({"amount": str(amount)})
            logger.info("PAYMENT-RESPONSE: settlement override %d microunits", amount)
        return response

    @app.middleware("http")
    async def x402_payment_middleware(request, call_next):
        # Human devs with API key skip x402 crypto payment
        if hasattr(request.state, "human_api_key"):
            return await call_next(request)

        # Feature flag: bypass payment wall when disabled
        if not settings.x402_enabled:
            response = await call_next(request)
            response.headers["X-X402-Bypassed"] = "true"
            return response

        try:
            response = await x402_mw(request, call_next)
            if response.status_code == 402:
                # Add human-readable help header
                response.headers["X-Payment-Help"] = PAYMENT_HELP.replace("\n", " ")
                logger.info("402 Payment Required: %s %s", request.method, request.url.path)
                analytics.increment_attempt(request.url.path)
            return response
        except Exception as e:
            logger.error("x402 middleware error: %s: %s", type(e).__name__, e)
            return JSONResponse(
                status_code=402,
                content={
                    "x402Version": 2,
                    "error": "Payment required",
                    "message": "x402 payment processing error — retry with payment-signature header",
                    "detail": str(e) if str(e) else "unknown error",
                },
                headers={
                    "PAYMENT-REQUIRED": "true",
                    "X-Payment-Help": PAYMENT_HELP.replace("\n", " "),
                },
            )
