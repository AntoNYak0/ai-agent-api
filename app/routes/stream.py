"""Streaming endpoint — SSE for real-time AI responses."""
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
from app.services.deepseek import deepseek_completion_stream
from app.services import analytics
from app.prompts.audit import AUDIT_SYSTEM_PROMPT
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT
from app.prompts.docs import DOCS_SYSTEM_PROMPT
from app.prompts.trading import TRADING_SYSTEM_PROMPT
from app.prompts.solidity_scan import SOLIDITY_SCAN_PROMPT

router = APIRouter()

_PROMPTS = {
    "audit": AUDIT_SYSTEM_PROMPT,
    "refactor": REFACTOR_SYSTEM_PROMPT,
    "docs": DOCS_SYSTEM_PROMPT,
    "trading": TRADING_SYSTEM_PROMPT,
    "solidity-scan": SOLIDITY_SCAN_PROMPT,
}


@router.post("/api/stream/{tool}")
async def stream_tool(
    request: Request,
    tool: str,
    input: str = Query(..., description="User input/code to process"),
    context: str = Query("", description="Optional context"),
):
    """Stream AI response via SSE. Tools: audit, refactor, docs, trading, solidity-scan."""
    if tool not in _PROMPTS:
        return StreamingResponse(
            iter([f"data: {{'error': 'Unknown tool: {tool}'}}\n\n"]),
            media_type="text/event-stream",
        )

    async def generate():
        try:
            async for chunk in deepseek_completion_stream(
                _PROMPTS[tool], input, context or None, json_mode=True
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {{'error': '{str(e)}'}}\n\n"

    analytics.track(
        tool, "x402" if not hasattr(request.state, "human_api_key") else "api_key",
        True, 0, 0
    )
    return StreamingResponse(generate(), media_type="text/event-stream")
