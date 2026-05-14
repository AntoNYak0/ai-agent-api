from fastapi import APIRouter, Request
from app.models import RefactorRequest, RefactorResponse
from app.services.deepseek import deepseek_completion
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT

router = APIRouter()


@router.post("/api/refactor")
async def refactor_endpoint(request: Request, body: RefactorRequest):
    user_content = body.code
    if body.instructions:
        user_content = f"Инструкции по рефакторингу: {body.instructions}\n\nКод:\n{body.code}"

    result = await deepseek_completion(
        system_prompt=REFACTOR_SYSTEM_PROMPT,
        user_content=user_content,
        context_window=body.context,
    )
    return RefactorResponse(
        refactored_code=result,
        explanation="Рефакторинг выполнен. Подробности в refactored_code.",
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
