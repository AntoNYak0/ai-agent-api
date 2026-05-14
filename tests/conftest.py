import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_audit_returns_402_without_payment(client):
    response = await client.post("/api/audit", json={"code": "function foo() {}"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_refactor_returns_402_without_payment(client):
    response = await client.post("/api/refactor", json={"code": "function bar() {}"})
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_docs_returns_402_without_payment(client):
    response = await client.post("/api/docs", json={"code": "print(42)"})
    assert response.status_code == 402
