"""Streaming endpoint — SSE for real-time AI responses. Payment required."""
import logging
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse, JSONResponse
from app.services.deepseek import deepseek_completion_stream
from app.services import credits, analytics
from app.x402_setup import settle_actual_usage, validate_min_price
from app.routes import get_network, get_tx
from app.pricing import round_up_cents, get_max_tokens, calc_upto_cost
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
_MAX_MICROUNITS = {
    "audit": 50_000, "refactor": 50_000, "docs": 30_000,
    "trading": 30_000, "solidity-scan": 80_000,
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

    # Credit pre-deduct for API key users BEFORE streaming (closes TOCTOU gap)
    max_mu = _MAX_MICROUNITS.get(tool, 50_000)
    if is_api_key:
        if not credits.pre_deduct_max(request.state.human_api_key, max_mu):
            analytics.track(tool, "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits",
                "message": f"Need at least ${max_mu/1_000_000:.2f} in credits"})

    async def generate():
        tokens = 0
        compressed = False
        try:
            stream = deepseek_completion_stream(
                _PROMPTS[tool], input, context or None, json_mode=True, max_tokens=get_max_tokens(tool)
            )
            # First value is the compression flag
            first = await stream.__anext__()
            if isinstance(first, bool):
                compressed = first
                if compressed:
                    yield "event: meta\ndata: {\"context_compressed\": true}\n\n"
            else:
                # No compression flag (legacy) — treat as content
                tokens += len(first) // 4 if isinstance(first, str) else 0
                yield f"data: {first}\n\n"

            async for chunk in stream:
                tokens += len(chunk) // 4  # rough token estimate from chars
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except StopAsyncIteration:
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f'data: {{"error": "{str(e)}"}}\n\n'

        # Settle after stream completes
        base = _BASE_MICROUNITS.get(tool, 20_000)
        microunits, _, _ = calc_upto_cost(base, tokens, max_mu)
        if not is_api_key:
            try:
                await settle_actual_usage(request, microunits)
            except Exception:
                logger.warning("x402 settlement failed after stream: tool=%s tokens=%s", tool, tokens)
            analytics.track(tool, "x402", True, tokens, microunits / 1e6)
        else:
            credits.finalize_deduction(request.state.human_api_key, max_mu, microunits)
            cost_cents = round_up_cents((microunits / 10_000) * _CREDIT_MULTIPLIER)
            analytics.track(tool, "api_key", True, tokens, cost_cents / 100)

    return StreamingResponse(generate(), media_type="text/event-stream")
