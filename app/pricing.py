"""Single source of truth for all service pricing, schemas, and metadata.

Import from here in routes, x402_setup, mcp_server, and well_known.
No more duplicated price lists.
"""

# Token rate: $0.003 per 1K tokens (DeepSeek cost ~$0.0014/1K, ~2x margin)
PER_1K_TOKENS_MICROUNITS = 3000
CREDIT_MULTIPLIER = 1.5  # API keys pay 1.5x vs x402 crypto


def round_up_cents(value: float) -> int:
    """Round to nearest cent, always rounding .5 up. Avoids Python banker's rounding."""
    import math
    return max(1, math.floor(value + 0.5))

# Network constants
EVM_NETWORKS = [
    "eip155:8453",    # Base
    "eip155:42161",   # Arbitrum
    "eip155:10",      # Optimism
]
TRON_NETWORK = "tron:0x2b6653dc"

NETWORKS = [
    {"caip2": "eip155:8453", "name": "Base", "asset": "USDC",
     "contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
    {"caip2": "eip155:42161", "name": "Arbitrum", "asset": "USDC",
     "contract": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"},
    {"caip2": "eip155:10", "name": "Optimism", "asset": "USDC",
     "contract": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"},
    {"caip2": "tron:0x2b6653dc", "name": "Tron", "asset": "USDT",
     "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"},
]

WALLET = "0xdE7eb04faE758055642f67f30D246CcB7136C95E"
WALLET_TRON = "TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw"
DOMAIN = "https://agent-api-ai.duckdns.org"
GITHUB = "https://github.com/AntoNYak0/ai-agent-api"

# ── Service definitions ──────────────────────────────────────────

# Each service: name, path, description, scheme, max_price, base_microunits, min_price_microunits
# base_microunits: minimum microunits before adding per-token cost
# min_price_microunits: for validate_min_price() — reject if client authorized less

AI_UPTO_SERVICES = {
    "audit": {
        "path": "/api/audit",
        "description": "Security scan with OWASP Top 10 + SWC Registry taxonomy",
        "max_price": "$0.05",
        "base_microunits": 20_000,
        "min_price_microunits": 10_000,
        "input": {"code": "string", "context": "string (optional)"},
        "output": {"findings": "[{severity,category,line,description,fix,code_fix}]",
                   "risk_score": "0-100", "summary": "string"},
    },
    "refactor": {
        "path": "/api/refactor",
        "description": "Refactor legacy code — DRY, SOLID, modern patterns",
        "max_price": "$0.05",
        "base_microunits": 30_000,
        "min_price_microunits": 10_000,
        "input": {"code": "string", "instructions": "string (optional)", "context": "string (optional)"},
        "output": {"issues_found": "[...]", "refactored_code": "string",
                   "changes": "[{what,why,before,after}]", "complexity_reduction_percent": "number"},
    },
    "docs": {
        "path": "/api/docs",
        "description": "Generate technical docs with architecture, signatures, examples",
        "max_price": "$0.03",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"code": "string", "context": "string (optional)"},
        "output": {"overview": "string", "architecture": "string",
                   "functions": "[{signature,params,returns,example}]",
                   "dependencies": "[string]", "integration_examples": "[string]"},
    },
    "defi_analyze": {
        "path": "/api/defi-analyze",
        "description": "DeFi protocol analysis — risks, tokenomics, architecture",
        "max_price": "$0.04",
        "base_microunits": 20_000,
        "min_price_microunits": 10_000,
        "input": {"protocol": "string", "chain": "string (optional)",
                  "details": "string (optional)", "onchain_data": "string (optional)"},
        "output": {"overview": "string", "architecture": "{...}", "tokenomics": "{...}",
                   "risks": "[{category,severity,description}]", "data_freshness": "training_data_only"},
    },
    "trading_signal": {
        "path": "/api/trading-signal",
        "description": "Crypto trading analytics — qualitative, NOT financial advice",
        "max_price": "$0.03",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"asset": "string", "timeframe": "string (optional)", "additional_info": "string (optional)"},
        "output": {"overview": "string",
                   "technical_analysis": "{trend,support_zones,resistance_zones}",
                   "sentiment": "{...}", "disclaimer": "string"},
    },
    "solidity_scan": {
        "path": "/api/solidity-scan",
        "description": "Solidity vulnerability scanner — 36 SWC checks + DeFi exploits",
        "max_price": "$0.08",
        "base_microunits": 40_000,
        "min_price_microunits": 20_000,
        "input": {"code": "string", "context": "string (optional)"},
        "output": {"vulnerabilities": "[{swc_id,severity,title,description,line,fix,code_example}]",
                   "security_score": "0-100", "gas_optimizations": "[...]", "recommendations": "[string]"},
    },
    "nl_to_sql": {
        "path": "/api/nl-to-sql",
        "description": "Convert natural language to SQL query",
        "max_price": "$0.03",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"query": "string"},
        "output": {"sql": "string", "explanation": "string", "dialect": "string", "assumed_schema": "string"},
    },
    "sql_to_nl": {
        "path": "/api/sql-to-nl",
        "description": "Explain SQL query in plain English",
        "max_price": "$0.02",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"sql": "string"},
        "output": {"explanation": "string", "tables_used": "[string]", "operations": "[string]",
                   "complexity": "simple|moderate|complex"},
    },
    "git_summarize": {
        "path": "/api/git-summarize",
        "description": "Summarize git diff into PR description",
        "max_price": "$0.02",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"diff": "string"},
        "output": {"title": "string", "description": "string", "breaking_changes": "[string]",
                   "files_summary": "[{file,what_changed,risk}]"},
    },
    "translate_code": {
        "path": "/api/translate-code",
        "description": "Translate code between languages (Python, TS, Rust, Go, Solidity)",
        "max_price": "$0.05",
        "base_microunits": 20_000,
        "min_price_microunits": 10_000,
        "input": {"code": "string", "source_lang": "string", "target_lang": "string"},
        "output": {"translated_code": "string", "notes": "[string]"},
    },
    "whale_tracker": {
        "path": "/api/whale-tracker",
        "description": "Whale movement analysis — large USDC transfers on Base/Arbitrum",
        "max_price": "$0.03",
        "base_microunits": 15_000,
        "min_price_microunits": 7_500,
        "input": {"asset": "string", "wallet_address": "string (optional)", "timeframe": "string (optional)"},
        "output": {"asset": "string", "total_whale_volume_24h_usd": "number", "movements": "[...]", "net_flow_usd": "number", "analysis": "string", "confidence": "low|medium|high"},
    },
    "smart_money": {
        "path": "/api/smart-money",
        "description": "Smart money wallet analysis — win rate, patterns, profitability",
        "max_price": "$0.05",
        "base_microunits": 25_000,
        "min_price_microunits": 12_500,
        "input": {"wallet_address": "string", "chain": "string (optional)"},
        "output": {"wallet": "string", "estimated_win_rate": "0-100%", "profitability_score": "0-100", "smart_money_indicators": "[...]", "analysis": "string", "confidence": "low|medium|high"},
    },
    "agent_audit": {
        "path": "/api/agent-audit",
        "description": "Full AI agent security audit — code, behavior, trust score",
        "max_price": "$0.50",
        "base_microunits": 250_000,
        "min_price_microunits": 125_000,
        "input": {"agent_code": "string", "behavior_description": "string (optional)", "agent_name": "string (optional)"},
        "output": {"agent_name": "string", "audit_summary": "string", "vulnerabilities": "[...]", "trust_score": "0-100", "recommendations": "[...]"},
    },
    "contract_verify": {
        "path": "/api/contract-verify",
        "description": "Smart contract formal verification — 36 SWC + DeFi exploits",
        "max_price": "$1.00",
        "base_microunits": 500_000,
        "min_price_microunits": 250_000,
        "input": {"contract_code": "string", "contract_name": "string (optional)", "network": "string (optional)"},
        "output": {"contract_name": "string", "verification_summary": "string", "vulnerabilities": "[...]", "security_score": "0-100", "audit_recommendation": "pass|fail"},
    },
    "security_score": {
        "path": "/api/security-score",
        "description": "Rapid security assessment — quick score and risk level",
        "max_price": "$0.10",
        "base_microunits": 50_000,
        "min_price_microunits": 25_000,
        "input": {"code": "string", "description": "string (optional)"},
        "output": {"target": "string", "quick_score": "0-100", "risk_level": "low|medium|high|critical", "summary": "string"},
    },
    "data_feed": {
        "path": "/api/data-feed",
        "description": "Structured data feed on any topic — machine-readable JSON",
        "max_price": "$0.02",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"topic": "string", "format": "string (optional)"},
        "output": {"feed_topic": "string", "entries": "[...]", "total_entries": "number", "metadata": "{...}"},
    },
    "price_feed": {
        "path": "/api/price-feed",
        "description": "AI-enhanced token price analysis with support/resistance levels",
        "max_price": "$0.02",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"token": "string"},
        "output": {"token": "string", "estimated_price_range": "string", "support_zones": "[...]", "resistance_zones": "[...]", "sentiment": "bullish|bearish|neutral", "analysis": "string", "disclaimer": "Training data only. Not financial advice."},
    },
    "debug_log": {
        "path": "/api/debug-log",
        "description": "CI/CD error log analysis — root cause and fix suggestions",
        "max_price": "$0.03",
        "base_microunits": 10_000,
        "min_price_microunits": 5_000,
        "input": {"log": "string", "context": "string (optional)"},
        "output": {"error_type": "string", "root_cause": "string", "fix": "string", "code_fix": "string", "prevention": "string"},
    },
}

EXACT_SERVICES = {
    "validate_json": {
        "path": "/api/validate-json",
        "description": "Validate JSON/YAML structure, schema, types",
        "price": "$0.0005",
        "microunits": 500,
        "input": {"data": "string", "schema": "string (optional)"},
        "output": {"valid": "boolean", "errors": "[{line,message,fix}]", "warnings": "[{line,message}]"},
    },
    "classify_text": {
        "path": "/api/classify-text",
        "description": "Classify text — sentiment, category, keywords, language",
        "price": "$0.001",
        "microunits": 1000,
        "input": {"text": "string", "categories": "string (optional)"},
        "output": {"sentiment": "positive|negative|neutral", "category": "string",
                   "confidence": "0.0-1.0", "keywords": "[string]", "language": "string"},
    },
    "extract_data": {
        "path": "/api/extract-data",
        "description": "Extract structured data — names, emails, phones, URLs, dates, amounts",
        "price": "$0.005",
        "microunits": 5000,
        "input": {"text": "string"},
        "output": {"entities": "[{type,value,confidence}]"},
    },
    "generate_regex": {
        "path": "/api/generate-regex",
        "description": "Generate regex pattern from description with test cases",
        "price": "$0.002",
        "microunits": 2000,
        "input": {"description": "string"},
        "output": {"pattern": "string", "flags": "string",
                   "test_cases": "[{input,matches,captured}]", "explanation": "string"},
    },
    "format_data": {
        "path": "/api/format-data",
        "description": "Convert data between CSV, JSON, YAML formats",
        "price": "$0.003",
        "microunits": 3000,
        "input": {"data": "string", "source_format": "csv|json|yaml", "target_format": "csv|json|yaml"},
        "output": {"converted": "string", "format": "string", "warnings": "[string]"},
    },
    "summarize": {
        "path": "/api/summarize",
        "description": "Summarize text to N words, extract key points",
        "price": "$0.002",
        "microunits": 2000,
        "input": {"text": "string", "max_length": "integer (optional)"},
        "output": {"summary": "string", "word_count": "integer", "key_points": "[string]"},
    },
}

ALL_SERVICES = {**{f"POST {v['path']}": v for v in AI_UPTO_SERVICES.values()},
                **{f"POST {v['path']}": v for v in EXACT_SERVICES.values()}}

# Composite skills (chain multiple tools)
COMPOSITE_SKILLS = {
    "defi_research": {
        "description": "Full DeFi research pipeline: extract on-chain data → analyze protocol → summarize findings",
        "chain": ["extract_data", "defi_analyze", "summarize"],
        "price": "$0.08",
        "input": {"protocol": "string", "chain": "string", "onchain_data": "string"},
    },
    "code_health_check": {
        "description": "Complete code health: security audit → refactor → generate documentation",
        "chain": ["audit", "refactor", "docs"],
        "price": "$0.10",
        "input": {"code": "string", "instructions": "string (optional)"},
    },
    "smart_contract_audit": {
        "description": "Solidity audit + documentation: scan vulnerabilities → generate audit report",
        "chain": ["solidity_scan", "docs"],
        "price": "$0.10",
        "input": {"code": "string"},
    },
    "data_pipeline": {
        "description": "Data processing pipeline: extract entities → convert format → summarize",
        "chain": ["extract_data", "format_data", "summarize"],
        "price": "$0.05",
        "input": {"text": "string", "target_format": "csv|json|yaml"},
    },
}
