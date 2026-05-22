"""Streaming endpoint — SSE for real-time AI responses. Payment required."""
import logging
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse, JSONResponse
from app.services.deepseek import deepseek_completion_stream
from app.services import credits, analytics
from app.x402_setup import settle_actual_usage, validate_min_price
from app.routes import get_network, get_tx
from app.pricing import round_up_cents, get_max_tokens, PER_1K_TOKENS_MICROUNITS
from app.prompts.audit import AUDIT_SYSTEM_PROMPT
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT
from app.prompts.docs import DOCS_SYSTEM_PROMPT
from app.prompts.trading import TRADING_SYSTEM_PROMPT
from app.prompts.solidity_scan import SOLIDITY_SCAN_PROMPT

logger = logging.getLogger("stream")
router = APIRouter()

_PROMPTS = {
    "audit": AUDIT_SYSTEM_PROMPT,
    "refactor": REFACTOR_SYSTEM_PROMPT,
    "docs": DOCS_SYSTEM_PROMPT,
    "trading": TRADING_SYSTEM_PROMPT,
    "solidity-scan": SOLIDITY_SCAN_PROMPT,
}

_BASE_MICROUNITS = {
    "audit": 20_000, "refactor": 30_000, "docs": 10_000,
    "trading": 10_000, "solidity-scan": 40_000,
}
_MIN_MICROUNITS = {
    "audit": 10_000, "refactor": 10_000, "docs": 5_000,
    "trading": 5_000, "solidity-scan": 20_000,
}
_CREDIT_MULTIPLIER = 1.5


@router.post("/api/stream/{tool}")
async def stream_tool(
    request: Request,
    tool: str,
    input: str = Query(..., description="User input/code to process"),
    context: str = Query("", description="Optional context"),
):
    """Stream AI response via SSE. Payment required."""
    if tool not in _PROMPTS:
        return StreamingResponse(
            iter([f'data: {{"error": "Unknown tool: {tool}"}}\n\n']),
            media_type="text/event-stream",
        )

    # Payment check — x402
    ok, err = validate_min_price(request, _MIN_MICROUNITS.get(tool, 10_000))
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")

    # Credit pre-check for API key users BEFORE streaming
    if is_api_key:
        estimated_microunits = _BASE_MICROUNITS.get(tool, 20_000) + 30_000  # base + ~10K tokens
        estimated_cents = round_up_cents((estimated_microunits / 10_000) * _CREDIT_MULTIPLIER)
        balance = credits.get_balance(request.state.human_api_key)
        if not balance or (balance["credits"] / 10) < estimated_cents:
            analytics.track(tool, "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits",
                "message": f"Need ~{estimated_cents} credits, have {balance['credits'] if balance else 0}"})

    async def generate():
        tokens = 0
        try:
            async for chunk in deepseek_completion_stream(
                _PROMPTS[tool], input, context or None, json_mode=True, max_tokens=get_max_tokens(tool)
            ):
                tokens += len(chunk) // 4  # rough token estimate from chars
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f'data: {{"error": "{str(e)}"}}\n\n'

        # Settle after stream completes
        if not is_api_key:
            microunits = _BASE_MICROUNITS.get(tool, 20_000) + int((tokens / 1000) * PER_1K_TOKENS_MICROUNITS)
            await settle_actual_usage(request, microunits)
            analytics.track(tool, "x402", True, tokens, microunits / 1e6)
        else:
            microunits = _BASE_MICROUNITS.get(tool, 20_000) + int((tokens / 1000) * PER_1K_TOKENS_MICROUNITS)
            cost_cents = round_up_cents((microunits / 10_000) * _CREDIT_MULTIPLIER)
            ok = credits.spend_credits(request.state.human_api_key, cost_cents)
            if not ok:
                logger.warning("spend_credits failed after stream: tool=%s key=%s... cents=%s",
                               tool, request.state.human_api_key[:10], cost_cents)
            analytics.track(tool, "api_key", ok, tokens, cost_cents / 100 if ok else 0)

    return StreamingResponse(generate(), media_type="text/event-stream")
