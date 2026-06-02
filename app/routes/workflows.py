"""Workflow registry routes — register, list, inspect, stats.

4 endpoints:
  GET  /api/workflows          — list all enabled workflows
  GET  /api/workflows/{id}     — get workflow details
  GET  /api/workflows/{id}/stats — execution stats (30-day rolling)
  POST /api/workflows/register  — register a new composite workflow
"""

import json as _json

from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Request, Body, Header as HeaderParam
from fastapi.responses import JSONResponse
from app.services import workflow_registry, workflow_analytics, credits
from app.pricing import AI_UPTO_SERVICES, EXACT_SERVICES
from app.errors import NotFound, Unauthorized, ValidationFailed

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Valid tool names that can appear in workflow chains.
# Union of: AI_UPTO_SERVICES keys + EXACT_SERVICES keys + COMPOSITE_SKILLS keys
_VALID_TOOLS = (
    set(AI_UPTO_SERVICES.keys())
    | set(EXACT_SERVICES.keys())
)


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic model — schema-first validation for register endpoint
# ═══════════════════════════════════════════════════════════════════════════

class WorkflowRegisterRequest(BaseModel):
    """Schema-first validation for POST /api/workflows/register."""

    name: str = Field(..., min_length=1, max_length=100, description="Workflow name")
    description: str = Field(..., min_length=1, max_length=500, description="Workflow description")
    chain: list[str] = Field(..., min_length=1, description="Ordered list of tool names")
    price_cents: int = Field(default=0, ge=0, description="Price in cents (USD)")
    platform_percent: int = Field(default=15, ge=0, le=100, description="Platform revenue share %")
    api_key: str = Field(default="", max_length=200, description="API key (or use Authorization header)")

    @field_validator("chain", mode="before")
    @classmethod
    def parse_chain(cls, v):
        """Accept both list and JSON-array string / comma-separated string."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("chain must not be empty")
            if v.startswith("["):
                try:
                    return _json.loads(v)
                except _json.JSONDecodeError:
                    pass
            # Fallback: comma-separated
            return [t.strip() for t in v.split(",") if t.strip()]
        raise ValueError("chain must be a list or string")

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_strings(cls, v):
        """Auto-strip whitespace from string fields."""
        if isinstance(v, str):
            return v.strip()
        return v


@router.get("")
async def list_workflows():
    """List all enabled workflows (public — no auth needed)."""
    workflows = workflow_registry.list_workflows()
    global_stats = workflow_analytics.get_global_stats()
    return JSONResponse({
        "workflows": workflows,
        "total": len(workflows),
        "global_stats": global_stats,
        "total_executions": workflow_registry.get_total_executions(),
    })


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get workflow details by ID."""
    wf = workflow_registry.get_workflow(workflow_id)
    if not wf:
        raise NotFound("Workflow not found")
    # Don't leak author_api_key
    return JSONResponse({
        k: v for k, v in wf.items() if k != "author_api_key"
    })


@router.get("/{workflow_id}/stats")
async def get_workflow_stats(workflow_id: str):
    """Get 30-day rolling execution stats for a workflow."""
    wf = workflow_registry.get_workflow(workflow_id)
    if not wf:
        raise NotFound("Workflow not found")
    stats = workflow_analytics.get_workflow_stats(workflow_id)
    stats["workflow_name"] = wf["name"]
    return JSONResponse(stats)


@router.post("/register")
async def register_workflow(
    request: Request,
    body: WorkflowRegisterRequest = Body(..., description="Workflow registration payload"),
    authorization: str = HeaderParam(default="", alias="Authorization", description="Bearer ak-..."),
):
    """Register a new composite workflow. Requires API key (Authorization header or body)."""
    # Resolve API key: prefer Authorization header, fallback to body field
    api_key = ""
    if authorization.startswith("Bearer ak-"):
        api_key = authorization[7:]
    elif body.api_key:
        api_key = body.api_key

    if not api_key:
        raise Unauthorized("API key required. Provide api_key in body or Authorization: Bearer ak-...")

    balance = credits.get_balance(api_key)
    if not balance:
        raise Unauthorized("Invalid API key")

    # Validate chain tools
    unknown = [t for t in body.chain if t not in _VALID_TOOLS]
    if unknown:
        raise ValidationFailed(
            f"Unknown tools: {', '.join(unknown)}. Valid: {', '.join(sorted(_VALID_TOOLS))}"
        )

    try:
        wf = workflow_registry.register_workflow(
            name=body.name,
            description=body.description,
            author_api_key=api_key,
            chain=body.chain,
            price_cents=body.price_cents,
            platform_percent=body.platform_percent,
        )
    except ValueError as e:
        raise ValidationFailed(str(e))

    price_cents = body.price_cents
    platform_percent = body.platform_percent
    author_share = price_cents * (100 - platform_percent) // 100

    return JSONResponse({
        "workflow": {k: v for k, v in wf.items() if k != "author_api_key"},
        "revenue_split": {
            "price_cents": price_cents,
            "platform_percent": platform_percent,
            "platform_cents": price_cents - author_share,
            "author_cents": author_share,
        },
    })
