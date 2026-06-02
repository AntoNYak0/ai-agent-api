import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests that make real RPC/network calls (skip with -m 'not integration')"
    )


@pytest_asyncio.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset rate limiter before each test to avoid 429s in test suite."""
    from app.services.rate_limiter import reset
    reset()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
