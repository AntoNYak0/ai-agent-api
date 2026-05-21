# Security Policy

## Payment Security (x402)

- **TOCTOU protection:** `validate_min_price()` executes before AI processing — payment is verified fail-closed. If verification fails, no tokens are consumed.
- **Replay protection:** Every `payment_tx` is tracked per-tool. A transaction hash can only be used once per tool (SHA-256 indexed, LRU cache with 10min TTL).
- **Settlement:** For "upto" pricing, actual usage is settled after the AI call completes. Overpayment is not refunded — agents authorize a max and pay actual (lower or equal).

## API Key Security

- **Hashing at rest:** All API keys are SHA-256 hashed before storage. Plaintext keys never touch disk.
- **Atomic writes:** Credit balance updates use atomic file replacement (`tempfile + os.replace`).
- **Rate limiting:** 10 requests/minute per IP for REST endpoints. `/billing` endpoints are excluded from global rate limit.

## Prompt Injection Defense

- 10 regex patterns in `deepseek.py:_sanitize()` strip jailbreak attempts, role-switching, and prompt leakage.
- All user input is sanitized before reaching the model.

## Facilitator Security

| Mode | Auth | Risk |
|------|------|------|
| `payai_auth` | Ed25519 JWT | PayAI-managed facilitator |
| `direct` | Public RPC verification | Self-verified USDC transfers |
| `cdp` | Ed25519 JWT | Coinbase-managed facilitator |

## Reporting a Vulnerability

Email: admin@agent-api-ai.duckdns.org

Do NOT open a public issue for security vulnerabilities.
