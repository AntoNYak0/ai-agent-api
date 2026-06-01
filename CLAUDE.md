# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Dev server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Tests
pytest tests/ -v                              # all tests
pytest tests/test_api.py -v                    # API tests only
pytest tests/test_api.py::test_audit_returns_402 -v  # single test

# Lint (matches CI)
ruff check app/ --ignore=E501,F841

# Docker
docker build -t agent-api .
docker compose up -d

# Pre-commit
pip install pre-commit && pre-commit install
pre-commit run --all-files

# Server
ssh -i ~/.ssh/id_ed25519 root@77.239.107.30
systemctl status agent-api && journalctl -u agent-api --no-pager -n 50
curl --resolve agent-api-ai.duckdns.org:443:77.239.107.30 https://agent-api-ai.duckdns.org/health

# Deploy — use deploy.py or manual scp
VPS_PASSWORD="zW8rW6eU3rgZ" python scripts/deploy.py
# Or manual:
scp app/*.py root@77.239.107.30:/opt/agent-api/app/
scp app/routes/*.py root@77.239.107.30:/opt/agent-api/app/routes/
scp app/services/*.py root@77.239.107.30:/opt/agent-api/app/services/
scp app/prompts/*.py root@77.239.107.30:/opt/agent-api/app/prompts/
ssh root@77.239.107.30 "systemctl restart agent-api"
```

## Critical: systemd overrides .env

`/etc/systemd/system/agent-api.service` sets `Environment=DEEPSEEK_API_KEY=...` — takes precedence over `/opt/agent-api/.env`. When rotating keys, update BOTH `.env` + systemd `Environment` line + `systemctl daemon-reload`.

## Architecture

**Payment:** x402 v2 (USDC via PayAI/Direct/CDP facilitators) + API key credits (1 credit = $0.001, 1.5x markup vs crypto). Token cost: $0.003/1K tokens (~2x margin over DeepSeek $0.0014/1K).

**Middleware chain (LIFO — last added runs first):**
Rate Limiter (10 req/min/IP, skips `/health`, `/.well-known`, `/billing`) → Security Headers → Cache-Control → API Key → Versioning → HEAD→GET (converts HEAD to GET for UptimeRobot) → x402 Payment

**24 REST services** in `app/routes/` (11 route modules) + **29 MCP tools** in `app/mcp_server.py` (SSE at `/mcp/sse`). **7 well-known endpoints** in `app/well_known.py` for marketplace discovery.

**Test infrastructure:** `httpx.AsyncClient` with `ASGITransport(app)` — no server spin-up needed. `conftest.py` auto-resets rate limiter before each test. CI: GitHub Actions, Python 3.11/3.12, ruff + pytest with `--timeout=60`, runs with `FACILITATOR_MODE=direct` and `TESTNET=true`.

### Route Pattern (all REST endpoints follow this)

```
1. validate_min_price() — reject before AI (fail-closed)
2. API key check — reject insufficient credits
3. cached_completion() — SHA-256 LRU cache, 10min TTL, 1000 entries
4. settle_actual_usage() (x402) or spend_credits() (API key)
5. Return ServiceResponse(result, payment_network, payment_tx)
```

Micro-tasks in `app/routes/micro.py` use `deepseek_completion()` directly (not cached — they're cheap `$0.001–$0.005` and often unique input). All 18 AI upto-services use `cached_completion()`.

### MCP Tool Pricing Flow

MCP tools pre-auth against **max** price (worst-case), then settle actual usage after AI call:
```
_verify_payment(max_price) → deepseek_completion() → _calc_upto_amount(tokens) → _settle_payment(actual)
```
Composite skills (defi-research, code-health-check, smart-contract-audit, data-pipeline) chain 2-3 AI calls, flat-priced. `run-workflow` dispatches user-registered chains with rev-share (author 85%, platform 15%).

### Cache Semantics

`cached_completion(tool, user_content, system_prompt, ...)` in `app/services/cache.py`:
- Hashes `tool + system_prompt + user_content` via SHA-256
- Cache hit → returns `(cached_result, 0)` — zero tokens, no charge
- Cache miss → calls DeepSeek, stores result, returns `(result, token_count)`
- Over capacity (1000 entries) → evicts oldest 10%
- **Use for expensive upto services** (audit, refactor, defi, solidity, etc.)
- **Don't use for micro-tasks** — input is nearly always unique, caching wastes memory

### Facilitator Modes

| Mode | Facilitator | Auth | KYC | Networks |
|------|------------|------|-----|----------|
| `payai_auth` (prod) | facilitator.payai.network | Ed25519 JWT | No | Base only |
| `payai` (test) | facilitator.payai.network | None | No | Base only |
| `direct` | EVM RPC + TronGrid | None | No | Base + Arbitrum + Optimism + Tron |
| `cdp` | Coinbase CDP | Ed25519 JWT | Yes | Base + Arbitrum + Optimism |
| `chaoschain` | facilitator.chaoscha.in | Ed25519 JWT | No | Base only |

## Key Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app, CORS, middleware chain, 14 routers, dashboard HTML, health/metrics/prices/security endpoints |
| `app/pricing.py` | **Single source of truth** — 18 AI + 6 micro service prices, 5 composite skills, networks, wallet, domain |
| `app/well_known.py` | 7 well-known endpoints: x402, openapi, server-card (Smithery), glama.json, agent-card, agentic-market-services, agent.json |
| `app/x402_setup.py` | x402 routes, facilitator setup, `validate_min_price()`, `settle_actual_usage()` |
| `app/mcp_server.py` | FastMCP SSE — 29 tools, dual auth (x402 + API key), composite skills, workflow dispatch |
| `app/config.py` | Pydantic settings from `.env`: facilitator mode, feature flags, admin key |
| `app/facilitator.py` | DirectFacilitator (EVM RPC) + TronFacilitator (TRC-20 via TronGrid) |
| `app/payai_auth.py` | PayAI Ed25519 JWT auth |
| `app/services/deepseek.py` | Async OpenAI client, 3 retries, 12 regex prompt injection sanitization, sliding window monitoring |
| `app/services/credits.py` | API key CRUD, SHA-256 hashed, atomic writes |
| `app/services/cache.py` | SHA-256 LRU cache — 10min TTL, 1000 entries, evicts oldest 10% |
| `app/services/replay_guard.py` | Payment tx dedup (in-memory + SQLite) |
| `app/services/rate_limiter.py` | 10 req/min per IP |
| `app/services/blockchain_listener.py` | Auto-top-up listener for on-chain deposits |
| `app/services/workflow_registry.py` | Composite workflow catalog — in-memory + JSON persistence, author rev-share |
| `app/services/workflow_analytics.py` | 30-day rolling execution stats |
| `app/routes/workflows.py` | Workflow CRUD — register, list, stats (execution via MCP `run-workflow` tool) |
| `app/routes/stream.py` | SSE streaming endpoint — token-by-token, credit pre-check before streaming |
| `app/prompts/` | System prompts for all AI services |
| `scripts/deploy.py` | Automated deploy via paramiko — cross-platform path support (fixed with pathlib) |
| `scripts/integration_test.py` | 29-scenario integration test suite (billing, rate-limit, 402, replay) |
| `scripts/vps_system_check.py` | VPS health diagnostics |
| `.github/workflows/ci.yml` | CI: ruff lint, bandit + pip-audit security scan, pytest + coverage, integration tests |
| `Dockerfile` | Multi-stage Docker build (python:3.12-slim) |
| `docker-compose.yml` | Dev/prod Docker Compose setup |
| `.pre-commit-config.yaml` | Pre-commit hooks: ruff, whitespace, YAML/JSON checks, private key detection |
| `tests/conftest.py` | Shared fixtures: `client` (httpx), rate limiter auto-reset |
| `SECURITY.md` | Security policy — payment, API keys, prompt injection defense, monitoring endpoints |

## Wallets

- **Receive:** `0xdE7eb04faE758055642f67f30D246CcB7136C95E` (USDC Base/Arbitrum/Optimism)
- **TRON:** `TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw`
- **Payer (PRIVATE — local only):** `scripts/.env` → `PAYER_PRIVATE_KEY`

## Known Issues

- agentic.market domain blocked — needs CDP + KYC (impossible from Russia)
- GitHub x402#2112 — DirectFacilitator invisible to indexers
