"""Refactor route — DRY, SOLID, modern patterns."""
from fastapi import APIRouter, Request
from app.models import RefactorRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services import credits, analytics
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 30000


def _get_network(request: Request) -> str:
    try:
        return request.state.payment_requirements.network
    except AttributeError:
        return "unknown"


def _get_tx(request: Request) -> str:
    try:
        return request.state.payment_payload.transaction
    except AttributeError:
        return "unknown"


@router.post("/api/refactor")
async def refactor_endpoint(request: Request, body: RefactorRequest):
    user_content = f"Instructions: {body.instructions}\n\nCode:\n{body.code}" if body.instructions else body.code
    result, tokens = await deepseek_completion(REFACTOR_SYSTEM_PROMPT, user_content, body.context, json_mode=True)
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("refactor", "api_key", True, tokens, cost_cents / 100)
    else:
        analytics.track("refactor", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=_get_network(request), payment_tx=_get_tx(request))
