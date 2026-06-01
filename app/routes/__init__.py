"""Shared route helpers — imported by all route modules."""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.models import ServiceResponse


def get_network(request: Request) -> str:
    try:
        return request.state.payment_requirements.network
    except AttributeError:
        return "unknown"


def get_tx(request: Request) -> str:
    try:
        return request.state.payment_payload.payload.get("transactionHash", "unknown")
    except AttributeError:
        return "unknown"


def build_upto_response(result: str, request: Request, microunits: int,
                         multiplier: float, tier: str, tokens: int) -> JSONResponse:
    """Build JSONResponse with X-Actual-Cost header for upto billing transparency.

    Header format: "microunits=NNNNNN cost=$X.XXXXXX tier=simple|normal|complex multiplier=X.Xx tokens=NNNN"
    """
    cost_usd = microunits / 1_000_000
    header_value = (
        f"microunits={microunits} cost=${cost_usd:.6f} "
        f"tier={tier} multiplier={multiplier}x tokens={tokens}"
    )
    return JSONResponse(
        content=ServiceResponse(
            result=result,
            payment_network=get_network(request),
            payment_tx=get_tx(request),
        ).model_dump(),
        headers={"X-Actual-Cost": header_value},
    )
