"""Security audit routes — agent audit, contract verification, security scoring."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import BaseModel, Field, ServiceResponse
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.pricing import round_up_cents, get_max_tokens, PER_1K_TOKENS_MICROUNITS
from app.prompts.security import AGENT_AUDIT_PROMPT, CONTRACT_VERIFY_PROMPT, SECURITY_SCORE_PROMPT
from app.x402_setup import settle_actual_usage, validate_min_price

router = APIRouter()
CREDIT_MULTIPLIER = 1.5

# Pricing: upto with base + per-token (premium pricing for security services)
AGENT_AUDIT_BASE = 250_000   # $0.25 base
AGENT_AUDIT_MIN = 125_000    # $0.125 min authorized
CONTRACT_VERIFY_BASE = 500_000  # $0.50 base
CONTRACT_VERIFY_MIN = 250_000   # $0.25 min authorized
SECURITY_SCORE_BASE = 50_000    # $0.05 base
SECURITY_SCORE_MIN = 25_000     # $0.025 min authorized


class AgentAuditRequest(BaseModel):
    agent_code: str = Field(max_length=50_000)
    behavior_description: str | None = Field(default=None, max_length=10_000)
    agent_name: str | None = Field(default=None, max_length=1_000)


class ContractVerifyRequest(BaseModel):
    contract_code: str = Field(max_length=50_000)
    contract_name: str | None = Field(default=None, max_length=1_000)
    network: str | None = Field(default=None, max_length=200)


class SecurityScoreRequest(BaseModel):
    code: str = Field(max_length=50_000)
    description: str | None = Field(default=None, max_length=5_000)


@router.post("/api/agent-audit")
async def agent_audit(request: Request, body: AgentAuditRequest):
    ok, err = validate_min_price(request, AGENT_AUDIT_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        cost_cents = round_up_cents((AGENT_AUDIT_BASE / 10000) * CREDIT_MULTIPLIER)
        balance = credits.get_balance(request.state.human_api_key)
        if not balance or (balance["credits"] / 10) < cost_cents:
            analytics.track("agent-audit", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    content = f"Agent: {body.agent_name or 'unnamed'}\nBehavior: {body.behavior_description or 'not provided'}\n\nCode:\n{body.agent_code}"
    result, tokens = await cached_completion("agent-audit", content, AGENT_AUDIT_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("agent-audit"))

    microunits = AGENT_AUDIT_BASE + int((tokens / 1000) * PER_1K_TOKENS_MICROUNITS)
    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("agent-audit", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("agent-audit", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/contract-verify")
async def contract_verify(request: Request, body: ContractVerifyRequest):
    ok, err = validate_min_price(request, CONTRACT_VERIFY_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        cost_cents = round_up_cents((CONTRACT_VERIFY_BASE / 10000) * CREDIT_MULTIPLIER)
        balance = credits.get_balance(request.state.human_api_key)
        if not balance or (balance["credits"] / 10) < cost_cents:
            analytics.track("contract-verify", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    content = f"Contract: {body.contract_name or 'unnamed'}\nNetwork: {body.network or 'ethereum'}\n\nCode:\n{body.contract_code}"
    result, tokens = await cached_completion("contract-verify", content, CONTRACT_VERIFY_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("contract-verify"))

    microunits = CONTRACT_VERIFY_BASE + int((tokens / 1000) * PER_1K_TOKENS_MICROUNITS)
    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("contract-verify", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("contract-verify", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/security-score")
async def security_score(request: Request, body: SecurityScoreRequest):
    ok, err = validate_min_price(request, SECURITY_SCORE_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        cost_cents = round_up_cents((SECURITY_SCORE_BASE / 10000) * CREDIT_MULTIPLIER)
        balance = credits.get_balance(request.state.human_api_key)
        if not balance or (balance["credits"] / 10) < cost_cents:
            analytics.track("security-score", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    content = f"Code:\n{body.code}\n\nDescription: {body.description or 'not provided'}"
    result, tokens = await cached_completion("security-score", content, SECURITY_SCORE_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("security-score"))

    microunits = SECURITY_SCORE_BASE + int((tokens / 1000) * PER_1K_TOKENS_MICROUNITS)
    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("security-score", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("security-score", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
