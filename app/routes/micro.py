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
from app.routes import get_network, get_tx, build_upto_response
from app.pricing import round_up_cents, get_max_tokens, CREDIT_MULTIPLIER, calc_upto_cost, get_upto_caps
from app.x402_setup import settle_actual_usage, validate_min_price
from fastapi.responses import JSONResponse

router = APIRouter()

# Credit price derived from pricing.py source of truth
def _get_credit_price(service: str) -> int:
    from app.pricing import _TOOL_NAMES, AI_UPTO_SERVICES, EXACT_SERVICES
    pricing_key = _TOOL_NAMES.get(service)
    if pricing_key is None:
        return 10_000
    svc = AI_UPTO_SERVICES.get(pricing_key)
    if svc:
        return svc["base_microunits"]
    svc = EXACT_SERVICES.get(pricing_key)
    if svc:
        return svc["microunits"]
    return 10_000


def _get_max_microunits(service: str) -> int:
    """Get max microunits for a service: upto cap or exact fixed price."""
    caps = get_upto_caps(service)
    if caps:
        return caps[1]  # max_mu
    return _get_credit_price(service)  # exact fixed price


async def _pre_deduct_service(request: Request, service: str) -> int | None:
    """Atomically pre-deduct at MAX cost BEFORE AI call. Returns reserved_microunits.

    Returns None if insufficient credits. Returns 0 for x402 (no pre-deduct needed).
    Closes TOCTOU race by combining balance check + deduction under single lock.
    """
    if not hasattr(request.state, "human_api_key"):
        return 0  # x402 users validated by middleware
    max_mu = _get_max_microunits(service)
    if not credits.pre_deduct_max(request.state.human_api_key, max_mu):
        analytics.track(service, "api_key", False, 0, 0)
        return None
    return max_mu


async def _settle_payment(request: Request, service: str, reserved_mu: int, tokens_used: int = 0):
    """Settle payment AFTER successful AI call. reserved_mu was pre-deducted (0 for x402).

    For API key users: finalize_deduction refunds difference between max and actual.
    For x402 users: settle_actual_usage for the actual microunits consumed.
    Returns (microunits, multiplier, tier) for upto services, None for exact services.
    """
    is_api_key = hasattr(request.state, "human_api_key")
    multiplier = 1.0
    tier = "exact"

    if tokens_used:
        caps = get_upto_caps(service)
        if caps:
            base_mu, max_mu = caps
            actual_mu, multiplier, tier = calc_upto_cost(base_mu, tokens_used, max_mu)
        else:
            microunits = _get_credit_price(service)
            actual_mu = microunits + int((tokens_used / 1000) * 3000)  # fallback: $0.003/1K tokens
    else:
        actual_mu = _get_credit_price(service)

    if is_api_key:
        credits.finalize_deduction(request.state.human_api_key, reserved_mu, actual_mu)
        cost_cents = round_up_cents((actual_mu / 10000) * CREDIT_MULTIPLIER)
        amount_usd = cost_cents / 100
        method = "api_key"
    else:
        await settle_actual_usage(request, actual_mu)
        amount_usd = actual_mu / 1e6
        method = "x402"

    analytics.track(service, method, True, tokens_used, amount_usd)

    if tokens_used:
        return actual_mu, multiplier, tier
    return None




# ── Micro-tasks ─────────────────────────────────────────────────

@router.post("/api/validate-json")
async def validate_json(request: Request, body: ValidateJsonRequest):
    reserved = await _pre_deduct_service(request, "validate-json")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    content = f"Target schema:\n{body.target_schema}\n\nData:\n{body.data}" if body.target_schema else body.data
    result, _, _ = await deepseek_completion(VALIDATE_JSON_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("validate-json"))
    await _settle_payment(request, "validate-json", reserved)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/classify-text")
async def classify_text(request: Request, body: ClassifyTextRequest):
    reserved = await _pre_deduct_service(request, "classify-text")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    content = f"Categories hint: {body.categories or 'auto-detect'}\n\nText:\n{body.text}"
    result, _, _ = await deepseek_completion(CLASSIFY_TEXT_PROMPT, content, json_mode=True, max_tokens=get_max_tokens("classify-text"))
    await _settle_payment(request, "classify-text", reserved)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/extract-data")
async def extract_data(request: Request, body: ExtractDataRequest):
    reserved = await _pre_deduct_service(request, "extract-data")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, _, _ = await deepseek_completion(EXTRACT_DATA_PROMPT, body.text, json_mode=True, max_tokens=get_max_tokens("extract-data"))
    await _settle_payment(request, "extract-data", reserved)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/translate-code")
async def translate_code(request: Request, body: TranslateCodeRequest):
    ok, err = validate_min_price(request, 10_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    reserved = await _pre_deduct_service(request, "translate-code")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    prompt = TRANSLATE_CODE_PROMPT.replace("__SOURCE_LANG__", body.source_lang).replace("__TARGET_LANG__", body.target_lang)
    result, tokens, _ = await cached_completion("translate-code", body.code, prompt, None, json_mode=True, max_tokens=get_max_tokens("translate-code"))
    settle_result = await _settle_payment(request, "translate-code", reserved, tokens)
    if settle_result:
        microunits, multiplier, tier = settle_result
        return build_upto_response(result, request, microunits, multiplier, tier, tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/generate-regex")
async def generate_regex(request: Request, body: GenerateRegexRequest):
    reserved = await _pre_deduct_service(request, "generate-regex")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, _, _ = await deepseek_completion(GENERATE_REGEX_PROMPT, body.description, json_mode=True, max_tokens=get_max_tokens("generate-regex"))
    await _settle_payment(request, "generate-regex", reserved)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/format-data")
async def format_data(request: Request, body: FormatDataRequest):
    reserved = await _pre_deduct_service(request, "format-data")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    prompt = FORMAT_DATA_PROMPT.replace("__SOURCE_FORMAT__", body.source_format).replace("__TARGET_FORMAT__", body.target_format)
    result, _, _ = await deepseek_completion(prompt, body.data, json_mode=True, max_tokens=get_max_tokens("format-data"))
    await _settle_payment(request, "format-data", reserved)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/summarize")
async def summarize(request: Request, body: SummarizeRequest):
    reserved = await _pre_deduct_service(request, "summarize")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    max_len = body.max_length if body.max_length is not None else 100
    if "__MAX_LENGTH__" in SUMMARIZE_PROMPT:
        prompt = SUMMARIZE_PROMPT.replace("__MAX_LENGTH__", str(max_len))
    else:
        prompt = SUMMARIZE_PROMPT
    result, _, _ = await deepseek_completion(prompt, body.text, json_mode=True, max_tokens=get_max_tokens("summarize"))
    await _settle_payment(request, "summarize", reserved)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


# ── SQL / Dev tools ────────────────────────────────────────────

@router.post("/api/nl-to-sql")
async def nl_to_sql(request: Request, body: NlToSqlRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    reserved = await _pre_deduct_service(request, "nl-to-sql")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, tokens, _ = await cached_completion("nl-to-sql", body.query, NL_TO_SQL_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("nl-to-sql"))
    settle_result = await _settle_payment(request, "nl-to-sql", reserved, tokens)
    if settle_result:
        microunits, multiplier, tier = settle_result
        return build_upto_response(result, request, microunits, multiplier, tier, tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/sql-to-nl")
async def sql_to_nl(request: Request, body: SqlToNlRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    reserved = await _pre_deduct_service(request, "sql-to-nl")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, tokens, _ = await cached_completion("sql-to-nl", body.sql, SQL_TO_NL_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("sql-to-nl"))
    settle_result = await _settle_payment(request, "sql-to-nl", reserved, tokens)
    if settle_result:
        microunits, multiplier, tier = settle_result
        return build_upto_response(result, request, microunits, multiplier, tier, tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/git-summarize")
async def git_summarize(request: Request, body: GitSummarizeRequest):
    ok, err = validate_min_price(request, 5_000)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})
    reserved = await _pre_deduct_service(request, "git-summarize")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    result, tokens, _ = await cached_completion("git-summarize", body.diff, GIT_SUMMARIZE_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("git-summarize"))
    settle_result = await _settle_payment(request, "git-summarize", reserved, tokens)
    if settle_result:
        microunits, multiplier, tier = settle_result
        return build_upto_response(result, request, microunits, multiplier, tier, tokens)
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
    reserved = await _pre_deduct_service(request, "debug-log")
    if reserved is None:
        return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
    content = f"Context: {body.context or 'CI/CD build failure'}\n\nError log:\n{body.log}"
    result, tokens, _ = await cached_completion("debug-log", content, DEBUG_LOG_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("debug-log"))
    settle_result = await _settle_payment(request, "debug-log", reserved, tokens)
    if settle_result:
        microunits, multiplier, tier = settle_result
        return build_upto_response(result, request, microunits, multiplier, tier, tokens)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
