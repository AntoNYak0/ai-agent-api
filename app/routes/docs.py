from fastapi import APIRouter, Request
from app.models import DocsRequest, DocsResponse
from app.services.deepseek import deepseek_completion
from app.prompts.docs import DOCS_SYSTEM_PROMPT

router = APIRouter()


@router.post("/api/docs")
async def docs_endpoint(request: Request, body: DocsRequest):
    result = await deepseek_completion(
        system_prompt=DOCS_SYSTEM_PROMPT,
        user_content=body.code,
        context_window=body.context,
    )
    return DocsResponse(
        documentation=result,
        payment_network=_get_network(request),
        payment_tx=_get_tx(request),
    )


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
