from fastapi import APIRouter, Request
from app.models import AuditRequest, AuditResponse
from app.services.deepseek import deepseek_completion
from app.prompts.audit import AUDIT_SYSTEM_PROMPT

router = APIRouter()


@router.post("/api/audit")
async def audit_endpoint(request: Request, body: AuditRequest):
    result = await deepseek_completion(
        system_prompt=AUDIT_SYSTEM_PROMPT,
        user_content=body.code,
        context_window=body.context,
    )
    return AuditResponse(
        analysis=result,
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
