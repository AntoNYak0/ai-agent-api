"""MCP server — exposes paid AI tools to other AI agents via x402.

16 tools: audit, refactor, docs, defi, trading, solidity-scan + 10 micro-tasks.
AI services use upto (usage-based) pricing; micro-tasks use exact (flat) pricing.
All priced for machine-to-machine economy ($0.001–$0.10 USDC).
"""
import logging
from mcp.server.fastmcp import FastMCP
from app.config import settings
from app.services.deepseek import deepseek_completion
from app.services.replay_guard import is_replay
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
)
from x402.http.facilitator_client import HTTPFacilitatorClient, FacilitatorConfig
from app.facilitator import DirectFacilitator, TronFacilitator, TRON_NETWORK, USDT_TRC20_CONTRACT
from mcp.server.fastmcp.server import TransportSecuritySettings

logger = logging.getLogger("mcp_server")

mcp = FastMCP(
    name="ai-agent-api",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
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
- validate-json ($0.0005 USDC) — validate JSON/YAML
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

if settings.testnet:
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

# Token rate: $0.003 per 1K tokens (DeepSeek cost ~$0.0014/1K, x2 margin)
PER_1K_TOKENS_MICROUNITS = 3000  # $0.003
CREDIT_MULTIPLIER = 1.5  # humans pay 1.5x vs crypto (covers Stripe 2.9% + buffer)


def _credits_cost_cents(microunits: int) -> int:
    """Convert microunits to credit cents with 1.5x multiplier, min 1 cent."""
    cents = (microunits / 10000) * CREDIT_MULTIPLIER
    return max(1, round(cents))

# ── Pricing tables ──────────────────────────────────────────────

# AI services: (base_price_microunits, max_price_microunits, display_name)
UPTO_SERVICES = {
    "audit":       (10000, 50000, "$0.01–$0.05"),
    "refactor":    (10000, 50000, "$0.01–$0.05"),
    "docs":        (5000,  30000, "$0.005–$0.03"),
    "defi":        (10000, 40000, "$0.01–$0.04"),
    "trading":     (5000,  30000, "$0.005–$0.03"),
    "solidity-scan": (20000, 80000, "$0.02–$0.08"),
    "nl-to-sql":   (5000,  30000, "$0.005–$0.03"),
    "sql-to-nl":   (5000,  20000, "$0.005–$0.02"),
    "git-summarize": (5000, 20000, "$0.005–$0.02"),
    "translate-code": (10000, 50000, "$0.01–$0.05"),
}

# Micro-tasks: exact pricing (amount in microunits, display price)
EXACT_SERVICES = {
    "validate-json":  ("500",  "$0.0005"),
    "classify-text":  ("1000", "$0.001"),
    "extract-data":   ("5000", "$0.005"),
    "generate-regex": ("2000", "$0.002"),
    "format-data":    ("3000", "$0.003"),
    "summarize":      ("2000", "$0.002"),
}

# Build PRICES and AMOUNTS for backward compat
PRICES = {}
AMOUNTS = {}

for name, (base, max_, display) in UPTO_SERVICES.items():
    PRICES[name] = display
    AMOUNTS[name] = str(max_)  # verify checks against max

for name, (amount, display) in EXACT_SERVICES.items():
    PRICES[name] = display
    AMOUNTS[name] = amount


async def _verify_payment(payment_tx: str, amount: str, tool_name: str = "unknown", api_key: str = "") -> tuple[bool, str]:
    """Verify payment (x402 or API key credits). Returns (is_valid, info_message)."""
    # 1. API key credits (human developers)
    if api_key:
        balance = credits.get_balance(api_key)
        if not balance:
            return False, f"Invalid API key: {api_key[:10]}..."
        if balance["credits"] <= 0:
            return False, f"API key {api_key[:10]}... has no credits. Top up at /billing/top-up"
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

    from x402.schemas import PaymentPayload, PaymentRequirements

    payload = PaymentPayload(
        x402_version=2,
        payload={"transactionHash": payment_tx, "payer": "mcp-client"},
        accepted=PaymentRequirements(
            scheme="exact",
            network="eip155:8453",
            asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            amount=amount,
            pay_to=PAY_TO,
            max_timeout_seconds=300,
        ),
    )
    requirements = PaymentRequirements(
        scheme="exact",
        network="eip155:8453",
        asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
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
        f"on Base (eip155:8453), Arbitrum (eip155:42161), Optimism (eip155:10){tron_part}, "
        f"then call again with payment_tx=<transaction-hash>"
    )


def _calc_upto_amount(service: str, tokens_used: int) -> int:
    """Calculate actual cost for upto service = base + token rate, capped at max."""
    base, max_amount, _ = UPTO_SERVICES[service]
    token_cost = (tokens_used / 1000) * PER_1K_TOKENS_MICROUNITS
    actual = int(base + token_cost)
    return min(actual, max_amount)


async def _settle_payment(payment_tx: str, actual_amount: int):
    """Settle upto payment with actual usage amount."""
    if settings.testnet:
        return
    try:
        from x402.schemas import PaymentPayload, PaymentRequirements
        payload = PaymentPayload(
            x402_version=2,
            payload={"transactionHash": payment_tx, "payer": "mcp-client"},
            accepted=PaymentRequirements(
                scheme="exact",
                network="eip155:8453",
                asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                amount=str(actual_amount),
                pay_to=PAY_TO,
                max_timeout_seconds=300,
            ),
        )
        await facilitator.settle(payload)
    except Exception as e:
        logger.warning(f"Settle failed (non-critical): {e}")


# ── Complex services (upto pricing) ─────────────────────────────

@mcp.tool(name="audit", description=f"Security scan with OWASP + SWC taxonomy. Price: {PRICES['audit']} USDC.")
async def audit_tool(code: str, context: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["audit"], "audit", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('audit')}"
    use_credits = info.startswith("credits:")
    result, tokens = await deepseek_completion(AUDIT_SYSTEM_PROMPT, code, context or None, json_mode=True)
    actual = _calc_upto_amount("audit", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


@mcp.tool(name="refactor", description=f"Refactor legacy code (DRY, SOLID). Price: {PRICES['refactor']} USDC.")
async def refactor_tool(code: str, instructions: str = "", context: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["refactor"], "refactor", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('refactor')}"
    use_credits = info.startswith("credits:")
    user_content = f"Instructions: {instructions}\n\nCode:\n{code}" if instructions else code
    result, tokens = await deepseek_completion(REFACTOR_SYSTEM_PROMPT, user_content, context or None, json_mode=True)
    actual = _calc_upto_amount("refactor", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


@mcp.tool(name="docs", description=f"Generate technical docs from code. Price: {PRICES['docs']} USDC.")
async def docs_tool(code: str, context: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["docs"], "docs", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('docs')}"
    use_credits = info.startswith("credits:")
    result, tokens = await deepseek_completion(DOCS_SYSTEM_PROMPT, code, context or None, json_mode=True)
    actual = _calc_upto_amount("docs", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


@mcp.tool(name="defi", description=f"DeFi protocol analysis. Price: {PRICES['defi']} USDC.")
async def defi_tool(protocol: str, chain: str = "Ethereum", details: str = "", onchain_data: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["defi"], "defi", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('defi')}"
    use_credits = info.startswith("credits:")
    user_content = f"Protocol: {protocol}\nBlockchain: {chain}"
    if details:
        user_content += f"\n\nDetails: {details}"
    if onchain_data:
        user_content += f"\n\nProvided onchain data:\n{onchain_data}"
    result, tokens = await deepseek_completion(DEFI_SYSTEM_PROMPT, user_content, json_mode=True)
    actual = _calc_upto_amount("defi", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


@mcp.tool(name="trading", description=f"Crypto trading analytics. Price: {PRICES['trading']} USDC.")
async def trading_tool(asset: str, timeframe: str = "daily", additional_info: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["trading"], "trading", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('trading')}"
    use_credits = info.startswith("credits:")
    user_content = f"Asset: {asset}\nTimeframe: {timeframe}"
    if additional_info:
        user_content += f"\n\nAdditional info: {additional_info}"
    result, tokens = await deepseek_completion(TRADING_SYSTEM_PROMPT, user_content, json_mode=True)
    actual = _calc_upto_amount("trading", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


# ── Solidity scanner (upto pricing) ──────────────────────────────

@mcp.tool(name="solidity-scan", description=f"Solidity vulnerability scanner (SWC Registry). Price: {PRICES['solidity-scan']} USDC.")
async def solidity_scan_tool(code: str, context: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["solidity-scan"], "solidity-scan", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('solidity-scan')}"
    use_credits = info.startswith("credits:")
    result, tokens = await deepseek_completion(SOLIDITY_SCAN_PROMPT, code, context or None, json_mode=True)
    actual = _calc_upto_amount("solidity-scan", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


# ── SQL services (upto pricing) ──────────────────────────────────

@mcp.tool(name="nl-to-sql", description=f"Natural language to SQL. Price: {PRICES['nl-to-sql']} USDC.")
async def nl_to_sql_tool(query: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["nl-to-sql"], "nl-to-sql", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('nl-to-sql')}"
    use_credits = info.startswith("credits:")
    result, tokens = await deepseek_completion(NL_TO_SQL_PROMPT, query, json_mode=True)
    actual = _calc_upto_amount("nl-to-sql", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


@mcp.tool(name="sql-to-nl", description=f"SQL to plain English explanation. Price: {PRICES['sql-to-nl']} USDC.")
async def sql_to_nl_tool(sql: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["sql-to-nl"], "sql-to-nl", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('sql-to-nl')}"
    use_credits = info.startswith("credits:")
    result, tokens = await deepseek_completion(SQL_TO_NL_PROMPT, sql, json_mode=True)
    actual = _calc_upto_amount("sql-to-nl", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


# ── Dev tools (upto pricing) ─────────────────────────────────────

@mcp.tool(name="git-summarize", description=f"Git diff to PR description. Price: {PRICES['git-summarize']} USDC.")
async def git_summarize_tool(diff: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["git-summarize"], "git-summarize", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('git-summarize')}"
    use_credits = info.startswith("credits:")
    result, tokens = await deepseek_completion(GIT_SUMMARIZE_PROMPT, diff, json_mode=True)
    actual = _calc_upto_amount("git-summarize", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


@mcp.tool(name="translate-code", description=f"Translate code between languages. Price: {PRICES['translate-code']} USDC.")
async def translate_code_tool(code: str, source_lang: str, target_lang: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["translate-code"], "translate-code", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('translate-code')}"
    use_credits = info.startswith("credits:")
    prompt = TRANSLATE_CODE_PROMPT.format(source_lang=source_lang, target_lang=target_lang)
    result, tokens = await deepseek_completion(prompt, code, json_mode=True)
    actual = _calc_upto_amount("translate-code", tokens)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(actual))
    else:
        await _settle_payment(payment_tx, actual)
    return result


# ── Micro-tasks (exact pricing) ──────────────────────────────────

@mcp.tool(name="validate-json", description=f"Validate JSON/YAML structure. Price: {PRICES['validate-json']} USDC.")
async def validate_json_tool(data: str, schema: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["validate-json"], "validate-json", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('validate-json')}"
    use_credits = info.startswith("credits:")
    content = f"Target schema:\n{schema}\n\nData:\n{data}" if schema else data
    result, _ = await deepseek_completion(VALIDATE_JSON_PROMPT, content, json_mode=True)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(int(AMOUNTS["validate-json"])))
    return result


@mcp.tool(name="classify-text", description=f"Classify text sentiment/category. Price: {PRICES['classify-text']} USDC.")
async def classify_text_tool(text: str, categories: str = "", payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["classify-text"], "classify-text", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('classify-text')}"
    use_credits = info.startswith("credits:")
    content = f"Categories hint: {categories or 'auto-detect'}\n\nText:\n{text}"
    result, _ = await deepseek_completion(CLASSIFY_TEXT_PROMPT, content, json_mode=True)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(int(AMOUNTS["classify-text"])))
    return result


@mcp.tool(name="extract-data", description=f"Extract structured data from text. Price: {PRICES['extract-data']} USDC.")
async def extract_data_tool(text: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["extract-data"], "extract-data", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('extract-data')}"
    use_credits = info.startswith("credits:")
    result, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, text, json_mode=True)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(int(AMOUNTS["extract-data"])))
    return result


@mcp.tool(name="generate-regex", description=f"Generate regex from description. Price: {PRICES['generate-regex']} USDC.")
async def generate_regex_tool(description: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["generate-regex"], "generate-regex", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('generate-regex')}"
    use_credits = info.startswith("credits:")
    result, _ = await deepseek_completion(GENERATE_REGEX_PROMPT, description, json_mode=True)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(int(AMOUNTS["generate-regex"])))
    return result


@mcp.tool(name="format-data", description=f"Convert data CSV/JSON/YAML. Price: {PRICES['format-data']} USDC.")
async def format_data_tool(data: str, source_format: str, target_format: str, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["format-data"], "format-data", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('format-data')}"
    use_credits = info.startswith("credits:")
    prompt = FORMAT_DATA_PROMPT.format(source_format=source_format, target_format=target_format)
    result, _ = await deepseek_completion(prompt, data, json_mode=True)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(int(AMOUNTS["format-data"])))
    return result


@mcp.tool(name="summarize", description=f"Summarize text to N words. Price: {PRICES['summarize']} USDC.")
async def summarize_tool(text: str, max_length: int = 100, payment_tx: str = "", api_key: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["summarize"], "summarize", api_key)
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('summarize')}"
    use_credits = info.startswith("credits:")
    prompt = SUMMARIZE_PROMPT.format(max_length=max_length)
    result, _ = await deepseek_completion(prompt, text, json_mode=True)
    if use_credits:
        credits.spend_credits(api_key, _credits_cost_cents(int(AMOUNTS["summarize"])))
    return result
