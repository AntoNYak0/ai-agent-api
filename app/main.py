from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from app.config import settings
from app.x402_setup import configure_x402
from app.routes import audit, refactor, docs, defi, trading, micro, billing, solidity_scan, stream
from app.well_known import router as well_known_router
from app.mcp_server import mcp as mcp_app
from app.services import credits, rate_limiter, analytics

app = FastAPI(
    title="AI Agent API",
    description="Paid AI services: code audit, refactoring, docs, DeFi analysis, trading, Solidity scanner, SQL tools. Payment via x402 (USDC) or API key (credits).",
    version="2.0.0",
)

# CORS — allow agents from anywhere to call MCP tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

configure_x402(
    app=app,
    pay_to_evm=settings.pay_to_address_evm,
    pay_to_solana=settings.pay_to_address_solana,
    facilitator_url=settings.facilitator_url,
    testnet=settings.testnet,
)

app.include_router(audit.router)
app.include_router(refactor.router)
app.include_router(docs.router)
app.include_router(defi.router)
app.include_router(micro.router)
app.include_router(trading.router)
app.include_router(solidity_scan.router)
app.include_router(stream.router)
app.include_router(well_known_router)
app.include_router(billing.router)

# Mount MCP server at /mcp — other AI agents connect here
app.mount("/mcp", mcp_app.sse_app())


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    stats = credits.get_stats()
    analytics_data = analytics.get_stats(1)
    rl = rate_limiter.get_stats()
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Agent API</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box }}
body {{ font:14px/1.5 -apple-system,BlinkMacSystemFont,sans-serif; background:#0d1117; color:#c9d1d9; padding:40px 20px }}
h1 {{ font-size:24px; margin-bottom:4px; color:#f0f6fc }}
p.sub {{ color:#8b949e; margin-bottom:24px }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:20px; margin-bottom:16px }}
h2 {{ font-size:16px; margin-bottom:12px; color:#f0f6fc; border-bottom:1px solid #30363d; padding-bottom:8px }}
.row {{ display:flex; gap:12px; flex-wrap:wrap }}
.stat {{ flex:1; min-width:140px; background:#0d1117; border-radius:6px; padding:14px; text-align:center }}
.stat .n {{ font-size:28px; font-weight:700; color:#58a6ff }}
.stat .l {{ font-size:11px; color:#8b949e; margin-top:2px }}
table {{ width:100%; border-collapse:collapse }}
th, td {{ text-align:left; padding:8px 12px; border-bottom:1px solid #30363d }}
th {{ color:#8b949e; font-weight:500; font-size:11px; text-transform:uppercase }}
code {{ background:#0d1117; padding:2px 6px; border-radius:4px; font-size:12px; color:#d2a8ff }}
a {{ color:#58a6ff }}
.endpoints {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:6px }}
.endpoints a {{ display:block; padding:6px 10px; background:#0d1117; border-radius:4px; text-decoration:none; font-size:12px }}
.endpoints a:hover {{ background:#1f2937 }}
</style>
</head>
<body>
<h1>AI Agent API</h1>
<p class="sub">16 pay-per-call AI services — DeepSeek V4 Pro (1M context) · x402 USDC · MCP</p>

<div class="row">
<div class="card" style="flex:2">
<h2>Stats (24h)</h2>
<div class="row">
<div class="stat"><div class="n">{analytics_data.get('total_calls', 0)}</div><div class="l">Calls</div></div>
<div class="stat"><div class="n">${analytics_data.get('total_revenue_usd', 0)}</div><div class="l">Revenue</div></div>
<div class="stat"><div class="n">{analytics_data.get('conversion_rate', 0)}%</div><div class="l">Conversion</div></div>
</div>
</div>
<div class="card" style="flex:1">
<h2>Billing</h2>
<div class="row">
<div class="stat"><div class="n">{stats.get('total_keys', 0)}</div><div class="l">API Keys</div></div>
<div class="stat"><div class="n">{stats.get('active_keys', 0)}</div><div class="l">Active</div></div>
<div class="stat"><div class="n">${stats.get('total_revenue_usd', 0)}</div><div class="l">Total Revenue</div></div>
</div>
</div>
</div>

<div class="card">
<h2>Quick Start</h2>
<code>curl http://77.239.107.30:8000/api/validate-json -H "Content-Type: application/json" -d '{{"data":"{{\\"name\\":\\"test\\"}}"}}'</code>
<p style="margin-top:8px;color:#8b949e;font-size:12px">No payment → 402 with PAYMENT-REQUIRED header. Send USDC, retry with payment-signature header.</p>
</div>

<div class="card">
<h2>Endpoints</h2>
<div class="endpoints">
<a href="/.well-known/x402">/.well-known/x402</a>
<a href="/.well-known/openapi.json">/.well-known/openapi.json</a>
<a href="/health">/health</a>
<a href="/docs">/docs (Swagger)</a>
<a href="/billing/tiers">/billing/tiers</a>
<a href="https://github.com/AntoNYak0/ai-agent-api">GitHub</a>
</div>
</div>

<p style="text-align:center;color:#8b949e;font-size:11px;margin-top:20px">
Powered by DeepSeek V4 Pro · Payments via x402 Protocol · {rl['tracked_ips']} IPs tracked · Rate limit: 10/min
</p>
</body>
</html>""")


@app.get("/health")
async def health():
    stats = credits.get_stats()
    return {
        "status": "ok",
        "testnet": settings.testnet,
        "version": "2.0.0",
        "billing": stats,
    }


@app.middleware("http")
async def human_api_key_middleware(request: Request, call_next):
    """Detect API keys in Authorization header for human developers.
    If a valid key is present, skip x402 payment and deduct credits instead.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ak-"):
        api_key = auth[7:]
        balance = credits.get_balance(api_key)
        if balance and balance["credits"] > 0:
            request.state.human_api_key = api_key
    response = await call_next(request)
    return response


@app.middleware("http")
async def cache_control_middleware(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit: 10 requests/minute per IP. Skips health/well-known paths."""
    path = request.url.path
    if path.startswith("/health") or path.startswith("/.well-known"):
        return await call_next(request)

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    ip = ip.split(",")[0].strip()

    if not rate_limiter.is_allowed(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests", "retry_after_seconds": 60},
        )

    return await call_next(request)
