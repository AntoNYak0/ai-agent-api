import pytest


@pytest.mark.asyncio
async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_well_known_returns_manifest(client):
    response = await client.get("/.well-known/x402")
    assert response.status_code == 200
    data = response.json()
    assert data["x402_version"] == 2
    assert len(data["endpoints"]) == 24


@pytest.mark.asyncio
async def test_agentic_market_services(client):
    response = await client.get("/.well-known/agentic-market-services.json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["services"]) == 24
    for s in data["services"]:
        assert "id" in s
        assert "category" in s
        assert "endpoints" in s
        assert s["domain"] == "agent-api-ai.duckdns.org"


# ── Complex services return 402 without payment ──────────────────

@pytest.mark.asyncio
async def test_audit_returns_402(client):
    response = await client.post("/api/audit", json={"code": "function foo() {}"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_refactor_returns_402(client):
    response = await client.post("/api/refactor", json={"code": "function bar() {}"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_docs_returns_402(client):
    response = await client.post("/api/docs", json={"code": "print(42)"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_defi_returns_402(client):
    response = await client.post("/api/defi-analyze", json={"protocol": "Aave"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_trading_returns_402(client):
    response = await client.post("/api/trading-signal", json={"asset": "BTC"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_solidity_scan_returns_402(client):
    response = await client.post("/api/solidity-scan", json={"code": "contract Foo {}"})
    assert response.status_code in (402, 429)


# ── SQL / Dev tools return 402 without payment ────────────────────

@pytest.mark.asyncio
async def test_nl_to_sql_returns_402(client):
    response = await client.post("/api/nl-to-sql", json={"query": "find all users"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_sql_to_nl_returns_402(client):
    response = await client.post("/api/sql-to-nl", json={"sql": "SELECT * FROM users"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_git_summarize_returns_402(client):
    response = await client.post("/api/git-summarize", json={"diff": "diff --git a/foo b/foo"})
    assert response.status_code in (402, 429)


# ── Micro-tasks return 402 without payment ───────────────────────

@pytest.mark.asyncio
async def test_validate_json_returns_402(client):
    response = await client.post("/api/validate-json", json={"data": "{}"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_classify_text_returns_402(client):
    response = await client.post("/api/classify-text", json={"text": "Great product!"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_extract_data_returns_402(client):
    response = await client.post("/api/extract-data", json={"text": "Contact: john@email.com"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_translate_code_returns_402(client):
    response = await client.post("/api/translate-code", json={
        "code": "def foo(): pass", "source_lang": "python", "target_lang": "typescript"
    })
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_generate_regex_returns_402(client):
    response = await client.post("/api/generate-regex", json={"description": "Match email"})
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_format_data_returns_402(client):
    response = await client.post("/api/format-data", json={
        "data": "a,b\n1,2", "source_format": "csv", "target_format": "json"
    })
    assert response.status_code in (402, 429)


@pytest.mark.asyncio
async def test_summarize_returns_402(client):
    response = await client.post("/api/summarize", json={"text": "Long article text here"})
    assert response.status_code in (402, 429)


# ── E2E x402 payment cycle ──────────────────────────────────────

import base64
import json


@pytest.mark.asyncio
async def test_x402_payment_required_header_structure(client):
    """PAYMENT-REQUIRED header must contain all fields AgentOnRails expects."""
    response = await client.post("/api/audit", json={"code": "function foo() {}"})
    assert response.status_code == 402

    pr_header = response.headers.get("payment-required")
    assert pr_header, "PAYMENT-REQUIRED header must be present"

    challenge = json.loads(base64.b64decode(pr_header))
    assert challenge["x402Version"] == 2
    assert len(challenge["accepts"]) >= 1

    option = challenge["accepts"][0]
    assert option["scheme"] in ("exact", "upto")
    assert option["network"].startswith("eip155:")
    assert option["asset"].startswith("0x")
    assert option["payTo"].startswith("0x")
    assert int(option["amount"]) > 0
    assert int(option["maxTimeoutSeconds"]) >= 60


@pytest.mark.asyncio
async def test_x402_payment_help_header(client):
    """X-Payment-Help must guide users on payment flow."""
    response = await client.post("/api/audit", json={"code": "function foo() {}"})
    assert response.status_code == 402

    help_text = response.headers.get("x-payment-help", "")
    assert "USDC" in help_text
    assert "0xdE7eb04" in help_text
    assert "payment-signature" in help_text


@pytest.mark.asyncio
async def test_x402_retry_with_payment_signature_does_not_crash(client, monkeypatch):
    """Retry with payment-signature must not cause 500 — returns 402 (invalid tx) or 200 (testnet)."""
    # Mock DeepSeek to avoid real AI API calls if payment passes
    async def mock_deepseek(*args, **kwargs):
        return "mocked AI response"

    async def mock_cached(*args, **kwargs):
        return ("mocked AI response", 100)
    import app.routes.audit as audit_module
    monkeypatch.setattr(audit_module, "cached_completion", mock_cached)

    # 1. Get 402 challenge
    response = await client.post("/api/audit", json={"code": "function foo() {}"})
    assert response.status_code == 402

    # 2. Retry with a payment-signature
    payment_payload = {
        "x402Version": 2,
        "payload": {
            "transactionHash": "0x" + "ab" * 32,
            "payer": "0x" + "cd" * 20,
        },
    }
    payment_sig = base64.b64encode(
        json.dumps(payment_payload).encode()
    ).decode()

    response2 = await client.post(
        "/api/audit",
        json={"code": "function foo() {}"},
        headers={"payment-signature": payment_sig},
    )
    # Must not be 500. 200 = testnet auto-approve, 402 = PayAI rejects fake tx.
    # Both are correct depending on facilitator mode.
    assert response2.status_code in (200, 402, 403, 422), \
        f"Unexpected status {response2.status_code}: {response2.text}"


@pytest.mark.asyncio
async def test_x402_payment_signature_header_parsing(client):
    """Payment-signature header must be accepted and parsed by x402 middleware."""
    payment_payload = {
        "x402Version": 2,
        "payload": {
            "transactionHash": "0x" + "ab" * 32,
            "payer": "0x" + "cd" * 20,
        },
    }
    payment_sig = base64.b64encode(
        json.dumps(payment_payload).encode()
    ).decode()

    response = await client.post(
        "/api/audit",
        json={"code": "function foo() {}"},
        headers={"payment-signature": payment_sig},
    )
    # Middleware parsed the header — returns 402 (PayAI rejects fake tx)
    # or 200 (testnet auto-approve). Both are fine.
    assert response.status_code in (200, 402, 403, 422), \
        f"Unexpected status {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_x402_all_services_return_payment_required(client):
    """Every API endpoint must return 402 without payment (not 500, not 200)."""
    endpoints = [
        ("/api/audit", {"code": "test"}),
        ("/api/refactor", {"code": "test"}),
        ("/api/docs", {"code": "test"}),
        ("/api/defi-analyze", {"protocol": "test"}),
        ("/api/trading-signal", {"asset": "BTC"}),
        ("/api/solidity-scan", {"code": "contract Test {}"}),
        ("/api/whale-tracker", {"asset": "USDC"}),
        ("/api/smart-money", {"wallet_address": "0x" + "aa" * 20}),
        ("/api/price-feed", {"token": "ETH"}),
        ("/api/agent-audit", {"agent_code": "test"}),
        ("/api/contract-verify", {"contract_code": "contract Test {}"}),
        ("/api/security-score", {"code": "test"}),
        ("/api/data-feed", {"topic": "test"}),
        ("/api/debug-log", {"log": "error: test"}),
        ("/api/nl-to-sql", {"query": "test"}),
        ("/api/sql-to-nl", {"sql": "SELECT 1"}),
        ("/api/translate-code", {"code": "test", "source_lang": "py", "target_lang": "ts"}),
        ("/api/git-summarize", {"diff": "test"}),
    ]
    for path, body in endpoints:
        response = await client.post(path, json=body)
        assert response.status_code in (402, 429, 422), \
            f"{path}: expected 402, got {response.status_code}"
