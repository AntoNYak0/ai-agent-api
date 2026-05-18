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

# Token rate: $0.003 per 1K tokens (DeepSeek cost ~$0.0014/1K, x2 margin)
PER_1K_TOKENS_MICROUNITS = 3000


def validate_min_price(request, min_microunits: int):
    """Check x402 payment has sufficient authorized amount BEFORE calling AI.
    Returns (ok: bool, error_json: dict | None).
    Call BEFORE deepseek_completion in upto routes to avoid wasting tokens on underpayment.
    """
    from fastapi.responses import JSONResponse

    # API key users have their own credit system — skip check
    if hasattr(request.state, "human_api_key"):
        return True, None

    # No payment info at all — let x402 middleware handle it
    if not hasattr(request.state, "payment_requirements"):
        return True, None

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
    """Settle x402 payment with ACTUAL (not max) amount — the core of upto pricing.

    Call AFTER AI inference completes. Only settles for x402 crypto payments
    (skips API key users and testnet). Retries 3 times with backoff on facilitator failure.
    """
    import asyncio
    from x402.schemas import PaymentPayload, PaymentRequirements, ResourceInfo

    # Only settle for real x402 payments (not API keys, not testnet)
    if hasattr(request.state, "human_api_key"):
        return
    if not hasattr(request.state, "payment_payload"):
        return

    facilitator = getattr(request.app.state, "x402_facilitator", None)
    if not facilitator:
        return

    pay_to = request.app.state.x402_pay_to
    payload_obj = request.state.payment_payload
    reqs = request.state.payment_requirements

    # Build resource info from the request path (required by CDP for Bazaar indexing)
    resource_url = str(request.url).split("?")[0]  # strip query params
    resource_info = ResourceInfo(
        url=resource_url,
        mime_type="application/json",
        service_name="AI Agent API",
    )

    settle_payload = PaymentPayload(
        x402_version=2,
        payload=payload_obj.payload if hasattr(payload_obj, 'payload') else {"payer": "rest-client"},
        accepted=PaymentRequirements(
            scheme="exact",  # settlement is always exact amount
            network=getattr(reqs, 'network', 'eip155:8453'),
            asset=getattr(reqs, 'asset', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
            amount=str(actual_microunits),
            pay_to=pay_to,
            max_timeout_seconds=300,
        ),
        resource=resource_info,
    )

    for attempt in range(3):
        try:
            await facilitator.settle(settle_payload)
            request.state.x402_settled = True
            request.state.x402_settled_amount = actual_microunits
            logger.info("Settled actual: %d microunits (~$%.4f)%s",
                actual_microunits, actual_microunits / 1e6,
                f" (attempt {attempt + 1})" if attempt > 0 else "")
            return
        except Exception as e:
            if attempt < 2:
                delay = [1.0, 2.0][attempt]
                logger.warning("Settle attempt %d failed: %s. Retry in %.1fs...", attempt + 1, e, delay)
                await asyncio.sleep(delay)
            else:
                logger.warning("Settle failed after 3 attempts (non-critical, result still delivered): %s", e)

    # Best effort: mark as settled even if facilitator failed
    request.state.x402_settled = True
    request.state.x402_settled_amount = actual_microunits

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
    elif mode == "payai":
        facilitator = HTTPFacilitatorClient(
            FacilitatorConfig(
                url=PAYAI_FACILITATOR_URL,
                timeout=30.0,
                identifier="payai",
            )
        )
        logger.info("x402: using PayAI Facilitator at %s (no KYC, free)", PAYAI_FACILITATOR_URL)
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

    common_networks = list(evm_networks)

    def make_upto_option(network: str, max_price: str) -> PaymentOption:
        """Upto/dynamic pricing: client authorizes max, we settle actual usage."""
        return PaymentOption(
            scheme="upto",
            pay_to=pay_to_evm,
            price=max_price,       # max authorized amount
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
        props = _SCHEMAS.get(route_key, {})
        required = [k for k, v in props.items() if "optional" not in v]
        schema_props = {}
        for k, v in props.items():
            type_str = v.split(" ")[0] if " " in v else "string"
            schema_props[k] = {"type": type_str, "description": v.replace(" (optional)", "")}
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
            extensions={
                "bazaar": {
                    "discoverable": True,
                    "inputSchema": _bazaar_schema(route_key),
                }
            },
        )

    for route_key, (price, desc) in _EXACT_SERVICES.items():
        routes[route_key] = RouteConfig(
            accepts=[make_exact_option(net, price) for net in common_networks],
            description=desc,
            mime_type="application/json",
            extensions={
                "bazaar": {
                    "discoverable": True,
                    "inputSchema": _bazaar_schema(route_key),
                }
            },
        )

    paywall = PaywallConfig(
        app_name="AI Agent API — 16 pay-per-call services ($0.0005–$0.08 USDC)",
    )

    from app.services import credits, analytics

    x402_mw = payment_middleware(routes, server, paywall_config=paywall)

    networks_help = "Base, Arbitrum, or Optimism"
    PAYMENT_HELP = (
        "To use this API, send USDC to {pay_to} on {nets}, "
        "then retry with header payment-signature: <base64-json>. "
        "MCP: https://agent-api-ai.duckdns.org/mcp/sse "
        "Docs: https://github.com/AntoNYak0/ai-agent-api"
    ).format(pay_to=pay_to_evm, nets=networks_help)

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

    @app.middleware("http")
    async def x402_response_header_middleware(request, call_next):
        """Add PAYMENT-RESPONSE header when x402 settlement completed successfully."""
        response = await call_next(request)
        if hasattr(request.state, "x402_settled") and request.state.x402_settled:
            response.headers["PAYMENT-RESPONSE"] = "true"
            amount = getattr(request.state, "x402_settled_amount", 0)
            usd = amount / 1e6
            response.headers["X-Payment-Amount"] = f"${usd:.6f} USDC"
            logger.info("PAYMENT-RESPONSE: settled %d microunits", amount)
        return response
