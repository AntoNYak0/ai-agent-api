# CLAUDE.md — agent-api

**Server:** `root@77.239.107.30` | **Live:** `https://agent-api-ai.duckdns.org` | **Model:** DeepSeek V4 Pro (1M ctx)

## Commands
```bash
# Dev
cd agent-api && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pytest tests/ -v

# Production
ssh -i ~/.ssh/id_ed25519 root@77.239.107.30
systemctl status agent-api && journalctl -u agent-api --no-pager -n 50
curl --resolve agent-api-ai.duckdns.org:443:77.239.107.30 https://agent-api-ai.duckdns.org/health

# Deploy (manual scp — scripts/deploy.py has path bugs, avoid it)
scp app/well_known.py root@77.239.107.30:/opt/agent-api/app/well_known.py
scp app/pricing.py root@77.239.107.30:/opt/agent-api/app/pricing.py
# ...then:
ssh root@77.239.107.30 "systemctl restart agent-api"
```

## Critical: systemd overrides .env
`/etc/systemd/system/agent-api.service` uses `WorkingDirectory=/opt/agent-api` and `Environment=DEEPSEEK_API_KEY=...` — takes precedence over `.env`. When rotating keys, update BOTH `/opt/agent-api/.env` + systemd Environment line + `daemon-reload`.

## Architecture

**Payment flow:** x402 v2 (USDC via PayAI/Direct/CDP facilitators) + API key credits (1 credit = $0.001, 1.5x markup vs crypto). Token cost: $0.003/1K tokens (~2x margin over DeepSeek $0.0014/1K).

**Middleware chain (LIFO — last added runs first):**
Rate Limiter → Security Headers → Cache-Control → API Key → Versioning → HEAD→GET → x402 Payment

Rate limiter skips `/health`, `/.well-known`, `/billing`. HEAD→GET middleware converts HEAD to GET for UptimeRobot monitors.

**24 REST services** in `app/routes/` (11 route modules) + **20 MCP tools** in `app/mcp_server.py` (SSE at `/mcp/sse`). **7 well-known endpoints** in `app/well_known.py` for marketplace discovery.

**Cache:** SHA-256 LRU, 10min TTL, 1000 entries. **Replay protection:** `app/services/replay_guard.py`.

## Key Files
| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app, CORS, middleware chain, 13 routers, dashboard HTML, health/metrics/prices endpoints |
| `app/pricing.py` | **Single source of truth** — 24 service prices, 4 composite skills, networks, wallet, domain |
| `app/well_known.py` | 7 well-known endpoints: x402, openapi, server-card (Smithery), glama.json, agent-card, agentic-market-services, agent.json (AP2) |
| `app/x402_setup.py` | x402 routes, facilitator setup, `validate_min_price()`, `settle_actual_usage()` |
| `app/mcp_server.py` | FastMCP SSE — 20 tools, dual auth (x402 crypto + API key) |
| `app/config.py` | Pydantic settings from `.env`: facilitator mode, feature flags, admin key |
| `app/facilitator.py` | DirectFacilitator (EVM RPC) + TronFacilitator (TRC-20 via TronGrid) |
| `app/payai_auth.py` | PayAI Ed25519 JWT auth |
| `app/services/deepseek.py` | Async OpenAI client, 3 retries, prompt injection sanitization (10 regex patterns) |
| `app/services/credits.py` | API key CRUD, SHA-256 hashed, atomic writes |
| `app/services/replay_guard.py` | Payment tx dedup (in-memory + SQLite) |
| `app/services/rate_limiter.py` | 10 req/min per IP |
| `app/services/blockchain_listener.py` | Auto-top-up listener for on-chain deposits |
| `app/prompts/` | System prompts for all AI services (audit, refactor, docs, defi, trading, solidity, micro, security, data_feed, defi_signals) |

## Facilitator Modes
| Mode | Facilitator | Auth | KYC | Networks |
|------|------------|------|-----|----------|
| `payai_auth` (prod) | facilitator.payai.network | Ed25519 JWT | No | Base only |
| `payai` (test) | facilitator.payai.network | None | No | Base only |
| `direct` | EVM RPC + TronGrid | None | No | Base + Arbitrum + Optimism + Tron |
| `cdp` | Coinbase CDP | Ed25519 JWT | Yes | Base + Arbitrum + Optimism |
| `chaoschain` | facilitator.chaoscha.in | Ed25519 JWT | No | Base only |

## Wallets
- **Receive:** `0xdE7eb04faE758055642f67f30D246CcB7136C95E` (USDC Base/Arbitrum/Optimism)
- **TRON:** `TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw`
- **Payer (PRIVATE — local only):** `scripts/.env` → `PAYER_PRIVATE_KEY` (`0x62fe...`)

## Route Pattern
```
1. validate_min_price() — reject before AI (fail-closed)
2. API key check — reject insufficient credits
3. deepseek_completion() / cached_completion()
4. settle_actual_usage() or spend_credits()
5. Return ServiceResponse
```

## Marketplace Files (GitHub discovery)
| File | Purpose |
|---|---|
| `smithery.yaml` | Smithery.ai auto-discovery |
| `mcp.json` | mcp.so directory listing |
| `AGENTS.md` | AI agent connection instructions (Smithery standard) |
| `SECURITY.md` | Vulnerability reporting + security practices |
| `.github/workflows/ci.yml` | CI: ruff lint + pytest (Python 3.11, 3.12) |
| `.claude/skills/setup-agent-api/SKILL.md` | Claude Code skill for one-command install |
