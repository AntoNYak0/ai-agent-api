"""Data feed route — structured data feeds from AI training data."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import BaseModel, Field, ServiceResponse
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.pricing import round_up_cents
from app.prompts.data_feed import DATA_FEED_PROMPT
from app.x402_setup import settle_actual_usage, validate_min_price

router = APIRouter()
CREDIT_MULTIPLIER = 1.5
FEED_BASE = 10_000      # $0.01 base
FEED_MIN = 5_000        # $0.005 min authorized


class DataFeedRequest(BaseModel):
    topic: str = Field(max_length=5_000)
    format: str | None = Field(default="json", max_length=200)


@router.post("/api/data-feed")
async def data_feed(request: Request, body: DataFeedRequest):
    ok, err = validate_min_price(request, FEED_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    content = f"Topic: {body.topic}\nRequested format: {body.format or 'json'}"
    result, tokens = await cached_completion("data-feed", content, DATA_FEED_PROMPT, None, json_mode=True)

    is_api_key = hasattr(request.state, "human_api_key")
    microunits = FEED_BASE + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        ok = credits.spend_credits(request.state.human_api_key, cost_cents)
        if not ok:
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
        analytics.track("data-feed", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("data-feed", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
