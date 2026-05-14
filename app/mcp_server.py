"""MCP server — exposes paid AI tools to other AI agents via x402.

Other agents (Claude, Cursor, etc.) can discover and call:
- audit — $15 USDC
- refactor — $10 USDC
- docs — $5 USDC
"""
from mcp.server.fastmcp import FastMCP
from app.config import settings
from app.services.deepseek import deepseek_completion
from app.prompts.audit import AUDIT_SYSTEM_PROMPT
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT
from app.prompts.docs import DOCS_SYSTEM_PROMPT
from app.facilitator import DirectFacilitator

mcp = FastMCP(
    name="ai-agent-api",
    instructions="""
AI Agent API — платные инструменты для разработчиков через x402.

Доступные инструменты:
- audit ($15 USDC) — аудит безопасности кода
- refactor ($10 USDC) — рефакторинг легаси-кода
- docs ($5 USDC) — генерация технической документации

Оплата: USDC на Base (eip155:8453) или Polygon (eip155:137).
После перевода USDC укажи transactionHash в параметре payment_tx.
Кошелёк: 0xdE7eb04faE758055642f67f30D246CCb7136C95E
""",
)

facilitator = DirectFacilitator(
    testnet=settings.testnet,
    pay_to=settings.pay_to_address_evm,
)

PAY_TO = settings.pay_to_address_evm
PRICES = {"audit": "$15.00", "refactor": "$10.00", "docs": "$5.00"}
AMOUNTS = {"audit": "15000000", "refactor": "10000000", "docs": "5000000"}


async def _verify_payment(payment_tx: str, amount: str) -> tuple[bool, str]:
    """Verify a USDC payment via the facilitator."""
    if settings.testnet:
        return True, "testnet"

    if not payment_tx:
        return False, f"Payment required: send {int(amount)/1e6} USDC to {PAY_TO} on Base/Polygon, then call with payment_tx=<hash>"

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

    result = await facilitator.verify(payload, requirements)
    if result.is_valid:
        return True, result.payer or "verified"
    return False, result.invalid_message or "Payment verification failed"


def _payment_help(service: str) -> str:
    """Generate payment instructions."""
    return (
        f"To use this tool, send {PRICES[service]} USDC to {PAY_TO} "
        f"on Base (eip155:8453) or Polygon (eip155:137), "
        f"then call again with payment_tx=<transaction-hash>"
    )


@mcp.tool(
    name="audit",
    description=f"Аудит безопасности кода / смарт-контрактов. Цена: {PRICES['audit']} USDC.",
)
async def audit_tool(code: str, context: str = "", payment_tx: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["audit"])
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('audit')}"

    return await deepseek_completion(
        system_prompt=AUDIT_SYSTEM_PROMPT,
        user_content=code,
        context_window=context or None,
    )


@mcp.tool(
    name="refactor",
    description=f"Рефакторинг легаси-кода с полным анализом. Цена: {PRICES['refactor']} USDC.",
)
async def refactor_tool(
    code: str, instructions: str = "", context: str = "", payment_tx: str = ""
) -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["refactor"])
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('refactor')}"

    user_content = code
    if instructions:
        user_content = f"Инструкции: {instructions}\n\nКод:\n{code}"

    return await deepseek_completion(
        system_prompt=REFACTOR_SYSTEM_PROMPT,
        user_content=user_content,
        context_window=context or None,
    )


@mcp.tool(
    name="docs",
    description=f"Генерация технической документации. Цена: {PRICES['docs']} USDC.",
)
async def docs_tool(code: str, context: str = "", payment_tx: str = "") -> str:
    valid, info = await _verify_payment(payment_tx, AMOUNTS["docs"])
    if not valid:
        return f"Payment required: {info}\n\n{_payment_help('docs')}"

    return await deepseek_completion(
        system_prompt=DOCS_SYSTEM_PROMPT,
        user_content=code,
        context_window=context or None,
    )
