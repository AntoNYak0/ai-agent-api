"""Serve /.well-known/x402 manifest, OpenAPI spec, agent-card, glama.json, and server-card for agent discovery."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.pricing import (
    AI_UPTO_SERVICES, EXACT_SERVICES, COMPOSITE_SKILLS,
    NETWORKS, WALLET, DOMAIN, GITHUB,
)

router = APIRouter()

# Build lookup dicts for templates
_SVC = {}
for name, info in AI_UPTO_SERVICES.items():
    _SVC[info['path']] = {
        'price': f"${info['base_microunits']/1_000_000:.4f}",
        'scheme': 'upto',
        'maxPrice': info['max_price'],
        'summary': info['description'],
        'body': info['input'],
        'response': info['output'],
    }
for name, info in EXACT_SERVICES.items():
    _SVC[info['path']] = {
        'price': info['price'],
        'scheme': 'exact',
        'summary': info['description'],
        'body': info['input'],
        'response': info['output'],
    }


def _build_402_response(price: str, scheme: str) -> dict:
    return {
        "description": f"Payment required — {price} USDC",
        "headers": {
            "PAYMENT-REQUIRED": {
                "schema": {"type": "string"},
                "description": "Base64-encoded JSON with x402 payment details",
            }
        },
    }


def _build_response_schema(info: dict) -> dict:
    """Build JSON Schema from endpoint response description."""
    props = {}
    for name, desc in info.get("response", {}).items():
        type_str = "string"
        if desc.startswith("[") or desc.startswith("{") or desc == "boolean":
            pass
        if desc == "integer" or desc == "0.0-1.0":
            type_str = "number"
        props[name] = {"type": type_str, "description": desc}
    return {"type": "object", "properties": props}


def _build_openapi_spec() -> dict:
    paths = {}
    for path, info in _SVC.items():
        paths[path] = {
            "post": {
                "summary": info["summary"],
                "operationId": path.replace("/api/", "").replace("-", "_"),
                "x-x402-price": info["price"],
                "x-x402-scheme": info["scheme"],
                "x-x402-networks": [n["caip2"] for n in NETWORKS],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {k: {"type": "string"} for k in info["body"]},
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Successful response (JSON)",
                        "content": {
                            "application/json": {
                                "schema": _build_response_schema(info),
                            }
                        },
                        "headers": {
                            "Cache-Control": {
                                "schema": {"type": "string"},
                                "description": "no-store",
                            },
                            "PAYMENT-RESPONSE": {
                                "schema": {"type": "string"},
                                "description": "true when x402 settlement completed",
                            },
                        },
                    },
                    "402": _build_402_response(info["price"], info["scheme"]),
                },
            }
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "AI Agent API",
            "version": "2.0.0",
            "description": (
                "16 pay-per-call AI services via x402 micropayments. "
                "6 complex (audit, refactor, docs, defi, trading, solidity-scan) + "
                "4 SQL/dev tools (nl-to-sql, sql-to-nl, git-summarize, translate-code) + "
                "6 micro-tasks (validate, classify, extract, regex, format, summarize). "
                "All responses are machine-readable JSON. "
                "No API keys — pay with USDC on Base/Arbitrum/Optimism or USDT on Tron."
            ),
            "contact": {
                "url": GITHUB,
                "email": "admin@agent-api-ai.duckdns.org",
            },
            "x-x402-payment": {
                "networks": NETWORKS,
                "wallet": WALLET,
            },
        },
        "servers": [{"url": DOMAIN, "description": "Production"}],
        "paths": paths,
    }


# ── Well-known endpoints ────────────────────────────────────────

@router.get("/.well-known/x402")
async def x402_manifest():
    return JSONResponse({
        "x402_version": 2,
        "name": "AI Agent API — 16 pay-per-call services for agent pipelines",
        "description": (
            "AI services on DeepSeek V4 Pro (1M token context). "
            "Payments via x402 in USDC (Base, Arbitrum, Optimism) and USDT (Tron). "
            "6 complex services (audit, refactor, docs, defi, trading, solidity-scan) + "
            "4 SQL/dev tools (nl-to-sql, sql-to-nl, git-summarize, translate-code) + "
            "6 high-frequency micro-tasks (validate, classify, extract, regex, format, summarize). "
            "Prices: $0.0005–$0.08 USDC per call. "
            "All responses are machine-readable JSON."
        ),
        "version": "2.0.0",
        "contact": {
            "github": GITHUB,
            "email": "admin@agent-api-ai.duckdns.org",
        },
        "payment": {
            "scheme": "mixed",
            "networks": [
                {"id": "eip155:8453", "name": "Base", "asset": "USDC"},
                {"id": "eip155:42161", "name": "Arbitrum", "asset": "USDC"},
                {"id": "eip155:10", "name": "Optimism", "asset": "USDC"},
                {"id": "tron:0x2b6653dc", "name": "Tron", "asset": "USDT"},
            ],
        },
        "endpoints": {
            "/api/audit": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.01–$0.05",
                "description": "Security scan with OWASP Top 10 + SWC Registry taxonomy"
            },
            "/api/refactor": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.01–$0.05",
                "description": "Refactor legacy code — DRY, SOLID, modern patterns"
            },
            "/api/docs": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.005–$0.03",
                "description": "Generate technical docs with architecture, signatures, examples"
            },
            "/api/defi-analyze": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.01–$0.04",
                "description": "DeFi protocol analysis — risks, tokenomics, architecture"
            },
            "/api/trading-signal": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.005–$0.03",
                "description": "Crypto trading analytics — qualitative, training data only"
            },
            "/api/solidity-scan": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.02–$0.08",
                "description": "Solidity vulnerability scanner — 36 SWC checks + DeFi exploit patterns"
            },
            "/api/nl-to-sql": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.005–$0.03",
                "description": "Convert natural language descriptions to SQL queries"
            },
            "/api/sql-to-nl": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.005–$0.02",
                "description": "Explain SQL queries in plain English"
            },
            "/api/git-summarize": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.005–$0.02",
                "description": "Summarize git diff into PR description with breaking change detection"
            },
            "/api/translate-code": {
                "method": "POST",
                "scheme": "upto",
                "price": "$0.01–$0.05",
                "description": "Translate code between languages (Python, TS, Rust, Go, Solidity)"
            },
            "/api/validate-json": {
                "method": "POST",
                "scheme": "exact",
                "price": "$0.0005",
                "description": "Validate JSON/YAML structure, schema, types"
            },
            "/api/classify-text": {
                "method": "POST",
                "scheme": "exact",
                "price": "$0.001",
                "description": "Classify text — sentiment, category, keywords, language"
            },
            "/api/extract-data": {
                "method": "POST",
                "scheme": "exact",
                "price": "$0.005",
                "description": "Extract structured data — names, emails, phones, URLs, dates, amounts"
            },
            "/api/generate-regex": {
                "method": "POST",
                "scheme": "exact",
                "price": "$0.002",
                "description": "Generate regex pattern from description with test cases"
            },
            "/api/format-data": {
                "method": "POST",
                "scheme": "exact",
                "price": "$0.003",
                "description": "Convert data between CSV, JSON, YAML formats"
            },
            "/api/summarize": {
                "method": "POST",
                "scheme": "exact",
                "price": "$0.002",
                "description": "Summarize text to N words, extract key points"
            },
        },
        "mcp": {
            "endpoint": "/mcp/sse",
            "transport": "sse",
            "available_tools": [
                "audit", "refactor", "docs", "defi", "trading", "solidity-scan",
                "nl-to-sql", "sql-to-nl", "git-summarize",
                "validate-json", "classify-text", "extract-data",
                "translate-code", "generate-regex", "format-data", "summarize",
            ],
        },
    })


@router.get("/.well-known/openapi.json")
async def openapi_spec():
    return JSONResponse(_build_openapi_spec())


@router.get("/.well-known/agent-card.json")
async def agent_card():
    """A2A (Agent-to-Agent) discovery card — standard format for agent registries."""
    tools = []
    for path, info in _SVC.items():
        name = path.replace("/api/", "")
        tools.append({
            "name": name,
            "description": info["summary"],
            "method": "POST",
            "path": path,
            "payment": {
                "scheme": info["scheme"],
                "price": info["price"],
                "currency": "USDC",
            },
            "input": info["body"],
            "output": info["response"],
        })

    return JSONResponse({
        "schema_version": "1.0",
        "agent_type": "api",
        "name": "AI Agent API",
        "description": "16 pay-per-call AI services powered by DeepSeek V4 Pro. Payments via x402 protocol.",
        "version": "2.0.0",
        "base_url": DOMAIN,
        "contact": {
            "github": GITHUB,
            "email": "admin@agent-api-ai.duckdns.org",
        },
        "payment": {
            "protocol": "x402",
            "version": 2,
            "wallet": WALLET,
            "networks": NETWORKS,
        },
        "mcp": {
            "endpoint": "/mcp/sse",
            "transport": "sse",
        },
        "tools": tools,
    })


@router.get("/.well-known/mcp/server-card.json")
async def mcp_server_card():
    """Smithery.ai server card — Smithery expects serverInfo + authentication + tools.
    https://smithery.ai/docs/build/publish
    """
    tools = []
    for path, info in _SVC.items():
        name = path.replace("/api/", "").replace("-", "_")
        props = {}
        required = []
        for k, v in info["body"].items():
            is_optional = "(optional)" in v
            props[k] = {"type": "string", "description": v.replace(" (optional)", "")}
            if not is_optional:
                required.append(k)
        tools.append({
            "name": name,
            "description": info["summary"],
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        })

    return JSONResponse({
        "serverInfo": {
            "name": "ai-agent-api",
            "version": "2.0.0",
            "description": "16 pay-per-call AI services via x402 USDC — code audit, refactoring, DeFi analysis, Solidity scanner, SQL/NL tools, micro-tasks. Powered by DeepSeek V4 Pro.",
        },
        "authentication": {
            "required": False,
            "schemes": ["x402"],
            "description": "No API key. Pay per call in USDC via x402 on Base/Arbitrum/Optimism.",
        },
        "transport": "sse",
        "url": f"{DOMAIN}/mcp/sse",
        "tools": tools,
        "resources": [],
        "prompts": [],
        "contact": {
            "github": GITHUB,
            "email": "admin@agent-api-ai.duckdns.org",
        },
    })


@router.get("/.well-known/glama.json")
async def glama_json():
    """Glama.ai auto-discovery file. Glama scans this to list the server."""
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "name": "AI Agent API",
        "description": "16 pay-per-call AI services: code audit, refactoring, DeFi analysis, Solidity scanner, SQL/NL tools, and micro-tasks. Powered by DeepSeek V4 Pro. Payment via x402 USDC.",
        "type": "sse",
        "url": f"{DOMAIN}/mcp/sse",
        "auth": {
            "type": "x402",
            "description": "Pay per call in USDC via x402 protocol on Base, Arbitrum, Optimism",
        },
        "maintainers": [{"email": "admin@agent-api-ai.duckdns.org"}],
        "homepage": DOMAIN,
        "repository": GITHUB,
        "license": "MIT",
    })
