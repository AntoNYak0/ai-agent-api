from fastapi import FastAPI
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

# Solana mainnet
SOLANA_NET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# AI services: upto pricing (pay per actual usage)
_UPTO_SERVICES = {
    "POST /api/audit":          ("$0.10", "Security scan with OWASP Top 10 + SWC Registry taxonomy"),
    "POST /api/refactor":       ("$0.16", "Refactor legacy code — DRY, SOLID, modern patterns"),
    "POST /api/docs":           ("$0.06", "Generate technical docs with architecture, signatures, examples"),
    "POST /api/defi-analyze":   ("$0.08", "DeFi protocol analysis: risks, tokenomics, architecture"),
    "POST /api/trading-signal": ("$0.06", "Crypto trading analytics — qualitative, NOT financial advice"),
    "POST /api/solidity-scan":  ("$0.20", "Solidity vulnerability scanner — 36 SWC checks + DeFi exploits"),
    "POST /api/nl-to-sql":      ("$0.06", "Convert natural language descriptions to SQL queries"),
    "POST /api/sql-to-nl":      ("$0.04", "Explain SQL queries in plain English"),
    "POST /api/git-summarize":  ("$0.04", "Summarize git diff into PR description"),
    "POST /api/translate-code": ("$0.10", "Translate code between languages (Python, TS, Rust, Go, Solidity)"),
}

# Micro-tasks: exact pricing (flat fee)
_EXACT_SERVICES = {
    "POST /api/validate-json":  ("$0.001", "Validate JSON/YAML structure, schema, types"),
    "POST /api/classify-text":  ("$0.002", "Classify text: sentiment, category, keywords, language"),
    "POST /api/extract-data":   ("$0.015", "Extract structured data: names, emails, phones, URLs, dates"),
    "POST /api/generate-regex": ("$0.005", "Generate regex pattern from description with test cases"),
    "POST /api/format-data":    ("$0.01",  "Convert data: CSV to JSON, JSON to YAML, etc."),
    "POST /api/summarize":      ("$0.005", "Summarize text to N words, extract key points"),
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
    pay_to_solana: str | None,
    facilitator_url: str,
    testnet: bool = True,
) -> None:
    if testnet:
        facilitator = DirectFacilitator(testnet=True, pay_to=pay_to_evm)
    else:
        facilitator = DirectFacilitator(testnet=False, pay_to=pay_to_evm)
    server = x402ResourceServer(facilitator)

    base_net = "eip155:84532" if testnet else "eip155:8453"
    polygon_net = "eip155:137"
    register_exact_evm_server(server, [base_net, polygon_net])

    # Networks: Base + Polygon for production (Solana in well-known only)
    common_networks = [base_net]
    if not testnet:
        common_networks.append(polygon_net)

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
        app_name="AI Agent API — 16 pay-per-call services ($0.001–$0.10 USDC)",
    )

    from app.services import credits

    x402_mw = payment_middleware(routes, server, paywall_config=paywall)

    PAYMENT_HELP = (
        "To use this API, send USDC to {pay_to} on Base or Polygon, "
        "then retry with header payment-signature: <base64-json>. "
        "Or get a free API key: POST /billing/create-key. "
        "Docs: https://github.com/AntoNYak0/ai-agent-api"
    ).format(pay_to=pay_to_evm)

    @app.middleware("http")
    async def x402_payment_middleware(request, call_next):
        # Human devs with API key skip x402 crypto payment
        if hasattr(request.state, "human_api_key"):
            return await call_next(request)

        from starlette.responses import Response as StarletteResponse
        import json as _json

        response = await x402_mw(request, call_next)
        if response.status_code == 402:
            try:
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                data = _json.loads(body) if body else {}
                data["message"] = PAYMENT_HELP
                new_body = _json.dumps(data).encode()
                return StarletteResponse(
                    content=new_body,
                    status_code=402,
                    headers=dict(response.headers),
                    media_type="application/json",
                )
            except Exception:
                pass
        return response
