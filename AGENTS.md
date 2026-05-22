# AGENTS.md — AI Agent API

Instructions for AI agents connecting to this MCP server.

## Connection

```
SSE Endpoint: https://agent-api-ai.duckdns.org/mcp/sse
Transport: SSE (Server-Sent Events)
Protocol: MCP (Model Context Protocol)
```

## Authentication

**x402 crypto payment** — no API key needed. Send USDC, get a tx hash, pass it as `payment_tx`.

| Parameter | Value |
|-----------|-------|
| Token | USDC |
| Networks | Base (`eip155:8453`), Arbitrum (`eip155:42161`), Optimism (`eip155:10`) |
| Wallet | `0xdE7eb04faE758055642f67f30D246CcB7136C95E` |
| Min payment | $0.0005 USDC |

**API key** (human developers): pass `api_key=ak-<your-key>`.

## Payment Flow

1. Call tool without `payment_tx` → server returns payment address + amount
2. Send exact USDC amount to the wallet
3. Call tool again with `payment_tx=<tx-hash>`
4. Server verifies on-chain, executes tool, returns result

## Available Tools (20)

### AI Services (upto pricing — pay per token usage)
- **audit** ($0.01-$0.05) — Security scan with OWASP Top 10 + SWC Registry
- **refactor** ($0.01-$0.05) — Legacy code modernization (DRY, SOLID)
- **docs** ($0.005-$0.03) — Technical documentation generation
- **defi** ($0.01-$0.04) — DeFi protocol analysis
- **trading** ($0.005-$0.03) — Crypto market analysis
- **solidity-scan** ($0.02-$0.08) — Solidity vulnerability scanner (36 SWC)
- **nl-to-sql** ($0.005-$0.03) — Natural language to SQL
- **sql-to-nl** ($0.005-$0.02) — SQL to plain English
- **git-summarize** ($0.005-$0.02) — Git diff to PR description
- **translate-code** ($0.01-$0.05) — Code translation between languages

### Micro-tasks (exact flat pricing)
- **validate-json** ($0.0005) — Validate JSON/YAML structure
- **classify-text** ($0.001) — Sentiment, category, keywords
- **extract-data** ($0.005) — Extract structured data from text
- **generate-regex** ($0.002) — Regex from description with tests
- **format-data** ($0.003) — Convert CSV/JSON/YAML
- **summarize** ($0.002) — Summarize text to N words

### Composite Skills
- **defi-research** ($0.08) — Extract → Analyze → Summarize
- **code-health-check** ($0.10) — Audit → Refactor → Document
- **smart-contract-audit** ($0.10) — Scan → Document
- **data-pipeline** ($0.05) — Extract → Format → Summarize

## Common Parameters (every tool)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `payment_tx` | string | No* | USDC transaction hash |
| `api_key` | string | No* | API key (ak- prefix) |
| `network` | string | No | CAIP-2 chain ID (default: `eip155:8453`) |

*One of `payment_tx` or `api_key` is required.

## Discovery Endpoints

- `/.well-known/x402` — Full manifest with all 24 services and prices
- `/.well-known/openapi.json` — OpenAPI 3.1 spec with x402 extensions
- `/.well-known/mcp/server-card.json` — Smithery server card
- `/.well-known/glama.json` — Glama auto-discovery
- `/.well-known/agent-card.json` — A2A agent card
- `/.well-known/agentic-market-services.json` — agentic.market listing
- `/.well-known/agent.json` — AP2 (Agent Payments Protocol) discovery
