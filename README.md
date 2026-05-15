# AI Agent API — 16 pay-per-call AI services via USDC

**DeepSeek V4 Pro (1M context) · x402 micropayments · MCP for AI agents · API keys for humans**

## Quick Start

```bash
# Get service manifest
curl http://agent-api-ai.duckdns.org:8000/.well-known/x402

# Get OpenAPI 3.1 spec
curl http://agent-api-ai.duckdns.org:8000/.well-known/openapi.json

# Request without payment → 402 Payment Required
curl -X POST http://agent-api-ai.duckdns.org:8000/api/validate-json \
  -H "Content-Type: application/json" \
  -d '{"data": "{\"name\": \"test\"}"}'
# → HTTP 402 + PAYMENT-REQUIRED header with price and payment details
```

## 16 Services

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

### Micro-tasks (exact pricing)

| Service | Price | Description |
|---|---|---|
| `validate-json` | $0.0005 | Validate JSON/YAML structure |
| `classify-text` | $0.001 | Sentiment, category, keywords |
| `extract-data` | $0.005 | Extract names, emails, phones, URLs |
| `generate-regex` | $0.002 | Regex from description with tests |
| `format-data` | $0.003 | Convert CSV/JSON/YAML |
| `summarize` | $0.002 | Summarize text to N words |

## Payment Methods

### x402 (AI agents)

Send USDC on Base, Arbitrum, Optimism (EVM address) or USDT on Tron. Then call with `payment_tx=<hash>`.

| Network | Token | Wallet |
|---------|-------|--------|
| Base | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Arbitrum | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Optimism | USDC | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Tron | USDT | `TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw` |

### API Keys (human developers)

```bash
# Create key
curl -X POST http://agent-api-ai.duckdns.org:8000/billing/create-key

# Check balance
curl "http://agent-api-ai.duckdns.org:8000/billing/balance?key=ak-YOUR_KEY"

# Call with key
curl -X POST http://agent-api-ai.duckdns.org:8000/api/validate-json \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ak-YOUR_KEY" \
  -d '{"data": "{\"name\": \"test\"}"}'
```

## MCP (AI Agent Connection)

AI agents connect via Model Context Protocol:

```
Endpoint: http://agent-api-ai.duckdns.org:8000/mcp/sse
```

All 16 tools available with `tool_name(code, ..., payment_tx="0x...")` (x402) or `tool_name(code, ..., api_key="ak-...")` (credits).

## Response Format

All endpoints return JSON:
```json
{
  "result": "{\"valid\": true, \"errors\": [], \"warnings\": []}",
  "payment_network": "eip155:8453",
  "payment_tx": "0x..."
}
```

## Tech Stack

- **Model**: DeepSeek V4 Pro (1M token context)
- **Protocol**: x402 v2 (Coinbase payment standard)
- **Facilitator**: DirectFacilitator (on-chain RPC verification, no external dependency)
- **Networks**: Base, Arbitrum, Optimism (USDC), Tron (USDT)
- **Framework**: FastAPI + FastMCP
- **Transport**: HTTP REST + MCP SSE
- **Domain**: DuckDNS (agent-api-ai.duckdns.org)

## Links

- [OpenAPI Spec](http://agent-api-ai.duckdns.org:8000/.well-known/openapi.json)
- [x402 Manifest](http://agent-api-ai.duckdns.org:8000/.well-known/x402)
- [Health Check](http://agent-api-ai.duckdns.org:8000/health)
- [Dashboard](http://agent-api-ai.duckdns.org:8000/)
- [GitHub](https://github.com/AntoNYak0/ai-agent-api)
