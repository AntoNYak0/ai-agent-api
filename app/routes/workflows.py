"""Workflow registry routes — register, list, inspect, stats.

4 endpoints:
  GET  /api/workflows          — list all enabled workflows
  GET  /api/workflows/{id}     — get workflow details
  GET  /api/workflows/{id}/stats — execution stats (30-day rolling)
  POST /api/workflows/register  — register a new composite workflow
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.services import workflow_registry, workflow_analytics, credits
from app.pricing import AI_UPTO_SERVICES, EXACT_SERVICES

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Valid tool names that can appear in workflow chains.
# Union of: AI_UPTO_SERVICES keys + EXACT_SERVICES keys + COMPOSITE_SKILLS keys
_VALID_TOOLS = (
    set(AI_UPTO_SERVICES.keys())
    | set(EXACT_SERVICES.keys())
)


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
        return JSONResponse(status_code=404, content={"error": "workflow not found"})
    # Don't leak author_api_key
    return JSONResponse({
        k: v for k, v in wf.items() if k != "author_api_key"
    })


@router.get("/{workflow_id}/stats")
async def get_workflow_stats(workflow_id: str):
    """Get 30-day rolling execution stats for a workflow."""
    wf = workflow_registry.get_workflow(workflow_id)
    if not wf:
        return JSONResponse(status_code=404, content={"error": "workflow not found"})
    stats = workflow_analytics.get_workflow_stats(workflow_id)
    stats["workflow_name"] = wf["name"]
    return JSONResponse(stats)


@router.post("/register")
async def register_workflow(request: Request):
    """Register a new composite workflow. Requires API key (Authorization header)."""
    import json as _json

    # Parse body — accept both JSON and form-encoded
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = {k: v for k, v in form.items()}

    api_key = body.get("api_key", "")
    if not api_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ak-"):
            api_key = auth[7:]

    if not api_key:
        return JSONResponse(status_code=401, content={"error": "API key required. Provide api_key in body or Authorization: Bearer ak-..."})

    balance = credits.get_balance(api_key)
    if not balance:
        return JSONResponse(status_code=401, content={"error": "invalid API key"})

    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    chain_raw = body.get("chain", [])
    price_cents = body.get("price_cents", 0)
    platform_percent = body.get("platform_percent", 15)

    # Validate
    if not name or len(name) > 100:
        return JSONResponse(status_code=400, content={"error": "name is required (max 100 chars)"})
    if not description or len(description) > 500:
        return JSONResponse(status_code=400, content={"error": "description is required (max 500 chars)"})
    if not chain_raw:
        return JSONResponse(status_code=400, content={"error": "chain is required (list of tool names)"})

    # Parse chain — accept JSON array string or list
    if isinstance(chain_raw, str):
        try:
            chain = _json.loads(chain_raw)
        except _json.JSONDecodeError:
            chain = [t.strip() for t in chain_raw.split(",") if t.strip()]
    else:
        chain = chain_raw

    # Validate chain tools
    unknown = [t for t in chain if t not in _VALID_TOOLS]
    if unknown:
        return JSONResponse(status_code=400, content={
            "error": f"Unknown tools: {', '.join(unknown)}",
            "valid_tools": sorted(_VALID_TOOLS),
        })

    try:
        price_cents = int(price_cents)
        platform_percent = int(platform_percent)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"error": "price_cents and platform_percent must be integers"})

    try:
        wf = workflow_registry.register_workflow(
            name=name,
            description=description,
            author_api_key=api_key,
            chain=chain,
            price_cents=price_cents,
            platform_percent=platform_percent,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

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
