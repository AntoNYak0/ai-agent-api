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

logger = logging.getLogger("x402")

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
}


def configure_x402(
    app: FastAPI,
    pay_to_evm: str,
    pay_to_tron: str | None,
    facilitator_url: str,
    pay_to_solana: str | None = None,
    testnet: bool = True,
) -> None:
    if testnet:
        facilitator = DirectFacilitator(testnet=True, pay_to=pay_to_evm)
        logger.info("x402: using DirectFacilitator (testnet mode)")
    else:
        facilitator = DirectFacilitator(testnet=False, pay_to=pay_to_evm)
        logger.info("x402: using DirectFacilitator (mainnet — onchain RPC verification)")
    server = x402ResourceServer(facilitator)

    base_net = "eip155:84532" if testnet else "eip155:8453"
    # Only register networks that the facilitator (Dexter) supports for exact EVM scheme
    evm_networks = [base_net]
    register_exact_evm_server(server, evm_networks)

    # REST x402 middleware only advertises Base (what Dexter verifies)
    # Arbitrum/Optimism/Tron are listed in well-known manifest + handled via MCP
    common_networks = list(evm_networks)

    def make_option(network: str, price: str) -> PaymentOption:
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

    for route_key, (price, desc) in {**_UPTO_SERVICES, **_EXACT_SERVICES}.items():
        routes[route_key] = RouteConfig(
            accepts=[make_option(net, price) for net in common_networks],
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

    PAYMENT_HELP = (
        "To use this API, send USDC to {pay_to} on Base, "
        "then retry with header payment-signature: <base64-json>. "
        "MCP: http://agent-api-ai.duckdns.org:8000/mcp/sse "
        "Docs: https://github.com/AntoNYak0/ai-agent-api"
    ).format(pay_to=pay_to_evm)

    @app.middleware("http")
    async def x402_payment_middleware(request, call_next):
        # Human devs with API key skip x402 crypto payment
        if hasattr(request.state, "human_api_key"):
            return await call_next(request)

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
