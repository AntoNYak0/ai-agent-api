"""Micro-task routes — high-frequency, low-cost AI services + SQL/dev tools."""
from fastapi import APIRouter, Request
from app.models import (
    ValidateJsonRequest, ClassifyTextRequest, ExtractDataRequest,
    TranslateCodeRequest, GenerateRegexRequest, FormatDataRequest,
    SummarizeRequest, NlToSqlRequest, SqlToNlRequest, GitSummarizeRequest,
    ServiceResponse, BaseModel, Field,
)
from app.services.deepseek import deepseek_completion
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.micro import (
    VALIDATE_JSON_PROMPT, CLASSIFY_TEXT_PROMPT, EXTRACT_DATA_PROMPT,
    TRANSLATE_CODE_PROMPT, GENERATE_REGEX_PROMPT, FORMAT_DATA_PROMPT,
    SUMMARIZE_PROMPT, NL_TO_SQL_PROMPT, SQL_TO_NL_PROMPT, GIT_SUMMARIZE_PROMPT,
    DEBUG_LOG_PROMPT,
)
from app.routes import get_network, get_tx
from app.pricing import round_up_cents
from app.x402_setup import settle_actual_usage, validate_min_price
from fastapi.responses import JSONResponse

router = APIRouter()

# Credit prices in microunits (with 1.5x human multiplier)
_CREDIT_PRICES = {
    "validate-json": 1000, "classify-text": 2000, "extract-data": 15000,
    "generate-regex": 5000, "format-data": 10000, "summarize": 5000,
    "nl-to-sql": 10000, "sql-to-nl": 10000, "git-summarize": 10000,
    "translate-code": 20000, "debug-log": 3000,
}
_CREDIT_MULTIPLIER = 1.5


async def _pre_check_credits(request: Request, service: str) -> bool:
    """Check API key credits BEFORE calling AI. Returns False if insufficient.
    Must be called BEFORE deepseek_completion to avoid wasting tokens on underfunded requests.
    """
    if not hasattr(request.state, "human_api_key"):
        return True  # x402 users validated by middleware
    microunits = _CREDIT_PRICES.get(service, 10000)
    cost_cents = round_up_cents((microunits / 10000) * _CREDIT_MULTIPLIER)
    balance = credits.get_balance(request.state.human_api_key)
    if not balance or (balance["credits"] / 10) < cost_cents:
        analytics.track(service, "api_key", False, 0, 0)
        return False
    return True


async def _settle_payment(request: Request, service: str, tokens_used: int = 0):
    """Settle payment AFTER successful AI call. Credits already pre-checked."""
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = _CREDIT_PRICES.get(service, 10000)
    if tokens_used:
        microunits += int((tokens_used / 1000) * 3000)

    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * _CREDIT_MULTIPLIER)
        credits.spend_credits(request.state.human_api_key, cost_cents)
        amount_usd = cost_cents / 100
        method = "api_key"
    else:
        await settle_actual_usage(request, microunits)
        amount_usd = microunits / 1e6
        method = "x402"

    analytics.track(service, method, True, tokens_used, amount_usd)




# ── Micro-tasks ─────────────────────────────────────────────────

@router.post("/api/validate-json")
async def validate_json(request: Request, body: ValidateJsonRequest):
    if not await _pre_check_credits(request, "validate-json"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    content = f"Target schema:\n{body.target_schema}\n\nData:\n{body.data}" if body.target_schema else body.data
    result, _ = await deepseek_completion(VALIDATE_JSON_PROMPT, content, json_mode=True)
    await _settle_payment(request, "validate-json")
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/classify-text")
async def classify_text(request: Request, body: ClassifyTextRequest):
    if not await _pre_check_credits(request, "classify-text"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    content = f"Categories hint: {body.categories or 'auto-detect'}\n\nText:\n{body.text}"
    result, _ = await deepseek_completion(CLASSIFY_TEXT_PROMPT, content, json_mode=True)
    await _settle_payment(request, "classify-text")
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/extract-data")
async def extract_data(request: Request, body: ExtractDataRequest):
    if not await _pre_check_credits(request, "extract-data"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, body.text, json_mode=True)
    await _settle_payment(request, "extract-data")
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/translate-code")
async def translate_code(request: Request, body: TranslateCodeRequest):
    ok, err = validate_min_price(request, 10_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    if not await _pre_check_credits(request, "translate-code"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    prompt = TRANSLATE_CODE_PROMPT.format(source_lang=body.source_lang, target_lang=body.target_lang)
    result, tokens = await cached_completion("translate-code", body.code, prompt, None, json_mode=True)
    await _settle_payment(request, "translate-code", tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/generate-regex")
async def generate_regex(request: Request, body: GenerateRegexRequest):
    if not await _pre_check_credits(request, "generate-regex"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, _ = await deepseek_completion(GENERATE_REGEX_PROMPT, body.description, json_mode=True)
    await _settle_payment(request, "generate-regex")
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/format-data")
async def format_data(request: Request, body: FormatDataRequest):
    if not await _pre_check_credits(request, "format-data"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    prompt = FORMAT_DATA_PROMPT.format(source_format=body.source_format, target_format=body.target_format)
    result, _ = await deepseek_completion(prompt, body.data, json_mode=True)
    await _settle_payment(request, "format-data")
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/summarize")
async def summarize(request: Request, body: SummarizeRequest):
    if not await _pre_check_credits(request, "summarize"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    prompt = SUMMARIZE_PROMPT.format(max_length=body.max_length)
    result, _ = await deepseek_completion(prompt, body.text, json_mode=True)
    await _settle_payment(request, "summarize")
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


# ── SQL / Dev tools ────────────────────────────────────────────

@router.post("/api/nl-to-sql")
async def nl_to_sql(request: Request, body: NlToSqlRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    if not await _pre_check_credits(request, "nl-to-sql"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, tokens = await cached_completion("nl-to-sql", body.query, NL_TO_SQL_PROMPT, None, json_mode=True)
    await _settle_payment(request, "nl-to-sql", tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/sql-to-nl")
async def sql_to_nl(request: Request, body: SqlToNlRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    if not await _pre_check_credits(request, "sql-to-nl"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, tokens = await cached_completion("sql-to-nl", body.sql, SQL_TO_NL_PROMPT, None, json_mode=True)
    await _settle_payment(request, "sql-to-nl", tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/git-summarize")
async def git_summarize(request: Request, body: GitSummarizeRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    if not await _pre_check_credits(request, "git-summarize"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, tokens = await cached_completion("git-summarize", body.diff, GIT_SUMMARIZE_PROMPT, None, json_mode=True)
    await _settle_payment(request, "git-summarize", tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


class DebugLogRequest(BaseModel):
    log: str = Field(max_length=50_000)
    context: str | None = Field(default=None, max_length=5_000)


@router.post("/api/debug-log")
async def debug_log(request: Request, body: DebugLogRequest):
    ok, err = validate_min_price(request, 3_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    if not await _pre_check_credits(request, "debug-log"):
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    content = f"Context: {body.context or 'CI/CD build failure'}\n\nError log:\n{body.log}"
    result, tokens = await cached_completion("debug-log", content, DEBUG_LOG_PROMPT, None, json_mode=True)
    await _settle_payment(request, "debug-log", tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
