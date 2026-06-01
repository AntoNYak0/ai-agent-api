# AI Agent API — 24 REST + 29 MCP AI services via USDC micropayments

[![CI](https://github.com/AntoNYak0/ai-agent-api/actions/workflows/ci.yml/badge.svg)](https://github.com/AntoNYak0/ai-agent-api/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-29-blue)](https://agent-api-ai.duckdns.org/mcp/sse)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)

**DeepSeek V4 Pro (1M context) · x402 micropayments · MCP for AI agents · API keys for humans**

## Quick Start

```bash
# Get service manifest
curl https://agent-api-ai.duckdns.org/.well-known/x402

# Get OpenAPI 3.1 spec
curl https://agent-api-ai.duckdns.org/.well-known/openapi.json

# Request without payment → 402 Payment Required
curl -X POST https://agent-api-ai.duckdns.org/api/validate-json \
  -H "Content-Type: application/json" \
  -d '{"data": "{\"name\": \"test\"}"}'
# → HTTP 402 + PAYMENT-REQUIRED header with price and payment details
```

## Docker

```bash
docker build -t agent-api .
docker compose up -d
curl http://localhost:8000/health
```

## 29 MCP Tools + 24 REST Services

### AI Services (upto pricing — pay for actual token usage)

| Service | Price | Description |
|---|---|---|
| `audit` | $0.01–$0.05 | Security scan — OWASP Top 10 + SWC Registry |
| `refactor` | $0.01–$0.05 | Legacy code modernization (DRY, SOLID) |
| `docs` | $0.005–$0.03 | Technical documentation from code |
| `defi-analyze` | $0.01–$0.04 | DeFi protocol analysis (training data only) |
| `trading-signal` | $0.005–$0.03 | Crypto market analysis (NOT financial advice) |
| `solidity-scan` | $0.02–$0.08 | Solidity vulnerability scanner (36 SWC checks) |
| `nl-to-sql` | $0.005–$0.03 | Natural language → SQL |
| `sql-to-nl` | $0.005–$0.02 | SQL → plain English |
| `translate-code` | $0.01–$0.05 | Code translation (Python, TS, Rust, Go, Solidity) |
| `git-summarize` | $0.005–$0.02 | Git diff → PR description |

### DeFi Signals (upto pricing)

| Service | Price | Description |
|---|---|---|
| `whale-tracker` | $0.015–$0.03 | Whale wallet movement tracking on Base/Arbitrum |
| `smart-money` | $0.025–$0.05 | Smart money wallet analysis — win rate, PnL patterns |
| `price-feed` | $0.01–$0.02 | AI-enhanced token price analysis with S/R levels |

### Security (upto pricing)

| Service | Price | Description |
|---|---|---|
| `agent-audit` | $0.25–$0.50 | Full AI agent security audit — code, behavior, trust score |
| `contract-verify` | $0.50–$1.00 | Smart contract formal verification — 36 SWC + DeFi exploits |
| `security-score` | $0.05–$0.10 | Rapid security assessment — quick score and risk level |

### Data & DevOps

| Service | Price | Description |
|---|---|---|
| `data-feed` | $0.01–$0.02 | Structured data feed on any topic — machine-readable JSON |
| `debug-log` | $0.01–$0.03 | CI/CD error log analysis — root cause and fix suggestions |

### Micro-tasks (exact pricing)

| Service | Price | Description |
|---|---|---|
| `validate-json` | $0.001 | Validate JSON/YAML structure |
| `classify-text` | $0.001 | Sentiment, category, keywords |
| `extract-data` | $0.005 | Extract names, emails, phones, URLs |
| `generate-regex` | $0.002 | Regex from description with tests |
| `format-data` | $0.003 | Convert CSV/JSON/YAML |
| `summarize` | $0.002 | Summarize text to N words |

## Payment Methods

### x402 (AI agents)

USDC on Base, Arbitrum, Optimism or USDT on Tron. All EVM chains use the same wallet.

| Network | Token | Wallet |
|---------|-------|--------|
| Base | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Arbitrum | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Optimism | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| BNB Chain | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Tron | USDT | `TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw` |

### API Keys (human developers)

```bash
# Create key
curl -X POST https://agent-api-ai.duckdns.org/billing/create-key

# Check balance
curl "https://agent-api-ai.duckdns.org/billing/balance?key=ak-YOUR_KEY"

# Call with key
curl -X POST https://agent-api-ai.duckdns.org/api/validate-json \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ak-YOUR_KEY" \
  -d '{"data": "{\"name\": \"test\"}"}'
```

## MCP (AI Agent Connection)

```
SSE Endpoint: https://agent-api-ai.duckdns.org/mcp/sse
```

Listed on: [Smithery.ai](https://smithery.ai/servers/antoNYak0/ai-agent-api) · [Glama.ai](https://glama.ai/mcp/servers?query=agent-api) · [mcp.so](https://mcp.so) (pending review)

## Agent Discovery

AI agents can discover this server through:

| Marketplace | Discovery | Type |
|-------------|-----------|------|
| [Smithery.ai](https://smithery.ai/servers/antoNYak0/ai-agent-api) | `smithery.yaml` + `/.well-known/mcp/server-card.json` | MCP directory |
| [Glama.ai](https://glama.ai/mcp/servers?query=agent-api) | `/.well-known/glama.json` | MCP directory |
| [mcp.so](https://mcp.so) | `mcp.json` + GitHub Issue [#2453](https://github.com/chatmcp/mcpso/issues/2453) | MCP directory |

For AI agents: read [AGENTS.md](AGENTS.md) for connection instructions.

## Response Format

```json
{
  "result": "{\"valid\": true, \"errors\": [], \"warnings\": []}",
  "payment_network": "eip155:8453",
  "payment_tx": "0x..."
}
```

## Security

- **[SECURITY.md](SECURITY.md)** — full security policy
- **`/health/security`** — real-time security status with attack detection
- **`/health/metrics`** — Prometheus metrics for rate limits, replay blocks, injection attempts
- **13 regex patterns** — prompt injection defense (jailbreak, role-switching, prompt leakage)
- **Rate limiting** — 10 req/min per IP + cumulative block counter
- **Replay protection** — SQLite-backed payment tx dedup

## Links

- [Dashboard](https://agent-api-ai.duckdns.org/)
- [Health Check](https://agent-api-ai.duckdns.org/health)
- [OpenAPI Spec](https://agent-api-ai.duckdns.org/.well-known/openapi.json)
- [x402 Manifest](https://agent-api-ai.duckdns.org/.well-known/x402)
- [GitHub](https://github.com/AntoNYak0/ai-agent-api)
