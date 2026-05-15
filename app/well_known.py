"""Serve /.well-known/x402 manifest and OpenAPI spec for agent discovery."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# ── Shared schemas ──────────────────────────────────────────────

_AI_ENDPOINTS = {
    "/api/audit": {
        "price": "$0.01", "scheme": "upto", "maxPrice": "$0.05",
        "summary": "Security scan with OWASP Top 10 + SWC Registry taxonomy",
        "body": {"code": "string", "context": "string (optional)"},
        "response": {"findings": "[{severity,category,line,description,fix,code_fix}]", "risk_score": "0-100", "summary": "string"},
    },
    "/api/refactor": {
        "price": "$0.01", "scheme": "upto", "maxPrice": "$0.05",
        "summary": "Refactor legacy code — DRY, SOLID, modern patterns",
        "body": {"code": "string", "instructions": "string (optional)", "context": "string (optional)"},
        "response": {"issues_found": "[...]", "refactored_code": "string", "changes": "[{what,why,before,after}]", "complexity_reduction_percent": "number"},
    },
    "/api/docs": {
        "price": "$0.005", "scheme": "upto", "maxPrice": "$0.03",
        "summary": "Generate technical docs with architecture, signatures, examples",
        "body": {"code": "string", "context": "string (optional)"},
        "response": {"overview": "string", "architecture": "string", "functions": "[{signature,params,returns,example}]", "dependencies": "[string]", "integration_examples": "[string]"},
    },
    "/api/defi-analyze": {
        "price": "$0.01", "scheme": "upto", "maxPrice": "$0.04",
        "summary": "DeFi protocol analysis — risks, tokenomics, architecture (training data only)",
        "body": {"protocol": "string", "chain": "string (optional)", "details": "string (optional)", "onchain_data": "string (optional)"},
        "response": {"overview": "string", "architecture": "{...}", "tokenomics": "{...}", "risks": "[{category,severity,description}]", "data_freshness": "training_data_only"},
    },
    "/api/trading-signal": {
        "price": "$0.005", "scheme": "upto", "maxPrice": "$0.03",
        "summary": "Crypto trading analytics — qualitative, training data only, NOT financial advice",
        "body": {"asset": "string", "timeframe": "string (optional)", "additional_info": "string (optional)"},
        "response": {"overview": "string", "technical_analysis": "{trend,support_zones,resistance_zones}", "sentiment": "{...}", "disclaimer": "string"},
    },
    "/api/solidity-scan": {
        "price": "$0.02", "scheme": "upto", "maxPrice": "$0.08",
        "summary": "Solidity vulnerability scanner — 36 SWC checks + DeFi exploit patterns",
        "body": {"code": "string", "context": "string (optional)"},
        "response": {"vulnerabilities": "[{swc_id,severity,title,description,line,fix,code_example}]", "security_score": "0-100", "gas_optimizations": "[...]", "recommendations": "[string]"},
    },
    "/api/nl-to-sql": {
        "price": "$0.005", "scheme": "upto", "maxPrice": "$0.03",
        "summary": "Convert natural language to SQL query",
        "body": {"query": "string"},
        "response": {"sql": "string", "explanation": "string", "dialect": "string", "assumed_schema": "string"},
    },
    "/api/sql-to-nl": {
        "price": "$0.005", "scheme": "upto", "maxPrice": "$0.02",
        "summary": "Explain SQL query in plain English",
        "body": {"sql": "string"},
        "response": {"explanation": "string", "tables_used": "[string]", "operations": "[string]", "complexity": "simple|moderate|complex"},
    },
    "/api/git-summarize": {
        "price": "$0.005", "scheme": "upto", "maxPrice": "$0.02",
        "summary": "Summarize git diff into PR description",
        "body": {"diff": "string"},
        "response": {"title": "string", "description": "string", "breaking_changes": "[string]", "files_summary": "[{file,what_changed,risk}]"},
    },
    "/api/translate-code": {
        "price": "$0.01", "scheme": "upto", "maxPrice": "$0.05",
        "summary": "Translate code between languages (Python, TS, Rust, Go, Solidity)",
        "body": {"code": "string", "source_lang": "string", "target_lang": "string"},
        "response": {"translated_code": "string", "notes": "[string]"},
    },
}

_MICRO_ENDPOINTS = {
    "/api/validate-json": {
        "price": "$0.0005", "scheme": "exact",
        "summary": "Validate JSON/YAML structure, schema, types",
        "body": {"data": "string", "schema": "string (optional)"},
        "response": {"valid": "boolean", "errors": "[{line,message,fix}]", "warnings": "[{line,message}]"},
    },
    "/api/classify-text": {
        "price": "$0.001", "scheme": "exact",
        "summary": "Classify text — sentiment, category, keywords, language",
        "body": {"text": "string", "categories": "string (optional)"},
        "response": {"sentiment": "positive|negative|neutral", "category": "string", "confidence": "0.0-1.0", "keywords": "[string]", "language": "string"},
    },
    "/api/extract-data": {
        "price": "$0.005", "scheme": "exact",
        "summary": "Extract structured data — names, emails, phones, URLs, dates, amounts",
        "body": {"text": "string"},
        "response": {"entities": "[{type,value,confidence}]"},
    },
    "/api/generate-regex": {
        "price": "$0.002", "scheme": "exact",
        "summary": "Generate regex pattern from description with test cases",
        "body": {"description": "string"},
        "response": {"pattern": "string", "flags": "string", "test_cases": "[{input,matches,captured}]", "explanation": "string"},
    },
    "/api/format-data": {
        "price": "$0.003", "scheme": "exact",
        "summary": "Convert data between CSV, JSON, YAML formats",
        "body": {"data": "string", "source_format": "csv|json|yaml", "target_format": "csv|json|yaml"},
        "response": {"converted": "string", "format": "string", "warnings": "[string]"},
    },
    "/api/summarize": {
        "price": "$0.002", "scheme": "exact",
        "summary": "Summarize text to N words, extract key points",
        "body": {"text": "string", "max_length": "integer (optional)"},
        "response": {"summary": "string", "word_count": "integer", "key_points": "[string]"},
    },
}

NETWORKS = [
    {"caip2": "eip155:8453", "name": "Base", "asset": "USDC", "contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
    {"caip2": "eip155:42161", "name": "Arbitrum", "asset": "USDC", "contract": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"},
    {"caip2": "eip155:10", "name": "Optimism", "asset": "USDC", "contract": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"},
    {"caip2": "tron:0x2b6653dc", "name": "Tron", "asset": "USDT", "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"},
]


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


def _build_openapi_spec() -> dict:
    paths = {}

    for path, info in {**_AI_ENDPOINTS, **_MICRO_ENDPOINTS}.items():
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
                        "headers": {
                            "Cache-Control": {
                                "schema": {"type": "string"},
                                "description": "no-store",
                            }
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
            "contact": {"url": "https://github.com/AntoNYak0/ai-agent-api"},
            "x-x402-payment": {
                "networks": NETWORKS,
                "wallet": "0xdE7eb04faE758055642f67f30D246CcB7136C95E",
            },
        },
        "servers": [{"url": "http://agent-api-ai.duckdns.org:8000", "description": "Production"}],
        "paths": paths,
    }


@router.get("/.well-known/x402")
async def x402_manifest():
    return JSONResponse({
        "x402_version": 2,
        "name": "AI Agent API — 16 pay-per-call services for agent pipelines",
        "description": (
            "AI services on DeepSeek V4 Pro (1M token context). "
            "Payments via x402 in USDC (Base, Polygon). "
            "6 complex services (audit, refactor, docs, defi, trading, solidity-scan) + "
            "4 SQL/dev tools (nl-to-sql, sql-to-nl, git-summarize, translate-code) + "
            "6 high-frequency micro-tasks (validate, classify, extract, regex, format, summarize). "
            "Prices: $0.001–$0.10 USDC per call. "
            "All responses are machine-readable JSON."
        ),
        "version": "2.0.0",
        "contact": {
            "github": "https://github.com/AntoNYak0/ai-agent-api",
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
