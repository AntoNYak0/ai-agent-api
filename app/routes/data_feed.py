"""Data feed route — structured data feeds from AI training data."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx, build_upto_response
from app.models import BaseModel, Field, ServiceResponse
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.pricing import round_up_cents, get_max_tokens, calc_upto_cost
from app.prompts.data_feed import DATA_FEED_PROMPT
from app.x402_setup import settle_actual_usage, validate_min_price

router = APIRouter()
CREDIT_MULTIPLIER = 1.5
FEED_BASE = 10_000      # $0.01 base
FEED_MIN = 5_000        # $0.005 min authorized
FEED_MAX = 20_000       # $0.02 cap


class DataFeedRequest(BaseModel):
    topic: str = Field(max_length=5_000)
    format: str | None = Field(default="json", max_length=200)


@router.post("/api/data-feed")
async def data_feed(request: Request, body: DataFeedRequest):
    ok, err = validate_min_price(request, FEED_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        if not credits.pre_deduct_max(request.state.human_api_key, FEED_MAX):
            analytics.track("data-feed", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    content = f"Topic: {body.topic}\nRequested format: {body.format or 'json'}"
    result, tokens, _ = await cached_completion("data-feed", content, DATA_FEED_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("data-feed"))

    microunits, multiplier, tier = calc_upto_cost(FEED_BASE, tokens, FEED_MAX)
    if is_api_key:
        credits.finalize_deduction(request.state.human_api_key, FEED_MAX, microunits)
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        analytics.track("data-feed", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("data-feed", "x402", True, tokens, microunits / 1e6)

    return build_upto_response(result, request, microunits, multiplier, tier, tokens)
