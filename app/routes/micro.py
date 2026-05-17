"""Micro-task routes — high-frequency, low-cost AI services + SQL/dev tools."""
from fastapi import APIRouter, Request
from app.models import (
    ValidateJsonRequest, ClassifyTextRequest, ExtractDataRequest,
    TranslateCodeRequest, GenerateRegexRequest, FormatDataRequest,
    SummarizeRequest, NlToSqlRequest, SqlToNlRequest, GitSummarizeRequest,
    ServiceResponse,
)
from app.services.deepseek import deepseek_completion
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.micro import (
    VALIDATE_JSON_PROMPT, CLASSIFY_TEXT_PROMPT, EXTRACT_DATA_PROMPT,
    TRANSLATE_CODE_PROMPT, GENERATE_REGEX_PROMPT, FORMAT_DATA_PROMPT,
    SUMMARIZE_PROMPT, NL_TO_SQL_PROMPT, SQL_TO_NL_PROMPT, GIT_SUMMARIZE_PROMPT,
)
from app.routes import get_network, get_tx
from app.x402_setup import settle_actual_usage, validate_min_price
from fastapi.responses import JSONResponse

router = APIRouter()

# Credit prices in microunits (with 1.5x human multiplier)
_CREDIT_PRICES = {
    "validate-json": 1000, "classify-text": 2000, "extract-data": 15000,
    "generate-regex": 5000, "format-data": 10000, "summarize": 5000,
    "nl-to-sql": 10000, "sql-to-nl": 10000, "git-summarize": 10000,
    "translate-code": 20000,
}
_CREDIT_MULTIPLIER = 1.5


async def _deduct_and_track(request: Request, service: str, tokens_used: int = 0) -> bool:
    """Deduct credits for API key users, settle for x402, and track the call.
    Returns True if payment succeeded, False if insufficient credits."""
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = _CREDIT_PRICES.get(service, 10000)
    if tokens_used:
        microunits += int((tokens_used / 1000) * 3000)

    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * _CREDIT_MULTIPLIER))
        if not credits.spend_credits(request.state.human_api_key, cost_cents):
            analytics.track(service, "api_key", False, tokens_used, 0)
            return False
        amount_usd = cost_cents / 100
        method = "api_key"
    else:
        await settle_actual_usage(request, microunits)
        amount_usd = microunits / 1e6
        method = "x402"

    analytics.track(service, method, True, tokens_used, amount_usd)
    return True




# ── Micro-tasks ─────────────────────────────────────────────────

@router.post("/api/validate-json")
async def validate_json(request: Request, body: ValidateJsonRequest):
    content = f"Target schema:\n{body.target_schema}\n\nData:\n{body.data}" if body.target_schema else body.data
    result, _ = await deepseek_completion(VALIDATE_JSON_PROMPT, content, json_mode=True)
    ok = await _deduct_and_track(request, "validate-json")
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/classify-text")
async def classify_text(request: Request, body: ClassifyTextRequest):
    content = f"Categories hint: {body.categories or 'auto-detect'}\n\nText:\n{body.text}"
    result, _ = await deepseek_completion(CLASSIFY_TEXT_PROMPT, content, json_mode=True)
    ok = await _deduct_and_track(request, "classify-text")
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/extract-data")
async def extract_data(request: Request, body: ExtractDataRequest):
    result, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, body.text, json_mode=True)
    ok = await _deduct_and_track(request, "extract-data")
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/translate-code")
async def translate_code(request: Request, body: TranslateCodeRequest):
    ok, err = validate_min_price(request, 10_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    prompt = TRANSLATE_CODE_PROMPT.format(source_lang=body.source_lang, target_lang=body.target_lang)
    result, tokens = await cached_completion("translate-code", body.code, prompt, None, json_mode=True)
    ok = await _deduct_and_track(request, "translate-code", tokens)
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/generate-regex")
async def generate_regex(request: Request, body: GenerateRegexRequest):
    result, _ = await deepseek_completion(GENERATE_REGEX_PROMPT, body.description, json_mode=True)
    ok = await _deduct_and_track(request, "generate-regex")
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/format-data")
async def format_data(request: Request, body: FormatDataRequest):
    prompt = FORMAT_DATA_PROMPT.format(source_format=body.source_format, target_format=body.target_format)
    result, _ = await deepseek_completion(prompt, body.data, json_mode=True)
    ok = await _deduct_and_track(request, "format-data")
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/summarize")
async def summarize(request: Request, body: SummarizeRequest):
    prompt = SUMMARIZE_PROMPT.format(max_length=body.max_length)
    result, _ = await deepseek_completion(prompt, body.text, json_mode=True)
    ok = await _deduct_and_track(request, "summarize")
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


# ── SQL / Dev tools ────────────────────────────────────────────

@router.post("/api/nl-to-sql")
async def nl_to_sql(request: Request, body: NlToSqlRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    result, tokens = await cached_completion("nl-to-sql", body.query, NL_TO_SQL_PROMPT, None, json_mode=True)
    ok = await _deduct_and_track(request, "nl-to-sql", tokens)
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/sql-to-nl")
async def sql_to_nl(request: Request, body: SqlToNlRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    result, tokens = await cached_completion("sql-to-nl", body.sql, SQL_TO_NL_PROMPT, None, json_mode=True)
    ok = await _deduct_and_track(request, "sql-to-nl", tokens)
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/git-summarize")
async def git_summarize(request: Request, body: GitSummarizeRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    result, tokens = await cached_completion("git-summarize", body.diff, GIT_SUMMARIZE_PROMPT, None, json_mode=True)
    ok = await _deduct_and_track(request, "git-summarize", tokens)
    if not ok:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
