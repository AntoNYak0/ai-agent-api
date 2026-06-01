# Security Policy

## Payment Security (x402)

- **TOCTOU protection:** `validate_min_price()` executes before AI processing — payment is verified fail-closed. If verification fails, no tokens are consumed.
- **Replay protection:** Every `payment_tx` is tracked per-tool. A transaction hash can only be used once per tool. SQLite-backed persistent storage + in-memory cache. Stats exposed at `/health/security`.
- **Settlement:** For "upto" pricing, actual usage is settled after the AI call completes. Overpayment is not refunded — agents authorize a max and pay actual (lower or equal).

## API Key Security

- **Hashing at rest:** All API keys are SHA-256 hashed before storage. Plaintext keys never touch disk.
- **Atomic writes:** Credit balance updates use atomic file replacement (`tempfile + os.replace`).
- **Rate limiting:** 10 requests/minute per IP for REST endpoints. `/billing` endpoints are excluded from global rate limit. Cumulative block counter exposed via Prometheus metrics.

## Prompt Injection Defense

- **12 regex patterns** in `deepseek.py:_sanitize()` strip jailbreak attempts, role-switching, and prompt leakage.
- All user input is sanitized before reaching the model.
- **Monitoring:** In-memory sliding window (60s) tracks recent injection attempts. Escalation at 5 attempts/60s, hard block at 20 attempts/60s.
- Cumulative `api_injection_blocks_total` counter exposed via Prometheus at `/health/metrics`.
- Injection stats available at `/health/security` (real-time status, recent attempts count).

## Security Monitoring

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/health` | Basic liveness check |
| `/health/security` | Security health — replay guard, rate limiter, prompt injection stats. Returns `status: ok|warning|critical` with detailed warnings. |
| `/health/metrics` | Prometheus text-format metrics: `api_rate_limit_blocks_total`, `api_replay_blocks_total`, `api_injection_blocks_total`, `api_replay_fingerprints`, `api_injection_recent_attempts` |

### Dashboard

The HTML dashboard at `/` includes a Security card with color-coded stats (green = no attacks, red = attacks detected) showing rate limiter blocks, replay blocks, and injection blocks.

## Facilitator Security

| Mode | Auth | Risk |
|------|------|------|
| `payai_auth` | Ed25519 JWT | PayAI-managed facilitator |
| `direct` | Public RPC verification | Self-verified USDC transfers |
| `cdp` | Ed25519 JWT | Coinbase-managed facilitator |

## Reporting a Vulnerability

Email: admin@agent-api-ai.duckdns.org

Do NOT open a public issue for security vulnerabilities.
