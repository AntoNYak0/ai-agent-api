# Setup Agent API MCP Server

Add 20 pay-per-call AI tools to your agent in one command.

## Quick Install

```bash
npx skills add https://github.com/AntoNYak0/ai-agent-api
```

Then run `/setup-agent-api` in Claude Code.

## What You Get

| Category | Tools | Pricing |
|----------|-------|---------|
| Code Security | audit, solidity-scan | $0.01-$0.08 USDC |
| Code Quality | refactor, docs | $0.005-$0.05 USDC |
| DeFi/Trading | defi, trading | $0.005-$0.04 USDC |
| SQL Tools | nl-to-sql, sql-to-nl | $0.005-$0.03 USDC |
| Dev Tools | git-summarize, translate-code | $0.005-$0.05 USDC |
| Micro-tasks | validate-json, classify-text, extract-data, generate-regex, format-data, summarize | $0.0005-$0.005 USDC |
| Composite | defi-research, code-health-check, smart-contract-audit, data-pipeline | $0.05-$0.10 USDC |

## Payment

**x402 crypto** — AI agents pay in USDC per call. No subscription, no API key.

1. Send USDC to `0xdE7eb04faE758055642f67f30D246CcB7136C95E` on Base/Arbitrum/Optimism
2. Pass `payment_tx=<tx-hash>` with every tool call
3. Server verifies on-chain and returns result

**API keys** — humans can prepay at https://agent-api-ai.duckdns.org/

## Connection

```
SSE Endpoint: https://agent-api-ai.duckdns.org/mcp/sse
```

Add to your MCP client:
```json
{
  "mcpServers": {
    "ai-agent-api": {
      "type": "sse",
      "url": "https://agent-api-ai.duckdns.org/mcp/sse"
    }
  }
}
```
