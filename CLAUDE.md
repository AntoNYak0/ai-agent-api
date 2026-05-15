# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI Agent API — FastAPI + MCP server with 16 paid AI services on DeepSeek V4 Pro (1M context). Two interfaces: HTTP REST and MCP SSE (`/mcp/sse`). Accepts USDC via x402 (DirectFacilitator — Sovereign Mode, on-chain verification) and API keys (pre-loaded credits for humans).

Production URL: `https://agent-api-ai.duckdns.org` (VPS `77.239.107.30`, Ubuntu 24.04, systemd). HTTPS via Nginx + Let's Encrypt.

## Commands

```bash
# Local run
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Tests
pytest tests/ -v

# Deploy to VPS
# VPS: 77.239.107.30, root. Password in scripts/deploy.py or VPS_PASSWORD env.
python scripts/deploy.py

# Check status
curl https://agent-api-ai.duckdns.org/health
curl https://agent-api-ai.duckdns.org/.well-known/x402

# View VPS logs
python -c "
import paramiko; c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('77.239.107.30', username='root', password='...')
_,o,_ = c.exec_command('journalctl -u agent-api --no-pager -n 50')
print(o.read().decode(errors='replace'))
c.close()
"
```

## Architecture

### Two interfaces (synchronized)

**REST API** (`app/routes/*.py`) — 16 FastAPI POST routes. English JSON prompts, `json_mode=True`, 3x DeepSeek retries. Payment: x402 middleware for agents, API key bypass for humans.

**MCP Server** (`app/mcp_server.py`) — 16 FastMCP tools. Same prompts, same retries, replay protection, upto pricing. SSE transport at `/mcp/sse`.

### Payment flow

```
REST:
  Human:  Authorization: Bearer ak-... → api_key middleware → skip x402 → handler → deduct credits
  Agent:  POST /api/audit → 402 + X-Payment-Help → pays USDC →
          retry with payment-signature: <base64-PaymentPayload> → DirectFacilitator RPC verify →
          handler → settle_actual_usage (3 retries, 1s/2s backoff)

MCP (SSE):
  Human:  audit_tool(code, api_key="ak-...") → credits check → spend_credits
  Agent:  audit_tool(code, payment_tx="0x...") → DirectFacilitator.verify() → settle
```

### Middleware chain (main.py — FastAPI LIFO: last added = outermost = runs first)

1. `rate_limit_middleware` — 10 req/min/IP, skips `/health` and `/.well-known/*`
2. `cache_control_middleware` — `Cache-Control: no-store` on `/api/*`
3. `human_api_key_middleware` — detects `Authorization: Bearer ak-...`, sets `request.state.human_api_key`
4. `api_versioning_middleware` — rewrites `/api/v1/X` → `/api/X`, adds Deprecation header to old `/api/X` (sunset Nov 2026)
5. `x402_payment_middleware` — skips if API key present or `X402_ENABLED=false`; otherwise payment wall
6. `x402_response_header_middleware` — adds `PAYMENT-RESPONSE: true` + `X-Payment-Amount` after settlement

### Facilitator (Sovereign Mode)

`DirectFacilitator(testnet=False, pay_to=...)` — verifies ERC-20 Transfer events via public RPCs (Base, Arbitrum, Optimism). No external facilitator dependency. Client sends `transactionHash`, facilitator reads on-chain receipt, verifies recipient + amount + token contract.

`TronFacilitator(pay_to_tron=...)` — TRC-20 USDT verification via TronGrid API. MCP tools only.

**Critical limitation**: Sovereign Mode = invisible to Agentic.market (Coinbase Bazaar). Bazaar auto-indexes only CDP Facilitator services (GitHub issue x402-foundation/x402#2112).

### Key files

| File | Role |
|------|------|
| `app/main.py` | FastAPI app: CORS + 4 middleware + 10 routers + MCP mount + `/` dashboard + `/health` + `/health/deep` + `/health/metrics` + DeepSeekError 503 handler |
| `app/x402_setup.py` | x402 route configs (16 services), upto/exact pricing, `validate_min_price()` (rejects before AI), `settle_actual_usage()` (3 retries), feature flag `X402_ENABLED`, Bazaar discovery extension |
| `app/mcp_server.py` | FastMCP: 16 tools with replay guard + upto settlement |
| `app/facilitator.py` | `DirectFacilitator` (EVM on-chain) + `TronFacilitator` (TRC-20 via TronGrid) |
| `app/well_known.py` | 5 discovery endpoints: `/.well-known/x402`, `/openapi.json`, `/agent-card.json`, `/glama.json`, `/mcp/server-card.json` |
| `app/services/deepseek.py` | AsyncOpenAI → DeepSeek, 3x retries (1s/2s/4s), `DeepSeekError` on total failure, streaming support |
| `app/services/replay_guard.py` | SQLite-backed payment deduplication (30-min TTL, 100K entries, WAL mode). Survives restarts. |
| `app/services/credits.py` | API key CRUD + credit management. JSON file at `/opt/agent-api/data/credits.json`. 1 credit = $0.001 |
| `app/services/analytics.py` | Call tracking: tool, payment_method, revenue, tokens. JSON file + in-memory counters. |
| `app/services/rate_limiter.py` | In-memory: 10 req/min/IP, max 500 IPs |
| `app/config.py` | Pydantic Settings from `.env`: DeepSeek key/URL, pay_to addresses, `testnet`, `x402_enabled` |
| `app/models.py` | Pydantic request models with `Field(max_length=...)` on all strings (protects DeepSeek budget) |
| `app/routes/billing.py` | `/billing/*` — create-key, balance, top-up, stats, analytics, tiers |
| `app/routes/micro.py` | 10 routes: 6 micro-tasks (exact pricing) + 4 SQL/dev tools (upto pricing). All with minPrice check. |
| `app/routes/audit.py` | Upto route with BASE_MICROUNITS + per-token pricing + minPrice check |
| `app/routes/refactor.py`, `docs.py`, `defi.py`, `trading.py`, `solidity_scan.py` | Upto routes, same pattern |
| `app/routes/stream.py` | SSE streaming: `POST /api/stream/{tool}` for 5 AI services |
| `scripts/deploy.py` | SFTP deploy (paramiko) + systemctl restart |
| `scripts/who_visited.sh` | Visitor audit: access log, unique IPs, MCP connections, user agents, API key usage |

### Networks & Wallet

| Network | Asset | Contract | Wallet |
|---------|-------|----------|--------|
| Base (eip155:8453) | USDC | `0x833589fC...` | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Arbitrum (eip155:42161) | USDC | `0xaf88d065...` | Same |
| Optimism (eip155:10) | USDC | `0x0b2C639c...` | Same |
| Tron (tron:0x2b6653dc) | USDT | `TR7NHqje...` | `TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw` |

### Pricing (May 2026)

**Upto** (pay per actual tokens, base→max):
audit $0.01–0.05, refactor $0.01–0.05, docs $0.005–0.03, defi $0.01–0.04, trading $0.005–0.03, solidity-scan $0.02–0.08, nl-to-sql $0.005–0.03, sql-to-nl $0.005–0.02, git-summarize $0.005–0.02, translate-code $0.01–0.05.

**Exact** (flat fee):
validate-json $0.0005, classify-text $0.001, extract-data $0.005, generate-regex $0.002, format-data $0.003, summarize $0.002.

Token rate: $0.003/1K tokens (DeepSeek cost ~$0.0014/1K, ~2x margin). API key multiplier: 1.5x.

### Marketplaces

| Marketplace | Status | URL |
|-------------|--------|-----|
| mcp.so | Listed | `https://mcp.so` |
| Smithery.ai | Listed (16 tools) | `https://smithery.ai` |
| Glama.ai | Connector added | `https://glama.ai/mcp` |
| x402scan.com | `.well-known/x402` indexed, POST-only blocked | `https://x402scan.com` |
| Agentic.market | Blocked (Sovereign Mode, needs CDP) | `https://agentic.market` |

## DuckDNS

Domain `agent-api-ai.duckdns.org` resolves to `77.239.107.30`. Cron auto-update every 5 min at `/etc/cron.d/duckdns`. Token in cron file.

Some ISPs (Russian) fail to resolve DuckDNS domains. Public DNS (8.8.8.8, 1.1.1.1) works fine. Workaround: `curl --resolve agent-api-ai.duckdns.org:443:77.239.107.30 https://...`

## HTTPS

Nginx reverse proxy on ports 80→443. Let's Encrypt cert at `/etc/letsencrypt/live/agent-api-ai.duckdns.org/`. Auto-renewal via certbot.timer. Config at `/etc/nginx/sites-available/agent-api`.

Self-signed backup cert at `/etc/nginx/ssl/agent-api.crt` (expires Aug 2026).

## Production safety features

- **max_length** on all input fields (50KB code, 10KB context) — prevents budget drain
- **DeepSeekError → 503** with Retry-After: 30 header (not 500)
- **Charge AFTER success** — credits/x402 settled only after valid AI response, never on failure
- **minPrice check** — `validate_min_price()` called BEFORE DeepSeek in all upto routes; authorized amount < minimum → 402 without wasting tokens
- **ReplayGuard** — SQLite `fingerprints` table, 30-min TTL, survives restart
- **Facilitator retry** — `settle_actual_usage` retries 3x with 1s/2s backoff
- **Feature flag** — `X402_ENABLED=false` in `.env` disables payment wall, adds `X-X402-Bypassed: true` header
- **Rate limit** — 10 req/min/IP via in-memory tracker

## Deploy

- systemd: `agent-api` service, auto-start
- UFW: ports 22, 80, 443 open (8000 not exposed directly — all traffic through Nginx)
- Data: `/opt/agent-api/data/` (credits.json, analytics.json, replay.db)
- Logs: `/opt/agent-api/logs/app.log` (RotatingFileHandler, 10MB × 5 backups)
- Nginx log: `/var/log/nginx/access.log`
- SFTP deploy via paramiko: `python scripts/deploy.py`
