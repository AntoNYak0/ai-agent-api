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
    assert len(data["endpoints"]) == 16


# ── Complex services return 402 without payment ──────────────────

@pytest.mark.asyncio
async def test_audit_returns_402(client):
    response = await client.post("/api/audit", json={"code": "function foo() {}"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_refactor_returns_402(client):
    response = await client.post("/api/refactor", json={"code": "function bar() {}"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_docs_returns_402(client):
    response = await client.post("/api/docs", json={"code": "print(42)"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_defi_returns_402(client):
    response = await client.post("/api/defi-analyze", json={"protocol": "Aave"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_trading_returns_402(client):
    response = await client.post("/api/trading-signal", json={"asset": "BTC"})
    assert response.status_code == 402


# ── Micro-tasks return 402 without payment ───────────────────────

@pytest.mark.asyncio
async def test_validate_json_returns_402(client):
    response = await client.post("/api/validate-json", json={"data": "{}"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_classify_text_returns_402(client):
    response = await client.post("/api/classify-text", json={"text": "Great product!"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_extract_data_returns_402(client):
    response = await client.post("/api/extract-data", json={"text": "Contact: john@email.com"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_translate_code_returns_402(client):
    response = await client.post("/api/translate-code", json={
        "code": "def foo(): pass", "source_lang": "python", "target_lang": "typescript"
    })
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_generate_regex_returns_402(client):
    response = await client.post("/api/generate-regex", json={"description": "Match email"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_format_data_returns_402(client):
    response = await client.post("/api/format-data", json={
        "data": "a,b\n1,2", "source_format": "csv", "target_format": "json"
    })
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_summarize_returns_402(client):
    response = await client.post("/api/summarize", json={"text": "Long article text here"})
    assert response.status_code == 402
