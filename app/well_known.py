"""Serve /.well-known/x402 manifest, OpenAPI spec, agent-card, glama.json, and server-card for agent discovery."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.pricing import (
    AI_UPTO_SERVICES, EXACT_SERVICES, COMPOSITE_SKILLS,
    NETWORKS, WALLET, DOMAIN, GITHUB,
    _TOOL_NAMES, _PRICING_TO_TOOL,
)
from app.services import workflow_registry

router = APIRouter()

# ── MCP composite skill metadata (mirrors @mcp.tool decorators in mcp_server.py) ──
_COMPOSITE_MCP_TOOLS = [
    {
        "name": "defi-research",
        "description": "Full DeFi research pipeline: extract on-chain data → analyze protocol → summarize. Price: $0.08 USDC.",
        "price": "$0.08",
        "input": {"protocol": "string", "chain": "string (optional, default: ethereum)", "onchain_data": "string (optional)"},
        "output": {"result": "string"},
    },
    {
        "name": "code-health-check",
        "description": "Complete code health: security audit → refactor → generate documentation. Price: $0.10 USDC.",
        "price": "$0.10",
        "input": {"code": "string", "instructions": "string (optional)"},
        "output": {"result": "string"},
    },
    {
        "name": "smart-contract-audit",
        "description": "Solidity audit + documentation: scan vulnerabilities → generate audit report. Price: $0.10 USDC.",
        "price": "$0.10",
        "input": {"code": "string"},
        "output": {"result": "string"},
    },
    {
        "name": "data-pipeline",
        "description": "Data processing pipeline: extract entities → convert format → summarize. Price: $0.05 USDC.",
        "price": "$0.05",
        "input": {"text": "string", "target_format": "csv|json|yaml (optional, default: json)"},
        "output": {"result": "string"},
    },
    {
        "name": "run-workflow",
        "description": "Execute a user-defined composite workflow chain. Browse available workflows at /api/workflows",
        "price": "varies",
        "input": {"workflow_id": "string", "input_text": "string"},
        "output": {"result": "string"},
    },
]

# Individual MCP tool count (from _TOOL_NAMES excluding composite/None entries)
_MCP_INDIVIDUAL_COUNT = sum(1 for v in _TOOL_NAMES.values() if v is not None)
_MCP_TOTAL_COUNT = _MCP_INDIVIDUAL_COUNT + len(_COMPOSITE_MCP_TOOLS)
_REST_COUNT = len(AI_UPTO_SERVICES) + len(EXACT_SERVICES)

# Build lookup dicts for templates
_SVC = {}
for name, info in AI_UPTO_SERVICES.items():
    min_price = info['min_price_microunits'] / 1_000_000
    _SVC[info['path']] = {
        'price': f"${info['base_microunits']/1_000_000:.4f}",
        'scheme': 'upto',
        'maxPrice': info['max_price'],
        'minPriceMicrounits': info['min_price_microunits'],
        'maxPriceMicrounits': int(float(info['max_price'].replace('$', '')) * 1_000_000),
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


def _display_price(info: dict) -> str:
    """Format price for display: upto -> '$0.01–$0.05', exact -> '$0.003'."""
    if info['scheme'] == 'upto':
        lo = f"${info['minPriceMicrounits'] / 1_000_000:.3f}".rstrip('0').rstrip('.')
        return f"{lo}–{info['maxPrice']}"
    return info['price']


def _service_category(path: str) -> str:
    """Map service path to Agentic Market category."""
    cats = {
        '/api/audit': 'Infra', '/api/refactor': 'Infra', '/api/docs': 'Infra',
        '/api/solidity-scan': 'Infra', '/api/agent-audit': 'Infra',
        '/api/contract-verify': 'Infra', '/api/security-score': 'Infra',
        '/api/debug-log': 'Infra',
        '/api/defi-analyze': 'Data', '/api/trading-signal': 'Data',
        '/api/whale-tracker': 'Data', '/api/smart-money': 'Data',
        '/api/price-feed': 'Data', '/api/data-feed': 'Data',
        '/api/nl-to-sql': 'Inference', '/api/sql-to-nl': 'Inference',
        '/api/git-summarize': 'Inference', '/api/translate-code': 'Inference',
        '/api/validate-json': 'Infra', '/api/classify-text': 'Inference',
        '/api/extract-data': 'Data', '/api/generate-regex': 'Infra',
        '/api/format-data': 'Data', '/api/summarize': 'Inference',
    }
    return cats.get(path, 'Inference')


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
        if desc.startswith("["):
            type_str = "array"
        elif desc.startswith("{"):
            type_str = "object"
        elif desc == "boolean":
            type_str = "boolean"
        if desc == "integer" or desc == "0.0-1.0":
            type_str = "number"
        props[name] = {"type": type_str, "description": desc}
    return {"type": "object", "properties": props}


def _build_x_payment_info(price: str, scheme: str) -> dict:
    """Build x-payment-info per x402scan DISCOVERY.md spec (OpenAPI-first indexing)."""
    if scheme == "exact":
        return {
            "protocols": ["x402"],
            "price": {"mode": "fixed", "currency": "USD", "amount": price.replace("$", "")},
        }
    # upto: "$0.01–$0.05" → dynamic with max
    parts = price.replace("$", "").split("–")
    max_price = parts[1] if len(parts) > 1 else parts[0]
    return {
        "protocols": ["x402"],
        "price": {"mode": "dynamic", "currency": "USD", "amount": max_price},
    }


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
                "x-payment-info": _build_x_payment_info(info["price"], info["scheme"]),
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
                f"{_REST_COUNT} REST services ({len(AI_UPTO_SERVICES)} upto + {len(EXACT_SERVICES)} exact) — "
                f"pay-per-call AI services via x402 micropayments. "
                f"Also {_MCP_TOTAL_COUNT} MCP tools at /mcp/sse. "
                "All responses are machine-readable JSON. "
                "Pay with USDC on Base, Arbitrum, Optimism, BNB Chain or USDT on Tron."
            ),
            "contact": {
                "url": GITHUB,
                "email": "admin@agent-api-ai.duckdns.org",
            },
            "x-x402-payment": {
                "networks": NETWORKS,
                "wallet": WALLET,
            },
            "license": {"name": "MIT"},
        },
        "servers": [{"url": DOMAIN, "description": "Production"}],
        "x-discovery": {
            "ownershipProofs": [
                {"type": "github", "url": GITHUB},
                {"type": "dns", "domain": DOMAIN.replace("https://", "")},
            ],
        },
        "security": [{"x402": []}],
        "components": {
            "securitySchemes": {
                "x402": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "x402 micropayments in USDC. Send PAYMENT header with signed transaction.",
                }
            }
        },
        "paths": paths,
    }


# ── Well-known endpoints ────────────────────────────────────────

@router.get("/.well-known/x402")
async def x402_manifest():
    endpoints = {}
    for path, info in _SVC.items():
        endpoints[path] = {
            "method": "POST",
            "scheme": info["scheme"],
            "price": _display_price(info),
            "description": info["summary"],
        }

    # Actual MCP tools — all 30 (25 individual + 5 composite/workflow)
    available_tools = (
        [mcp_name for mcp_name, pk in sorted(_TOOL_NAMES.items()) if pk is not None]
        + [ct["name"] for ct in _COMPOSITE_MCP_TOOLS]
    )

    # Build resource URLs for x402scan compatibility
    resources = [f"{DOMAIN}{path}" for path in sorted(_SVC.keys())]

    return JSONResponse({
        "x402_version": 2,
        "name": f"AI Agent API — {_REST_COUNT} REST + {_MCP_TOTAL_COUNT} MCP tools for agent pipelines",
        "resources": resources,
        "description": (
            f"AI services on DeepSeek V4 Pro (1M token context). "
            f"Payments via x402 in USDC (Base, Arbitrum, Optimism, BNB Chain) or USDT (Tron). "
            f"{_REST_COUNT} REST services + {_MCP_TOTAL_COUNT} MCP tools: "
            f"code audit, refactoring, DeFi analysis, "
            f"Solidity scanner, AMM security, SQL/NL tools, data feeds, security tools, micro-tasks, "
            f"composite workflows. "
            f"Prices: $0.001–$1.00 USDC per call. "
            f"All responses are machine-readable JSON."
        ),
        "version": "2.0.0",
        "contact": {
            "github": GITHUB,
            "email": "admin@agent-api-ai.duckdns.org",
        },
        "payment": {
            "scheme": "x402",
            "networks": [
                {"caip2": n["caip2"], "name": n["name"], "asset": n["asset"]}
                for n in NETWORKS
            ],
        },
        "endpoints": endpoints,
        "mcp": {
            "endpoint": "/mcp/sse",
            "transport": "sse",
            "available_tools": available_tools,
            "total_tools": len(available_tools),
        },
    })


@router.get("/.well-known/agentic-market-services.json")
async def agentic_market_services():
    """Agentic Market service listing — https://api.agentic.market/v1/services/ compatible schema."""
    networks_short = ["base", "arbitrum", "optimism", "bnb", "tron"]

    services = []
    for path, info in sorted(_SVC.items()):
        name = path.replace("/api/", "").replace("-", " ")
        tool_id = f"agent-api-{path.replace('/api/', '').replace('-', '_')}"

        # Determine amount: max price for upto, exact price for exact
        if info['scheme'] == 'upto':
            amount = info['maxPrice'].replace('$', '')
        else:
            amount = info['price'].replace('$', '')

        services.append({
            "id": tool_id,
            "name": name.title(),
            "description": info['summary'],
            "domain": "agent-api-ai.duckdns.org",
            "category": _service_category(path),
            "networks": networks_short,
            "integrationType": "1P",
            "isNew": False,
            "endpoints": [
                {
                    "url": f"{DOMAIN}{path}",
                    "description": info['summary'],
                    "method": "POST",
                    "pricing": {
                        "amount": amount,
                        "currency": "USDC",
                        "network": "base",
                    },
                }
            ],
        })

    # Registered composite workflows
    workflows_list = []
    for wf in workflow_registry.list_workflows():
        workflows_list.append({
            "id": wf["id"],
            "name": wf["name"],
            "description": wf["description"],
            "chain": wf["chain"],
            "price_cents": wf["price_cents"],
            "platform_percent": wf.get("platform_percent", 15),
            "author_share_cents": wf["price_cents"] * (100 - wf.get("platform_percent", 15)) // 100,
            "enabled": wf.get("enabled", True),
            "total_executions": wf.get("total_executions", 0),
        })

    return JSONResponse({"services": services, "workflows": workflows_list})


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

    # Add composite MCP tools
    for ct in _COMPOSITE_MCP_TOOLS:
        tools.append({
            "name": ct["name"],
            "description": ct["description"],
            "method": "POST",
            "path": "/mcp/sse",
            "payment": {
                "scheme": "exact",
                "price": ct["price"],
                "currency": "USDC",
            },
            "input": ct["input"],
            "output": ct["output"],
        })

    return JSONResponse({
        "schema_version": "1.0",
        "agent_type": "api",
        "name": "AI Agent API",
        "description": f"{_REST_COUNT} REST + {_MCP_TOTAL_COUNT} MCP pay-per-call AI services powered by DeepSeek V4 Pro. Payments via x402 protocol.",
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
            "total_tools": _MCP_TOTAL_COUNT,
        },
        "tools": tools,
    })


@router.get("/.well-known/mcp/server-card.json")
async def mcp_server_card():
    """Smithery.ai server card — Smithery expects serverInfo + authentication + tools.
    https://smithery.ai/docs/build/publish
    """
    tools = []
    # Individual MCP tools — use actual MCP names from _TOOL_NAMES (NOT derived from REST paths)
    for mcp_name, pricing_key in sorted(_TOOL_NAMES.items()):
        if pricing_key is None:
            continue  # Composite skills handled separately
        svc = AI_UPTO_SERVICES.get(pricing_key) or EXACT_SERVICES.get(pricing_key)
        if not svc:
            continue
        props = {}
        required = []
        for k, v in svc.get("input", {}).items():
            is_optional = "(optional)" in v.lower()
            props[k] = {"type": "string", "description": v.replace(" (optional)", "").replace(" (optional,", " (")}
            if not is_optional:
                required.append(k)
        tools.append({
            "name": mcp_name,
            "description": svc["description"],
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": required if required else [],
            },
        })

    # Composite skills + workflow dispatcher
    for ct in _COMPOSITE_MCP_TOOLS:
        props = {}
        required = []
        for k, v in ct["input"].items():
            is_optional = "(optional)" in v.lower()
            clean_desc = v.replace(" (optional)", "").replace(" (optional,", " (")
            props[k] = {"type": "string", "description": clean_desc}
            if not is_optional:
                required.append(k)
        tools.append({
            "name": ct["name"],
            "description": ct["description"],
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": required if required else [],
            },
        })

    return JSONResponse({
        "serverInfo": {
            "name": "ai-agent-api",
            "version": "2.0.0",
            "description": (
                f"{_MCP_TOTAL_COUNT} MCP tools ({_MCP_INDIVIDUAL_COUNT} individual + {len(_COMPOSITE_MCP_TOOLS)} composite) "
                f"via x402 USDC — code audit, refactoring, DeFi analysis, Solidity scanner, "
                f"SQL/NL tools, micro-tasks, security, data feeds, composite workflows. "
                f"Powered by DeepSeek V4 Pro."
            ),
        },
        "authentication": {
            "required": False,
            "schemes": ["x402", "api_key"],
            "description": "x402 USDC payments (AI agents) or API key credits (human developers). Base, Arbitrum, Optimism, BNB Chain, Tron.",
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
    tools_list = []
    # Individual MCP tools
    for mcp_name, pricing_key in sorted(_TOOL_NAMES.items()):
        if pricing_key is None:
            continue
        svc = AI_UPTO_SERVICES.get(pricing_key) or EXACT_SERVICES.get(pricing_key)
        if svc:
            tools_list.append({
                "name": mcp_name,
                "description": svc["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": {k: {"type": "string", "description": v.replace(" (optional)", "")} for k, v in svc.get("input", {}).items()},
                },
            })
    # Composite skills
    for ct in _COMPOSITE_MCP_TOOLS:
        tools_list.append({
            "name": ct["name"],
            "description": ct["description"],
            "inputSchema": {
                "type": "object",
                "properties": {k: {"type": "string", "description": v.replace(" (optional)", "")} for k, v in ct["input"].items()},
            },
        })

    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "name": "AI Agent API",
        "description": (
            f"{_MCP_TOTAL_COUNT} MCP tools: code audit, refactoring, DeFi analysis, "
            f"Solidity scanner, SQL/NL tools, micro-tasks, security, data feeds, "
            f"composite workflows. Powered by DeepSeek V4 Pro. Payment via x402 USDC or API key credits."
        ),
        "type": "sse",
        "url": f"{DOMAIN}/mcp/sse",
        "auth": {
            "type": "x402",
            "description": "Pay per call in USDC via x402 protocol on Base, Arbitrum, Optimism, BNB Chain, Tron. API key credits also supported.",
        },
        "tools": tools_list,
        "maintainers": [{"email": "admin@agent-api-ai.duckdns.org"}],
        "homepage": DOMAIN,
        "repository": GITHUB,
        "license": "MIT",
    })

@router.get("/.well-known/agent.json")
async def agent_json():
    """AP2 (Agent Payments Protocol) discovery — A2A Agent Card with payments block.
    https://agentpaymentsprotocol.info/specification/discovery/
    """
    skills = []
    for path, info in _SVC.items():
        name = path.replace("/api/", "").replace("-", "_")
        skills.append({
            "id": name,
            "name": name.replace("_", " ").title(),
            "description": info["summary"],
            "tags": [name, info["scheme"]],
            "input": info["body"],
            "output": info["response"],
        })

    # Add MCP composite skills
    for ct in _COMPOSITE_MCP_TOOLS:
        skills.append({
            "id": ct["name"],
            "name": ct["name"].replace("-", " ").title(),
            "description": ct["description"],
            "tags": [ct["name"], "composite"],
            "input": ct["input"],
            "output": ct["output"],
        })

    # Build tasks list from service catalog
    tasks = []
    for path, info in _SVC.items():
        max_price = info.get("maxPrice", info.get("price", "$0.01"))
        tasks.append({
            "id": path.replace("/api/", "").replace("-", "_"),
            "name": path.replace("/api/", "").replace("-", " ").title(),
            "description": info["summary"],
            "category": _service_category(path),
            "pricing": {
                "model": info["scheme"],
                "currency": "USDC",
                "max": max_price,
            },
            "estimatedDuration": "PT10S",
        })

    return JSONResponse({
        "name": "AI Agent API",
        "url": DOMAIN,
        "version": "2.0.0",
        "did": f"did:web:{DOMAIN.replace('https://', '')}",
        "description": (
            f"{_REST_COUNT} REST + {_MCP_TOTAL_COUNT} MCP pay-per-call AI services via x402 USDC micropayments. "
            "Code audit, refactoring, DeFi analysis, Solidity scanner, "
            "AMM security, SQL/NL tools, micro-tasks, composite workflows. "
            "Powered by DeepSeek V4 Pro (1M context)."
        ),
        "capabilities": {
            "streaming": True,
            "mcp": True,
            "pushNotifications": False,
            "extensions": ["x402", "mcp", "a2a"],
            "tasks": tasks,
        },
        "payments": {
            "version": "2025.0",
            "rails": [
                {
                    "id": "x402",
                    "currencies": ["USDC", "USDT"],
                    "captureTypes": ["immediate_capture", "usage_metered"],
                    "jurisdictions": ["WW"],
                    "policy": f"{DOMAIN}/.well-known/x402",
                    "fees": {
                        "processing": "0%",
                        "refund": "0 USD",
                    },
                }
            ],
            "pricing": {
                "model": "catalog",
                "catalogUrl": f"{DOMAIN}/.well-known/x402",
            },
            "contact": {
                "operations": "admin@agent-api-ai.duckdns.org",
                "disputes": "admin@agent-api-ai.duckdns.org",
            },
        },
        "mcp": {
            "endpoint": "/mcp/sse",
            "transport": "sse",
            "total_tools": _MCP_TOTAL_COUNT,
        },
        "authentication": {
            "required": True,
            "schemes": ["x402", "api_key"],
        },
        "skills": skills,
        "contact": {
            "email": "admin@agent-api-ai.duckdns.org",
            "github": GITHUB,
        },
        "repository": GITHUB,
        "license": "MIT",
    })
