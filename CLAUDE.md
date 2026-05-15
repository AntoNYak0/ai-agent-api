# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI Agent API — FastAPI + MCP server with 16 paid AI services on DeepSeek V4 Pro (1M context). Two interfaces: HTTP REST API and MCP SSE (`/mcp/sse`). Accepts USDC via x402 (DirectFacilitator with on-chain RPC verification) and API keys (credits for humans).

Deploy: `http://agent-api-ai.duckdns.org:8000` (VPS `77.239.107.30`, Ubuntu 24.04, systemd).
GitHub: `https://github.com/AntoNYak0/ai-agent-api`.

## Commands

```bash
# Local run
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Tests
pytest tests/ -v

# Deploy to VPS (SFTP via paramiko + systemctl restart)
python scripts/deploy.py

# Check status
curl http://agent-api-ai.duckdns.org:8000/health
curl http://agent-api-ai.duckdns.org:8000/
curl http://agent-api-ai.duckdns.org:8000/.well-known/x402

# Test scripts
python scripts/test_payment.py       # 9 tests: REST + API keys + replay
python scripts/test_dexter.py        # 7 tests: x402 + Dexter + manifest
python examples/client.py            # Interactive client (3 modes)
```

## Architecture

### Two interfaces (synchronized)

**REST API** (`app/routes/*.py`) — 16 FastAPI routes. English JSON prompts, `json_mode=True`, 3x retries, credit deduction for humans. Payment: x402 middleware for agents, skipped if `request.state.human_api_key`.

**MCP Server** (`app/mcp_server.py`) — 16 FastMCP tools. Same prompts, 3x retries, `json_mode=True`, replay protection, upto pricing. Primary interface for AI agents via `/mcp/sse`.

**Streaming** (`app/routes/stream.py`) — SSE endpoint `POST /api/stream/{tool}` for 5 AI services. Chunks via `text/event-stream`.

### Payment flow

```
REST:
  Human: Authorization: Bearer ak-... → API key middleware → x402 skip → handler → deduct credits
  Agent: POST /api/audit → 402 + X-Payment-Help header → pays USDC →
         retry with payment-signature: <base64-PaymentPayload> → DirectFacilitator RPC verification → handler

MCP (SSE):
  Human: audit_tool(code, api_key="ak-...") → _verify_payment → credits check → spend_credits
  Agent: audit_tool(code, payment_tx="0x...") → _verify_payment → DirectFacilitator.verify() → settle
```

### Payment-signature header

Base64-encoded JSON with `x402Version: 2`, `payload.transactionHash`, `accepted` (scheme, network, asset, amount, payTo, maxTimeoutSeconds). Format in `examples/client.py`.

### Middleware chain (main.py, reverse-order execution)

1. `rate_limit_middleware` — 10 req/min/IP, skips `/health` and `/.well-known/*`
2. `cache_control_middleware` — `Cache-Control: no-store` on `/api/*`
3. `human_api_key_middleware` — detects `Authorization: Bearer ak-...`, sets `request.state.human_api_key`
4. `x402_payment_middleware` — checks API key flag, otherwise x402; adds `X-Payment-Help` on 402

### Facilitator

**Production:** `DirectFacilitator(testnet=False, pay_to=...)` — verifies ERC-20 Transfer events via public RPCs. Client sends `transactionHash` in `payment-signature` header, facilitator reads receipt, finds Transfer event, verifies recipient + amount + token contract address.

**Testnet:** `DirectFacilitator(testnet=True)` — auto-approves without blockchain.

**TRON:** `TronFacilitator(pay_to_tron=...)` — verifies TRC-20 USDT transfers via TronGrid API. Used only by MCP tools; REST x402 middleware delegates EVM to DirectFacilitator.

Dexter (`HTTPFacilitatorClient`) is imported but NOT used — DirectFacilitator does on-chain verification directly, avoiding EIP-3009 Permit2 dependency.

### Networks

| Network | Token | Wallet | REST x402 | MCP |
|---------|-------|--------|-----------|-----|
| Base (`eip155:8453`) | USDC | `0xdE7eb...C95E` | Yes | Yes |
| Arbitrum (`eip155:42161`) | USDC | `0xdE7eb...C95E` | Well-known only | Yes |
| Optimism (`eip155:10`) | USDC | `0xdE7eb...C95E` | Well-known only | Yes |
| Tron (`tron:0x2b6653dc`) | USDT | `TADavZEH...P9wMw` | Well-known only | Yes |

Same EVM wallet address works on all EVM chains. Only Base is registered in `register_exact_evm_server` (Dexter limitation for other chains).

### Key files

| File | Role |
|------|------|
| `app/main.py` | CORS + middleware chain + routers + MCP mount + dashboard (`GET /`) + health |
| `app/x402_setup.py` | x402 config: 16 routes, prices, networks, Bazaar discovery, API key bypass, `X-Payment-Help`, attempt counter |
| `app/mcp_server.py` | FastMCP: 16 tools, verify+settle, upto logic, replay guard, credits, `TransportSecuritySettings` for domain access |
| `app/facilitator.py` | `DirectFacilitator` (EVM on-chain verification) + `TronFacilitator` (TRC-20 via TronGrid) |
| `app/well_known.py` | `/.well-known/x402` + `/.well-known/openapi.json` (16 endpoints, x402 extensions, MCP section) |
| `app/services/deepseek.py` | AsyncOpenAI → DeepSeek, 3x retries, json_mode, returns `(text, tokens)` + streaming |
| `app/services/replay_guard.py` | SHA-256 payment fingerprint with 10-min TTL |
| `app/services/credits.py` | API key system: create, top-up, spend, balance + bulk bonuses (10%/20%/30%) |
| `app/services/analytics.py` | Call stats: tool, payment_method, revenue (JSON, 10K entries, 30 days) + in-memory attempt counter |
| `app/services/rate_limiter.py` | In-memory: 10 req/min/IP, max 500 IPs |
| `app/config.py` | Pydantic Settings from `.env` |
| `app/models.py` | Pydantic request models + `ServiceResponse` |
| `app/routes/billing.py` | `/billing/create-key`, `/balance`, `/top-up`, `/stats`, `/analytics`, `/tiers` |
| `app/routes/micro.py` | 10 routes: 6 micro-tasks + translate + nl-to-sql + sql-to-nl + git-summarize |
| `app/routes/stream.py` | SSE streaming for 5 AI services |
| `scripts/deploy.py` | SFTP deploy (19 files) + systemctl restart + log check |
| `scripts/simple_pay.py` | USDC payment via web3 + API call for Bazaar indexing |

### API keys and credits

- Format: `ak-` + 32 hex
- 10 credits = $0.01 (1 credit = $0.001)
- Human price = x402 × 1.5
- Min deduction: 1 cent
- Storage: `/opt/agent-api/data/credits.json`
- Top-up: `POST /billing/top-up?key=...&amount_cents=...`

### Pricing (ultra-low, May 2026)

AI services (upto — base→max): audit $0.01–0.05, refactor $0.01–0.05, docs $0.005–0.03, defi $0.01–0.04, trading $0.005–0.03, solidity-scan $0.02–0.08, nl-to-sql $0.005–0.03, sql-to-nl $0.005–0.02, git-summarize $0.005–0.02, translate-code $0.01–0.05.

Micro-tasks (exact): validate-json $0.0005, classify-text $0.001, extract-data $0.005, generate-regex $0.002, format-data $0.003, summarize $0.002.

Token rate: $0.003/1K tokens (DeepSeek cost ~$0.0014/1K, ~2x margin).

## DuckDNS domain

- URL: `agent-api-ai.duckdns.org`
- Auto-update cron every 5 min: `curl https://www.duckdns.org/update?domains=agent-api-ai&token=...`
- MCP SSE requires `TransportSecuritySettings(enable_dns_rebinding_protection=False)` for domain access

## Deploy

VPS: `77.239.107.30`, root. Password in `scripts/deploy.py`.
- systemd: `agent-api` (auto-start, `systemctl restart agent-api`)
- Port 8000 open (ufw)
- SFTP via paramiko: `python scripts/deploy.py`
- Logs: `journalctl -u agent-api --no-pager -n 50`
- Data: `/opt/agent-api/data/` (credits.json, analytics.json)
- DuckDNS cron: `/etc/cron.d/duckdns`

## Known issues

1. **No HTTPS** — plain HTTP. Need Nginx + Let's Encrypt for production (required for mcp.so registration).
2. **No Stripe** — credits work but top-up is manual (`/billing/top-up`).
3. **mcp.so rejected** — requires HTTPS URL, DuckDNS + port 8000 not accepted.
4. **x402scan GET probes** — endpoints are POST-only, return 405 on GET. x402scan skips POST-only endpoints. Well-known manifest lists correct methods.
5. **Arbitrum/Optimism not in REST x402** — Dexter doesn't support them for `register_exact_evm_server`. Listed in well-known manifest only.
