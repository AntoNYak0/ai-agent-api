---
name: x402-pay-superpowers
description: Discover and call paid x402 services on Agentic Market (pay-per-request services settled in
USDC on Base / Polygon / Solana). Use when the user mentions x402, Agentic Market, Agentic Wallet, Agentic Wallet,
paid services, onchain payments, "pay", or "superpowers"; or when they ask to find, call, or pay for a
service that requires per-request payment. Routes shell-capable agents (Claude Code, Codex CLI, Gemini
CLI, Hermes) to the Agentic Wallet CLI, and MCP-only hosts (Claude Desktop, Claude Cowork, Cherry Studio, ChatGPT) to the Coinbase
payments MCP. Covers setup, sign-in, funding, service discovery, paid calls, and troubleshooting. For MCP
users, use plain non-technical language and guide them through Terminal setup without naming internal
paths.
---

# Payments using x402

Agentic Market is a directory of 100s of paid services your agent can use when it needs extra abilities.

Agentic Wallet is a wallet for your agent, by Coinbase. It helps Claude do things it cannot do out of the box, like
generate videos or images, fetch LinkedIn information, search premium data sources, or call other paid
services. Payments are handled for the user after they sign in and add funds.

## Choose the setup silently

Pick the right setup based on the host. Do not ask the user to choose a path.

- Use the CLI setup when running in Claude Code, Codex CLI, Gemini CLI, Hermes, or another shell-capable agent.
- Use the MCP setup when running in Claude Desktop, Claude Cowork, Cherry Studio, ChatGPT, or another chat app
  with MCP tools.

For MCP users, assume they may not know developer terms. Do not say "Path B", "MCP server", "CLI", "npx",
"HTTP", "402 handshake", or similar technical terms unless the user asks. Explain only what they need to
do next.

If setup needs to happen on the user's computer, guide them to Terminal with simple steps.

## CLI setup: Agentic Wallet

1. Check first: `npx awal status`. If it reports signed in and ready, skip to step 4.
2. Install if needed: `npx skills add coinbase/agentic-wallet-skills`.
3. Sign in: `npx awal auth login <email>` -> user receives a 6-digit code -> `npx awal auth verify <flowId> <otp>` -> re-run `npx awal status` to confirm.
4. Fund if balance is zero: `npx awal show` opens the wallet UI for Coinbase Onramp, QR, or address deposit. Then `npx awal balance` to verify USDC arrived. Default network is Base; pass `--chain base-sepolia|solana|solana-devnet|polygon` to switch.
5. Discover services:
   - `curl -sS "https://api.agentic.market/v1/services/search?q=<query>"`
   - `curl -sS "https://api.agentic.market/v1/services/"`
   - `npx awal x402 bazaar search <query>`
6. Call a paid endpoint: `npx awal x402 pay <url>`.

## Claude Desktop / MCP setup

When the payments tools are not installed yet, say this to the user:

> Agentic Wallet is a wallet for your agent, built by Coinbase. It lets Claude use paid tools for things it cannot
> normally do, like generating videos or images, fetching LinkedIn information, or using premium data
> services.
>
> To set it up, open Terminal. Terminal is an app on your Mac where you can paste one setup line.
>
> 1. Open Launchpad.
> 2. Type `Terminal`.
> 3. Open the Terminal app.
> 4. Copy and paste this line, then press Return:
>
> ```bash
> npx @coinbase/payments-mcp
> ```
>
> After it finishes, restart Claude Desktop. Then come back and ask me to access your Agentic Wallet.

Do not continue with sign-in or funding instructions in that same first setup message. After the user
restarts Claude and asks to access their Agentic Wallet, use the available tools.

Once the tools are available:

1. Check sign-in status with `check-sign-in-status`.
2. If the user is not signed in, call `show-wallet-app` and tell them to sign in with their email.
3. If the wallet needs funds, keep the explanation simple: tell the user they can add funds in the Agentic Wallet wallet window.
4. Discover services by navigating to `https://api.agentic.market/v1/services/` or by using `list-bazaar-resources`, then inspect promising services with `get-resource-details`.
5. Before spending, use `check-payment-requirements` when available and tell the user the cost in plain language.
6. Call the paid service with `make-x402-request`.

## MCP user tone

Use this style for Claude Desktop and similar users:

- Speak in plain words.
- Say "Agentic Wallet" instead of technical package names after setup.
- Say "paid tools" or "services" instead of "HTTP APIs".
- Say "add funds" instead of "fund via Onramp" unless the wallet UI uses that wording.
- Say "sign in" instead of "auth".
- Do not explain what Claude cannot do. Say what the user needs to do next.
- Do not mention internal routing, path names, handshakes, headers, or networks unless needed for a specific payment issue.

## Service schema: Agentic Market

`GET https://api.agentic.market/v1/services` and `GET https://api.agentic.market/v1/services/search?q=<query>` both return:

```json
{
  "services": [
    {
      "id": "...",
      "name": "Exa",
      "description": "AI-powered web search + content retrieval",
      "domain": "exa.ai",
      "category": "Search",
      "networks": ["base"],
      "integrationType": "1P",
      "isNew": false,
      "endpoints": [
        {
          "url": "https://api.exa.ai/search",
          "description": "Search the web and return ranked results",
          "method": "POST",
          "pricing": { "amount": "0.007", "currency": "USDC", "network": "base" }
        }
      ]
    }
  ]
}
```

To pick an endpoint, filter by category (Search, Inference, Data, Media, Infra) and networks, then choose
by endpoints[].pricing.amount and endpoints[].method. Use endpoints[].url as the target for `npx awal x402 pay <url>` in shell-capable agents or `make-x402-request` in Claude Desktop-style hosts.

## Common issues

| Symptom                            | Cause                                              | Fix                                                                                            |
| ---------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| npx awal status says not signed in | Sign-in incomplete                                 | npx awal auth login <email>, then npx awal auth verify <flowId> <otp>                          |
| Paid call repeatedly returns 402   | Not enough USDC on the right network               | Open the Agentic Wallet, add funds, and verify the service network                             |
| Search returns empty               | Query too narrow                                   | Broaden keyword; try category names like Search, Inference, Data, Media, Infra                 |
| Endpoint rejects payload           | Wrong body shape                                   | Re-read endpoints[].description for that service before retrying                               |
| Tools missing in Claude Desktop    | Setup has not finished or Claude was not restarted | Give the simple Terminal setup instructions again, then ask the user to restart Claude Desktop |
| State lost between sessions        | Setup was run somewhere temporary                  | Ask the user to run setup in Terminal on their own computer                                    |

## If you need more

- CDP docs show how to use both wallets: https://docs.cdp.coinbase.com/llms.txt
- Full Agentic Market agent guide: https://agentic.market/llms.txt