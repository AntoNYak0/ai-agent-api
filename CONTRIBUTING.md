# Contributing to AI Agent API

Thanks for helping build the first pay-per-use AI API for Web3 agents!

## Ways to Contribute

### 🐛 Report Bugs
Open an issue with:
- What you called and what you expected
- The exact response or error
- Your client (Claude Code, Cursor, custom agent, etc.)

### 💡 Suggest Features
Open an issue with `[Feature]` in the title. For new AI services, describe:
- What it does
- What input it takes
- What output it returns
- Why agents would pay for it

### 🔧 Submit Code

1. **Fork** the repo
2. **Create a branch** — `feat/your-feature` or `fix/your-bug`
3. **Run tests:**
   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-asyncio httpx
   pytest tests/ -v
   ```
4. **Run lint:**
   ```bash
   pip install ruff
   ruff check app/ --ignore=E501,F841
   ```
5. **Open a PR** against `master`

### 📋 PR Guidelines

- Keep PRs focused — one feature or fix per PR
- Add tests for new functionality
- Update `pricing.py` if adding a new AI service
- Update `README.md` counts if adding/removing tools
- Run `pytest tests/ -v` before pushing
- CI must be green (ruff + pytest + bandit + pip-audit)

### 🏗️ Architecture

Before contributing code, read [CLAUDE.md](CLAUDE.md) — it covers:
- Middleware chain (rate limiter → security → cache → x402 payment)
- Payment flow (validate_min_price → AI call → settle_actual_usage)
- Route pattern (all endpoints follow the same 5-step flow)
- Facilitator modes (payai, direct, cdp, chaoschain)
- Error hierarchy (ApiError → domain-specific subclasses)

### 💰 Revenue Share

Composite workflows registered via the API pay 85% to the author. To register a workflow:
```bash
curl -X POST https://agent-api-ai.duckdns.org/workflows/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ak-YOUR_KEY" \
  -d '{"name": "my-workflow", "chain": ["audit", "refactor"], "price_cents": 8}'
```

### 📦 Adding a New AI Service

1. Create a prompt module in `app/prompts/`
2. Add pricing to `app/pricing.py` (`AI_UPTO_SERVICES` or `EXACT_SERVICES`)
3. Add MCP tool name to `_TOOL_NAMES` in `pricing.py`
4. Add route in `app/routes/` following the standard 5-step pattern
5. Register MCP tool in `app/mcp_server.py`
6. Add tests in `tests/`
7. Update counts in `README.md`, `AGENTS.md`, `mcp.json`, `smithery.yaml`, `server.json`

### ❓ Questions?

- [GitHub Discussions](https://github.com/AntoNYak0/ai-agent-api/discussions)
- Email: admin@agent-api-ai.duckdns.org
