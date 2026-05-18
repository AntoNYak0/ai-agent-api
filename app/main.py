from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from app.config import settings
from app.x402_setup import configure_x402
from app.routes import audit, refactor, docs, defi, trading, micro, billing, solidity_scan, stream, defi_signals, security, data_feed
from app.well_known import router as well_known_router
from app.mcp_server import mcp as mcp_app
from app.pricing import ALL_SERVICES, COMPOSITE_SKILLS, NETWORKS, WALLET
from app.services import credits, rate_limiter, analytics

# ---------------------------------------------------------------------------
# File logging — production: /opt/agent-api/logs/app.log  (10 MB rotated, 5 backups)
#               local dev:   ./logs/app.log
# ---------------------------------------------------------------------------
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "/opt/agent-api/logs"
_log_dir_fallback = "./logs"

if os.path.exists("/opt/agent-api"):
    os.makedirs(LOG_DIR, exist_ok=True)
    _handler = RotatingFileHandler(
        f"{LOG_DIR}/app.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
else:
    os.makedirs(_log_dir_fallback, exist_ok=True)
    _handler = RotatingFileHandler(
        f"{_log_dir_fallback}/app.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )

_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("uvicorn.access").addHandler(_handler)

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
    pay_to_tron=settings.pay_to_address_tron,
    testnet=settings.testnet,
)

@app.middleware("http")
async def head_to_get_middleware(request: Request, call_next):
    """UptimeRobot and other monitors use HEAD — convert to GET for health/well-known."""
    if request.method == "HEAD" and (
        request.url.path.startswith("/health") or
        request.url.path.startswith("/.well-known") or
        request.url.path == "/"
    ):
        request.scope["method"] = "GET"
        response = await call_next(request)
        response.headers["X-HEAD-Converted"] = "GET"
        return response
    return await call_next(request)


@app.middleware("http")
async def api_versioning_middleware(request: Request, call_next):
    """Route /api/v1/X to /api/X internally.
    Registered AFTER configure_x402 so it runs BEFORE x402_payment_middleware
    (FastAPI middleware is LIFO — last added = outermost = runs first)."""
    path = request.scope.get("path", "")
    is_v1 = path.startswith("/api/v1/")
    if is_v1:
        request.scope["path"] = path.replace("/api/v1/", "/api/", 1)

    response = await call_next(request)

    if path.startswith("/api/") and not is_v1 and response.status_code < 400:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "Sat, 01 Nov 2026 00:00:00 GMT"
        response.headers["X-API-Version"] = "use /api/v1/ instead"
    return response

from app.services.deepseek import DeepSeekError


@app.exception_handler(DeepSeekError)
async def deepseek_error_handler(request: Request, exc: DeepSeekError):
    """Return 503 when AI backend is down — don't leak stack traces."""
    logging.getLogger("main").error("DeepSeek unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "error": "service_unavailable",
            "message": "AI backend is temporarily unavailable. Please retry in a few seconds.",
            "retry_after_seconds": 30,
        },
        headers={"Retry-After": "30"},
    )

app.include_router(audit.router)
app.include_router(refactor.router)
app.include_router(docs.router)
app.include_router(defi.router)
app.include_router(micro.router)
app.include_router(trading.router)
app.include_router(solidity_scan.router)
app.include_router(defi_signals.router)
app.include_router(security.router)
app.include_router(data_feed.router)
app.include_router(stream.router)
app.include_router(well_known_router)
app.include_router(billing.router)

# Start blockchain listener for auto-top-up on startup
@app.on_event("startup")
async def startup_blockchain_listener():
    import asyncio
    from app.services.blockchain_listener import start_listener
    asyncio.create_task(start_listener())

# Mount MCP server at /mcp — other AI agents connect here
app.mount("/mcp", mcp_app.sse_app())


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    stats = credits.get_stats()
    analytics_data = analytics.get_stats(1)
    attempts_data = analytics.get_attempts()
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
<div class="stat"><div class="n">{attempts_data.get('total_attempts', 0)}</div><div class="l">402 Attempts</div></div>
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
<h2>Quick Start — Free Trial</h2>
<code>curl https://agent-api-ai.duckdns.org/api/validate-json -H "Content-Type: application/json" -d '{{"data":"{{\\"name\\":\\"test\\"}}"}}'</code>
<p style="margin-top:8px;color:#3fb950;font-size:12px">validate-json is FREE — no payment needed. All other endpoints require x402 USDC or API key.</p>
</div>

<div class="card">
<h2>Get API Key — Pay with Crypto</h2>
<p style="color:#8b949e;margin-bottom:12px">Send USDC to the address below, then contact to top up your key. 1 credit = $0.001.</p>
<div style="background:#0d1117;border-radius:6px;padding:14px;margin-bottom:12px;display:flex;align-items:center;gap:14px">
<div style="flex:1">
<div style="font-size:12px;color:#8b949e;margin-bottom:4px">USDC (Base / Arbitrum / Optimism)</div>
<code style="font-size:13px;word-break:break-all">0xdE7eb04faE758055642f67f30D246CcB7136C95E</code>
</div>
<img src="https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=0xdE7eb04faE758055642f67f30D246CcB7136C95E" width="60" height="60" style="border-radius:4px" alt="USDC QR">
</div>
<div style="background:#0d1117;border-radius:6px;padding:14px;margin-bottom:12px;display:flex;align-items:center;gap:14px">
<div style="flex:1">
<div style="font-size:12px;color:#8b949e;margin-bottom:4px">USDT (Tron TRC-20)</div>
<code style="font-size:13px;word-break:break-all">TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw</code>
</div>
<img src="https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw" width="60" height="60" style="border-radius:4px" alt="USDT QR">
</div>
<table>
<tr><th>Tier</th><th>Price</th><th>Credits</th><th>Bonus</th></tr>
<tr><td>Starter</td><td>$10</td><td>10,000</td><td>—</td></tr>
<tr><td>Pro</td><td>$45</td><td>50,000</td><td>10% extra</td></tr>
<tr><td>Scale</td><td>$80</td><td>100,000</td><td>20% extra</td></tr>
</table>
<p style="margin-top:8px;color:#8b949e;font-size:12px"><a href="/billing/create-key" style="color:#58a6ff">Create free trial key</a> (1000 credits, no payment required).</p>
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


@app.get("/favicon.svg")
async def favicon():
    return HTMLResponse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<circle cx="16" cy="16" r="15" fill="#2563eb"/>'
        '<text x="16" y="22" text-anchor="middle" fill="white" font-size="18" font-weight="bold" font-family="Arial">AI</text>'
        '</svg>',
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/prices")
async def api_prices():
    """Return structured pricing for all services — machine-readable for agents."""
    services = []
    for key, svc in sorted(ALL_SERVICES.items()):
        method, path = key.split(" ", 1)
        services.append({
            "path": path,
            "method": method,
            "description": svc["description"],
            "price": svc.get("max_price", svc.get("price")),
            "scheme": "upto" if "max_price" in svc else "exact",
        })

    skills = []
    for name, skill in COMPOSITE_SKILLS.items():
        skills.append({
            "name": name,
            "description": skill["description"],
            "price": skill["price"],
            "chain": skill["chain"],
        })

    return JSONResponse({
        "service": "AI Agent API",
        "version": "2.0.0",
        "payment": {
            "protocol": "x402",
            "version": 2,
            "wallet": WALLET,
            "networks": NETWORKS,
        },
        "services": services,
        "composite_skills": skills,
    })


@app.get("/docs/examples", response_class=HTMLResponse)
async def docs_examples():
    """Human-friendly API examples page — curl snippets for every endpoint."""

    rows = []
    for key, svc in sorted(ALL_SERVICES.items()):
        method, path = key.split(" ", 1)
        name = path.replace("/api/", "")
        price = svc.get("max_price", svc.get("price"))
        body_fields = svc.get("input", {})
        body_json = ", ".join(f'"{k}": "..."' for k in body_fields)

        rows.append(f"""<div class="endpoint-card">
<div class="ep-head"><span class="method">POST</span> <code class="ep-path">{path}</code> <span class="ep-price">{price}</span></div>
<div class="ep-desc">{svc["description"]}</div>
<div class="ep-example">
<pre>curl -X POST https://agent-api-ai.duckdns.org{path} \\
  -H "Content-Type: application/json" \\
  -d '{{ {body_json} }}'
# → HTTP 402 Payment Required</pre>
<pre># With API key (credits):
curl -X POST https://agent-api-ai.duckdns.org{path} \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ak-YOUR_KEY" \\
  -d '{{ {body_json} }}'
# → HTTP 200 (JSON result)</pre>
</div></div>""")

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API Examples — AI Agent API</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box }}
body {{ font:14px/1.5 -apple-system,BlinkMacSystemFont,sans-serif; background:#0d1117; color:#c9d1d9; padding:40px 20px }}
h1 {{ font-size:24px; margin-bottom:4px; color:#f0f6fc }}
p.sub {{ color:#8b949e; margin-bottom:24px }}
.note {{ background:#1a3a2a; border:1px solid #2ea043; border-radius:8px; padding:12px 16px; margin-bottom:24px; color:#3fb950 }}
.endpoint-card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:20px; margin-bottom:12px }}
.ep-head {{ margin-bottom:8px; display:flex; align-items:center; gap:10px; flex-wrap:wrap }}
.method {{ background:#2ea043; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:600 }}
.ep-path {{ font-size:15px; color:#d2a8ff }}
.ep-price {{ background:#0d1117; color:#58a6ff; padding:2px 8px; border-radius:4px; font-size:12px }}
.ep-desc {{ color:#8b949e; margin-bottom:10px; font-size:13px }}
.ep-example pre {{ background:#0d1117; padding:10px 14px; border-radius:4px; font-size:12px; margin-bottom:6px; overflow-x:auto; color:#c9d1d9 }}
a {{ color:#58a6ff }}
</style></head>
<body>
<h1>API Examples</h1>
<p class="sub">Copy-paste curl snippets for all 19 endpoints. <a href="/">Dashboard</a> · <a href="/docs">Swagger</a></p>
<div class="note"><strong>All endpoints require payment.</strong> No free tier. Pay with x402 (USDC) or API key (credits). <a href="/billing/create-key">Create a key</a>.</div>
{''.join(rows)}
<p style="text-align:center;color:#8b949e;font-size:11px;margin-top:30px">19 endpoints · Powered by DeepSeek V4 Pro · <a href="https://github.com/AntoNYak0/ai-agent-api">GitHub</a></p>
</body></html>""")


@app.get("/health")
async def health():
    stats = credits.get_stats()
    attempts = analytics.get_attempts()
    return {
        "status": "ok",
        "testnet": settings.testnet,
        "version": "2.0.0",
        "billing": stats,
        "payment_attempts": attempts["total_attempts"],
    }


@app.get("/health/deep")
async def health_deep():
    """Deep health check — verifies ALL dependencies (DeepSeek, billing, RPCs)."""
    import time

    from app.services.deepseek import deepseek_completion

    import httpx

    results: dict = {"status": "ok", "checks": {}}

    # DeepSeek API
    t0 = time.time()
    try:
        await deepseek_completion(
            system_prompt="",
            user_content="pong",
            json_mode=False,
        )
        results["checks"]["deepseek"] = {
            "status": "ok",
            "latency_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        results["checks"]["deepseek"] = {"status": "error", "message": str(e)[:200]}
        results["status"] = "degraded"

    # Billing storage
    try:
        stats = credits.get_stats()
        results["checks"]["billing"] = {
            "status": "ok",
            "total_keys": stats.get("total_keys", 0),
        }
    except Exception as e:
        results["checks"]["billing"] = {"status": "error", "message": str(e)[:200]}
        results["status"] = "degraded"

    # Chain RPC health (internal — no URLs exposed)
    rpcs = {
        "base": "https://mainnet.base.org",
        "arbitrum": "https://arb1.arbitrum.io/rpc",
        "optimism": "https://mainnet.optimism.io",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        for chain, rpc_url in rpcs.items():
            t0 = time.time()
            try:
                r = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "eth_blockNumber",
                        "params": [],
                        "id": 1,
                    },
                )
                if r.status_code == 200:
                    results["checks"][f"chain_{chain}"] = {
                        "status": "ok",
                        "latency_ms": round((time.time() - t0) * 1000),
                    }
                else:
                    results["checks"][f"chain_{chain}"] = {
                        "status": "error",
                    }
                    results["status"] = "degraded"
            except Exception:
                results["checks"][f"chain_{chain}"] = {
                    "status": "error",
                }
                results["status"] = "degraded"

    # Override: if deepseek is down, it's degraded (even if RPCs are fine)
    return results


@app.get("/health/metrics")
async def health_metrics():
    """Prometheus-compatible metrics endpoint."""
    from collections import Counter

    stats = analytics.get_stats(1)
    attempts = analytics.get_attempts()
    rl = rate_limiter.get_stats()

    lines = [
        "# HELP api_calls_total Total API calls (24h)",
        "# TYPE api_calls_total counter",
        f"api_calls_total {stats.get('total_calls', 0)}",
        "# HELP api_revenue_usd_total Revenue in USD (24h)",
        "# TYPE api_revenue_usd_total counter",
        f"api_revenue_usd_total {stats.get('total_revenue_usd', 0)}",
        "# HELP api_errors_total Error responses (24h)",
        "# TYPE api_errors_total counter",
        f"api_errors_total {stats.get('errors', 0)}",
        "# HELP api_conversion_rate Conversion rate percent",
        "# TYPE api_conversion_rate gauge",
        f"api_conversion_rate {stats.get('conversion_rate', 0)}",
        "# HELP api_payment_attempts_total 402 attempts since restart",
        "# TYPE api_payment_attempts_total counter",
        f"api_payment_attempts_total {attempts.get('total_attempts', 0)}",
        "# HELP api_rate_limited_ips Tracked IPs",
        "# TYPE api_rate_limited_ips gauge",
        f"api_rate_limited_ips {rl.get('tracked_ips', 0)}",
        "# HELP api_active_keys Active API keys",
        "# TYPE api_active_keys gauge",
        f"api_active_keys {credits.get_stats().get('active_keys', 0)}",
    ]

    # Per-tool breakdown
    by_tool = stats.get("by_tool", {})
    lines.append(f"# HELP api_calls_by_tool Calls per tool (24h)")
    lines.append(f"# TYPE api_calls_by_tool gauge")
    for tool, count in by_tool.items():
        lines.append(f'api_calls_by_tool{{tool="{tool}"}} {count}')

    lines.append("")
    return JSONResponse(content="\n".join(lines), media_type="text/plain; charset=utf-8")


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
        logging.warning("Rate limit hit — IP: %s, path: %s", ip, path)
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests", "retry_after_seconds": 60},
        )

    logging.debug("Request allowed — IP: %s, path: %s, method: %s", ip, path, request.method)
    return await call_next(request)
