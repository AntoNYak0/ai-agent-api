# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI Agent API — FastAPI + MCP server with 24 paid AI services on DeepSeek V4 Pro (1M context). Two interfaces: HTTP REST (`/api/*`) and MCP SSE (`/mcp/sse`). Accepts USDC via x402 v2 (PayAI Facilitator by default — free, no KYC) and API keys (pre-loaded credits for humans).

Production: `https://agent-api-ai.duckdns.org` | VPS `77.239.107.30` (Ubuntu 24.04, systemd) | HTTPS via Nginx + Let's Encrypt.

## Commands

```bash
# Local run
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Tests (require .env with DEEPSEEK_API_KEY)
pytest tests/ -v

# Deploy to VPS (paramiko SFTP + systemctl restart)
python scripts/deploy.py

# Check production status
curl https://agent-api-ai.duckdns.org/health
curl https://agent-api-ai.duckdns.org/.well-known/x402
curl https://agent-api-ai.duckdns.org/health/deep

# Integration test (sends real requests to production)
python scripts/integration_test.py

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

**REST API** (`app/routes/*.py`) — 24 FastAPI POST routes. English JSON prompts, `json_mode=True`, 3x DeepSeek retries (1s/2s/4s). Payment: x402 middleware for agents, API key bypass for humans.

**MCP Server** (`app/mcp_server.py`) — 16 FastMCP tools + 4 composite skills. Same prompts, same retries, replay protection, upto settlement. SSE transport at `/mcp/sse`.

### Payment flow

```
REST:
  Human:  Authorization: Bearer ak-... → api_key middleware → skip x402 → handler → deduct credits
  Agent:  POST /api/audit → 402 + X-Payment-Help → pays USDC →
          retry with payment-signature: <base64-PaymentPayload> → Facilitator.verify() →
          handler → settle_actual_usage (3 retries, 1s/2s backoff)

MCP (SSE):
  Human:  audit_tool(code, api_key="ak-...") → credits check → spend_credits
  Agent:  audit_tool(code, payment_tx="0x...") → Facilitator.verify() → settle
```

### Payment safety

- **Charge AFTER success** — credits/x402 settled only after valid AI response, never on failure
- **minPrice check** — `validate_min_price()` called BEFORE DeepSeek in all upto routes; authorized amount < minimum → 402 without wasting tokens
- **ReplayGuard** — SQLite `fingerprints` table, SHA-256 hash, 30-min TTL, WAL mode, persistent connection
- **Facilitator retry** — `settle_actual_usage` retries 3x with 1s/2s backoff
- **Atomic writes** — `credits.json` uses `tempfile + os.replace` to prevent corruption
- **max_length** on all input fields (50KB code, 10KB context) — prevents budget drain
- **DeepSeekError → 503** with `Retry-After: 30` header (not 500)

### Middleware chain (FastAPI LIFO — last added = outermost = runs first)

Execution order (outermost → innermost):

1. `rate_limit_middleware` — 10 req/min/IP, skips `/health` and `/.well-known/*`
2. `cache_control_middleware` — `Cache-Control: no-store` on `/api/*`
3. `human_api_key_middleware` — detects `Authorization: Bearer ak-...`, sets `request.state.human_api_key`
4. `api_versioning_middleware` — rewrites `/api/v1/X` → `/api/X`, adds Deprecation header to old `/api/X` (sunset Nov 2026)
5. `head_to_get_middleware` — converts HEAD to GET for `/health`, `/.well-known/*`, `/` (UptimeRobot fix)
6. `x402_response_header_middleware` — adds `PAYMENT-RESPONSE: true` + `X-Payment-Amount` after settlement
7. `x402_payment_middleware` — skips if API key present or `X402_ENABLED=false`; otherwise payment wall

### Facilitator (3 modes)

Configured via `FACILITATOR_MODE` in `.env`:

| Mode | Facilitator | Auth | KYC | agentic.market |
|------|------------|------|-----|----------------|
| `payai` (default) | `https://facilitator.payai.network` | None | No | No |
| `direct` | `DirectFacilitator` (EVM RPC) + `TronFacilitator` (TronGrid) | None | No | No |
| `cdp` | `https://api.cdp.coinbase.com/platform/v2/x402` | Ed25519 JWT | **Yes** | Yes (when fixed) |

**PayAI** — recommended default. Free, no KYC, no auth, multi-chain (Base, Arbitrum, Optimism, Solana, Polygon, Avalanche). Uses `HTTPFacilitatorClient` with no auth provider.

**DirectFacilitator** — Sovereign Mode. Verifies ERC-20 Transfer events via public RPCs. No external dependency. `TronFacilitator` handles TRC-20 USDT via TronGrid API. MCP tools only.

**CDP Facilitator** — required for agentic.market listing. Needs Coinbase account + KYC (impossible from Russia). Uses `app/cdp_auth.py` for Ed25519 JWT generation per request.

**Critical limitation**: agentic.market ONLY indexes through CDP Facilitator. Even CDP users are blocked by Bazaar bug (GitHub issue x402-foundation/x402#2112). PayAI and Direct modes are invisible to agentic.market.

### Key files

| File | Role |
|------|------|
| `app/main.py` | FastAPI app: CORS + 7 middleware + 14 routers + MCP mount + `/` dashboard + `/health` + `/health/deep` + `/health/metrics` + `/api/prices` + `/docs/examples` + DeepSeekError 503 handler + blockchain listener startup |
| `app/pricing.py` | **Single source of truth** for all 24 service definitions, networks, wallet, composite skills. Imported by routes, x402_setup, mcp_server, well_known. |
| `app/x402_setup.py` | x402 route configs (24 services), upto/exact pricing, `validate_min_price()` (rejects before AI), `settle_actual_usage()` (3 retries), feature flag `X402_ENABLED`, Bazaar discovery extension |
| `app/mcp_server.py` | FastMCP: 16 tools + 4 composite skills with replay guard + upto settlement |
| `app/facilitator.py` | `DirectFacilitator` (EVM on-chain) + `TronFacilitator` (TRC-20 via TronGrid) |
| `app/well_known.py` | 5 discovery endpoints: `/.well-known/x402`, `/openapi.json`, `/agent-card.json`, `/glama.json`, `/mcp/server-card.json` |
| `app/config.py` | Pydantic Settings from `.env`: DeepSeek, pay_to addresses, `facilitator_mode` (payai/direct/cdp), `cdp_api_key_id/secret`, testnet, x402_enabled |
| `app/cdp_auth.py` | CDP JWT auth provider — generates Ed25519-signed JWTs per facilitator endpoint. Only used when `facilitator_mode=cdp`. |
| `app/models.py` | Pydantic request models with `Field(max_length=...)` on all strings |
| `app/routes/__init__.py` | Shared helpers: `get_network(request)` and `get_tx(request)` — used by all route files |
| `app/routes/micro.py` | 10 routes: 7 micro-tasks (exact pricing) + 3 SQL/dev tools (upto pricing). Uses `_deduct_and_track()` pattern. |
| `app/routes/security.py` | 3 endpoints: agent-audit ($0.50), contract-verify ($1.00), security-score ($0.10) |
| `app/routes/defi_signals.py` | 3 endpoints: whale-tracker ($0.03), smart-money ($0.05), price-feed ($0.02) |
| `app/routes/data_feed.py` | data-feed ($0.02) — structured JSON feeds from training data |
| `app/routes/audit.py`, `refactor.py`, `docs.py`, `defi.py`, `trading.py`, `solidity_scan.py` | Upto routes, same pattern: validate_min_price → cached_completion → settle/spend |
| `app/routes/stream.py` | SSE streaming: `POST /api/stream/{tool}` for 5 AI services |
| `app/routes/billing.py` | `/billing/*` — create-key, balance, top-up, stats, analytics, tiers, register-wallet |
| `app/services/deepseek.py` | AsyncOpenAI → DeepSeek, 3x retries (1s/2s/4s), `DeepSeekError` on total failure, streaming support |
| `app/services/cache.py` | In-memory response cache: SHA-256 hash of tool+content, 10-min TTL, 1000 max entries, LRU eviction |
| `app/services/replay_guard.py` | SQLite payment deduplication (30-min TTL, 100K entries, WAL mode, persistent connection) |
| `app/services/credits.py` | API key CRUD + credit management. JSON at `/opt/agent-api/data/credits.json`. 1 credit = $0.001. Atomic writes. |
| `app/services/blockchain_listener.py` | Background asyncio task — polls eth_getLogs for USDC Transfer events, auto-top-ups API keys when wallet receives funds |
| `app/services/analytics.py` | Call tracking: tool, payment_method, revenue, tokens. JSON + in-memory counters. |
| `app/services/rate_limiter.py` | In-memory: 10 req/min/IP, max 500 IPs |
| `app/prompts/*.py` | All 24 prompts in standardized format: ROLE → TASK → FOCUS → OUTPUT_SCHEMA → RULES → EXAMPLE |

### Networks & Wallet

| Network | Asset | Contract | Wallet |
|---------|-------|----------|--------|
| Base (eip155:8453) | USDC | `0x833589fC...` | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Arbitrum (eip155:42161) | USDC | `0xaf88d065...` | Same |
| Optimism (eip155:10) | USDC | `0x0b2C639c...` | Same |
| Tron (tron:0x2b6653dc) | USDT | `TR7NHqje...` | `TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw` |

### Pricing (May 2026)

Token rate: $0.003/1K tokens (DeepSeek cost ~$0.0014/1K, ~2x margin). API key multiplier: 1.5x.

**Upto** (pay per actual tokens, base→max):
audit $0.01–0.05, refactor $0.01–0.05, docs $0.005–0.03, defi-analyze $0.01–0.04, trading-signal $0.005–0.03, solidity-scan $0.02–0.08, nl-to-sql $0.005–0.03, sql-to-nl $0.005–0.02, git-summarize $0.005–0.02, translate-code $0.01–0.05, whale-tracker $0.015–0.03, smart-money $0.025–0.05, price-feed $0.01–0.02, agent-audit $0.25–0.50, contract-verify $0.50–1.00, security-score $0.05–0.10, data-feed $0.01–0.02, debug-log $0.03 (exact in pricing.py, upto in x402_setup.py — check before changing).

**Exact** (flat fee):
validate-json $0.0005, classify-text $0.001, extract-data $0.005, generate-regex $0.002, format-data $0.003, summarize $0.002.

**Composite skills** (MCP only): defi-research $0.08, code-health-check $0.10, smart-contract-audit $0.10, data-pipeline $0.05.

### Marketplaces

| Marketplace | Status |
|-------------|--------|
| mcp.so | Listed |
| Smithery.ai | Listed (16 tools) |
| Glama.ai | Connector added |
| x402scan.com | `.well-known/x402` indexed, POST-only blocked |
| AgenticTrade | 16 services active |
| Agentic.market | Blocked (needs CDP Facilitator + Coinbase KYC — impossible from Russia) |
| the402.ai | Pending registration ($0.01 USDC fee, needs funded payer wallet) |

## DuckDNS

Domain `agent-api-ai.duckdns.org` → `77.239.107.30`. Cron auto-update every 5 min. Some ISPs (Russian) fail to resolve DuckDNS — workaround: `curl --resolve agent-api-ai.duckdns.org:443:77.239.107.30 https://...`

## Wallets

**Receiving wallet** (public, safe to deploy): `0xdE7eb04faE758055642f67f30D246CcB7136C95E` — revenue lands here.

**Payer wallet** (PRIVATE KEY — never deploy to VPS): stored locally in `scripts/.env` as `PAYER_PRIVATE_KEY`. Used for outgoing x402 payments (the402.ai registration, testing). The previous payer key `0xde54...` was compromised on May 15, 2026 — $4.16 USDC stolen. Current key: `0x62fe...` (May 2026). Keep only on local machine, never commit or deploy.

## Deploy

- systemd: `agent-api` service, auto-start
- UFW: ports 22, 80, 443 open (8000 not exposed — all traffic through Nginx)
- Data: `/opt/agent-api/data/` (credits.json, analytics.json, replay.db)
- Logs: `/opt/agent-api/logs/app.log` (RotatingFileHandler, 10MB × 5 backups)
- Nginx: `/etc/nginx/sites-available/agent-api`, Let's Encrypt auto-renewal via certbot.timer
- SFTP deploy: `python scripts/deploy.py`

## Route pattern (when adding new endpoints)

Every upto route follows this exact pattern:
1. `validate_min_price(request, MIN_PRICE_MICROUNITS)` — reject underpayment before AI
2. `cached_completion(tool, user_content, system_prompt, context, json_mode=True)` — cache-aware AI call
3. On success: `settle_actual_usage(request, actual_microunits)` for x402 OR `credits.spend_credits(key, cents)` for API keys
4. Return JSON with `payment_network` and `payment_tx` from `get_network(request)` / `get_tx(request)`

Pricing constants (`PER_1K_TOKENS_MICROUNITS`, `round_up_cents()`) come from `app.pricing`.
