# AI Agent API — 16 pay-per-call AI services via USDC

**DeepSeek V4 Pro (1M context) · x402 micropayments · MCP for AI agents · API keys for humans**

## Quick Start

```bash
# Get service manifest
curl http://77.239.107.30:8000/.well-known/x402

# Get OpenAPI 3.1 spec
curl http://77.239.107.30:8000/.well-known/openapi.json

# Request without payment → 402 Payment Required
curl -X POST http://77.239.107.30:8000/api/validate-json \
  -H "Content-Type: application/json" \
  -d '{"data": "{\"name\": \"test\"}"}'

# → HTTP 402 + PAYMENT-REQUIRED header with price and payment details
```

## 16 Services

### AI Services (upto pricing — pay for actual usage)

| Service | Price | Description |
|---|---|---|
| `audit` | $0.02–$0.10 | Security scan — OWASP Top 10 + SWC Registry |
| `refactor` | $0.03–$0.16 | Legacy code modernization (DRY, SOLID) |
| `docs` | $0.01–$0.06 | Technical documentation from code |
| `defi-analyze` | $0.02–$0.08 | DeFi protocol analysis (training data only) |
| `trading-signal` | $0.01–$0.06 | Crypto market analysis (NOT financial advice) |
| `solidity-scan` | $0.04–$0.20 | Solidity vulnerability scanner (36 SWC checks) |
| `nl-to-sql` | $0.01–$0.06 | Natural language → SQL |
| `sql-to-nl` | $0.01–$0.04 | SQL → plain English |
| `translate-code` | $0.02–$0.10 | Code translation (Python, TS, Rust, Go, Solidity) |
| `git-summarize` | $0.01–$0.04 | Git diff → PR description |

### Micro-tasks (exact pricing)

| Service | Price | Description |
|---|---|---|
| `validate-json` | $0.001 | Validate JSON/YAML structure |
| `classify-text` | $0.002 | Sentiment, category, keywords |
| `extract-data` | $0.015 | Extract names, emails, phones, URLs |
| `generate-regex` | $0.005 | Regex from description with tests |
| `format-data` | $0.01 | Convert CSV/JSON/YAML |
| `summarize` | $0.005 | Summarize text to N words |

## Payment Methods

### x402 (AI agents)
Send USDC to `0xdE7eb04faE758055642f67f30D246CcB7136C95E` on Base or Polygon, then call any endpoint with `payment_tx=<hash>`.

### API Keys (human developers)
```bash
# Create key
curl -X POST http://77.239.107.30:8000/billing/create-key

# Check balance
curl "http://77.239.107.30:8000/billing/balance?key=ak-YOUR_KEY"

# Call with key
curl -X POST http://77.239.107.30:8000/api/validate-json \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ak-YOUR_KEY" \
  -d '{"data": "{\"name\": \"test\"}"}'
```

## MCP (AI Agent Connection)

AI agents connect via Model Context Protocol:

```
Endpoint: http://77.239.107.30:8000/mcp/sse
```

All 16 tools are available with `tool_name(code, ..., payment_tx="0x...")` or `tool_name(code, ..., api_key="ak-...")`.

## Response Format

All endpoints return JSON:
```json
{
  "result": "{\"valid\": true, \"errors\": [], \"warnings\": []}",
  "payment_network": "eip155:8453",
  "payment_tx": "0x..."
}
```

## Comparison

| | AI Agent API | Zugabot |
|---|---|---|
| Services | 16 | 7 |
| Pricing | $0.001–$0.20 | $0.10–$0.25 |
| 1M context | Yes | No |
| JSON mode | All services | None |
| Retries | 3x | No |
| MCP support | Yes | No |
| API keys | Yes | No |
| OpenAPI | Yes | No |
| Open source | Yes | No |

## Tech Stack

- **Model**: DeepSeek V4 Pro (1M token context window)
- **Protocol**: x402 v2 (Coinbase payment standard)
- **Facilitator**: Dexter (Permit2 gasless)
- **Networks**: Base, Polygon, Solana
- **Framework**: FastAPI + FastMCP
- **Transport**: HTTP REST + MCP SSE

## Links

- [OpenAPI Spec](http://77.239.107.30:8000/.well-known/openapi.json)
- [x402 Manifest](http://77.239.107.30:8000/.well-known/x402)
- [Health Check](http://77.239.107.30:8000/health)
