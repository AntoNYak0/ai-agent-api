"""Tests for ECC fastapi-patterns adaptations: error hierarchy, DI, lifespan.

Pattern adapted from ECC fastapi-patterns:
  - Domain error classes with status_code + code + message
  - Centralized exception handlers → consistent JSON error shape
  - Reusable Depends() dependencies
  - Lifespan context manager instead of on_event
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.errors import (
    ApiError,
    NotFound,
    ValidationFailed,
    Unauthorized,
    Forbidden,
    RateLimitExceeded,
    ServiceUnavailable,
    Conflict,
    PaymentError,
    InsufficientCredits,
    register_exception_handlers,
)
from app.dependencies import (
    get_api_key,
    require_api_key,
    require_valid_api_key,
    check_rate_limit,
    get_payment_context,
)
from app.main import app


# ═══════════════════════════════════════════════════════════════════
# Error hierarchy — class attributes
# ═══════════════════════════════════════════════════════════════════

class TestApiError:
    def test_default_message(self):
        e = ApiError()
        assert e.message == "An unexpected error occurred"
        assert e.status_code == 500
        assert e.code == "internal_error"

    def test_custom_message(self):
        e = ApiError("Something broke")
        assert e.message == "Something broke"
        assert str(e) == "Something broke"

    def test_extra_detail_not_in_response(self):
        e = ApiError("Bad", extra="secret")
        resp = e.to_response()
        assert "secret" not in str(resp)
        assert e.detail == {"extra": "secret"}

    def test_to_response_shape(self):
        e = NotFound("Key not found")
        resp = e.to_response()
        assert resp == {"error": {"code": "not_found", "message": "Key not found"}}


class TestNotFoundError:
    def test_status_code(self):
        assert NotFound.status_code == 404
        assert NotFound.code == "not_found"

    def test_raise_catch(self):
        with pytest.raises(NotFound) as exc:
            raise NotFound("User 42 not found")
        assert exc.value.status_code == 404
        assert exc.value.code == "not_found"
        assert "User 42" in exc.value.message


class TestValidationFailed:
    def test_status_code(self):
        assert ValidationFailed.status_code == 400

    def test_response(self):
        e = ValidationFailed("name is required")
        resp = e.to_response()
        assert resp["error"]["code"] == "validation_failed"


class TestUnauthorized:
    def test_status_code(self):
        assert Unauthorized.status_code == 401


class TestForbidden:
    def test_status_code(self):
        assert Forbidden.status_code == 403


class TestRateLimitExceeded:
    def test_default_retry_after(self):
        e = RateLimitExceeded()
        assert e.retry_after_seconds == 60

    def test_custom_retry_after(self):
        e = RateLimitExceeded("Slow down", retry_after_seconds=120)
        assert e.retry_after_seconds == 120

    def test_response_includes_retry(self):
        e = RateLimitExceeded("Too fast")
        resp = e.to_response()
        assert resp["error"]["retry_after_seconds"] == 60


class TestServiceUnavailable:
    def test_default_retry_after(self):
        e = ServiceUnavailable()
        assert e.retry_after_seconds == 30

    def test_response_shape(self):
        e = ServiceUnavailable("DB down", retry_after_seconds=10)
        resp = e.to_response()
        assert resp["error"]["code"] == "service_unavailable"
        assert resp["error"]["retry_after_seconds"] == 10


class TestConflict:
    def test_status_code(self):
        assert Conflict.status_code == 409


class TestPaymentErrors:
    def test_payment_error_base(self):
        assert PaymentError.status_code == 402
        assert PaymentError.code == "payment_required"

    def test_insufficient_credits(self):
        assert InsufficientCredits.status_code == 402
        assert InsufficientCredits.code == "insufficient_credits"


# ═══════════════════════════════════════════════════════════════════
# Error handler integration — JSON shape compliance
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandlerIntegration:
    """Verify that ApiError subclasses produce correct HTTP responses."""

    @pytest.fixture
    def test_app(self):
        """Minimal app with only error handlers registered."""
        a = FastAPI()
        register_exception_handlers(a)

        @a.get("/not-found")
        async def not_found():
            raise NotFound("Test resource missing")

        @a.get("/bad-request")
        async def bad_request():
            raise ValidationFailed("Field 'name' required")

        @a.get("/unauthorized")
        async def unauthorized():
            raise Unauthorized("Missing token")

        @a.get("/rate-limited")
        async def rate_limited():
            raise RateLimitExceeded("Calm down", retry_after_seconds=45)

        @a.get("/server-error")
        async def server_error():
            raise ApiError("Critical failure")

        return a

    @pytest_asyncio.fixture
    async def client(self, test_app):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client):
        r = await client.get("/not-found")
        assert r.status_code == 404
        body = r.json()
        assert body["error"]["code"] == "not_found"
        assert body["error"]["message"] == "Test resource missing"

    @pytest.mark.asyncio
    async def test_validation_returns_400(self, client):
        r = await client.get("/bad-request")
        assert r.status_code == 400
        body = r.json()
        assert body["error"]["code"] == "validation_failed"

    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, client):
        r = await client.get("/unauthorized")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429_with_retry_header(self, client):
        r = await client.get("/rate-limited")
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "45"
        body = r.json()
        assert body["error"]["retry_after_seconds"] == 45

    @pytest.mark.asyncio
    async def test_server_error_returns_500(self, client):
        r = await client.get("/server-error")
        assert r.status_code == 500
        body = r.json()
        assert body["error"]["code"] == "internal_error"

    @pytest.mark.asyncio
    async def test_error_shape_is_consistent(self, client):
        """All errors follow {error: {code, message}} shape."""
        endpoints = ["/not-found", "/bad-request", "/unauthorized",
                     "/rate-limited", "/server-error"]
        for ep in endpoints:
            r = await client.get(ep)
            body = r.json()
            assert "error" in body
            assert "code" in body["error"]
            assert "message" in body["error"]


# ═══════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════

class TestDependencies:
    """Verify reusable Depends() functions."""

    @pytest.mark.asyncio
    async def test_get_api_key_no_auth(self):
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [], "query_string": "",
        }
        request = Request(scope)
        result = await get_api_key(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_api_key_with_bearer(self):
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer ak-test123")],
            "query_string": "",
        }
        request = Request(scope)
        result = await get_api_key(request)
        assert result == "ak-test123"

    @pytest.mark.asyncio
    async def test_get_api_key_with_other_bearer(self):
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer some-jwt-token")],
            "query_string": "",
        }
        request = Request(scope)
        result = await get_api_key(request)
        assert result is None  # Doesn't start with ak-

    @pytest.mark.asyncio
    async def test_require_api_key_missing(self):
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [], "query_string": "",
        }
        request = Request(scope)
        with pytest.raises(Unauthorized):
            await require_api_key(request)

    @pytest.mark.asyncio
    async def test_require_api_key_present(self):
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer ak-valid")],
            "query_string": "",
        }
        request = Request(scope)
        result = await require_api_key(request)
        assert result == "ak-valid"

    @pytest.mark.asyncio
    async def test_require_valid_api_key_invalid(self):
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer ak-nonexistent")],
            "query_string": "",
        }
        request = Request(scope)
        with pytest.raises(Unauthorized):
            await require_valid_api_key(request)

    @pytest.mark.asyncio
    async def test_check_rate_limit_skips_health(self):
        scope = {
            "type": "http", "method": "GET", "path": "/health",
            "headers": [], "query_string": "",
        }
        request = Request(scope)
        await check_rate_limit(request)  # should not raise

    @pytest.mark.asyncio
    async def test_check_rate_limit_skips_well_known(self):
        scope = {
            "type": "http", "method": "GET", "path": "/.well-known/x402",
            "headers": [], "query_string": "",
        }
        request = Request(scope)
        await check_rate_limit(request)  # should not raise


# ═══════════════════════════════════════════════════════════════════
# Lifespan — verify no deprecation
# ═══════════════════════════════════════════════════════════════════

class TestLifespan:
    """Verify the app uses lifespan, not deprecated on_event."""

    def test_app_has_lifespan(self):
        """App is created with lifespan, not on_event."""
        assert app.router.lifespan_context is not None, \
            "App should have a lifespan context manager, not @app.on_event"


# ═══════════════════════════════════════════════════════════════════
# Real app integration — billing/workflows use new errors
# ═══════════════════════════════════════════════════════════════════

class TestRealAppErrorResponses:
    """Smoke tests against the real app — verify error shape in production routes."""

    @pytest_asyncio.fixture
    async def client(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_billing_balance_missing_key(self, client):
        """GET /billing/balance?key=nonexistent → 404 with structured error."""
        r = await client.get("/billing/balance?key=ak-nonexistent")
        assert r.status_code == 404
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "not_found"

    @pytest.mark.asyncio
    async def test_billing_analytics_no_admin(self, client):
        """GET /billing/analytics without admin key → 403."""
        r = await client.get("/billing/analytics?key=wrong")
        assert r.status_code == 403
        body = r.json()
        assert body["error"]["code"] == "forbidden"

    @pytest.mark.asyncio
    async def test_workflow_not_found(self, client):
        """GET /api/workflows/nonexistent → 404 with structured error."""
        r = await client.get("/api/workflows/nonexistent-id")
        assert r.status_code == 404
        body = r.json()
        assert body["error"]["code"] == "not_found"

    @pytest.mark.asyncio
    async def test_workflow_register_no_auth(self, client):
        """POST /api/workflows/register without body → 422 (Pydantic validates required fields first)."""
        r = await client.post("/api/workflows/register", json={})
        # Pydantic validates required fields BEFORE handler runs → 422
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_workflow_register_bad_body(self, client):
        """POST /api/workflows/register with auth but missing required fields → 422."""
        r = await client.post(
            "/api/workflows/register",
            json={"api_key": "ak-test"},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_workflow_register_auth_required(self, client):
        """POST /api/workflows/register with valid body but no auth → 401."""
        r = await client.post(
            "/api/workflows/register",
            json={
                "name": "Test WF",
                "description": "A test workflow",
                "chain": ["audit", "refactor"],
            },
        )
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_workflow_register_name_too_long(self, client):
        """POST /api/workflows/register with name > 100 chars → 422."""
        r = await client.post(
            "/api/workflows/register",
            json={
                "name": "A" * 101,
                "description": "Valid description",
                "chain": ["audit"],
                "api_key": "ak-test",
            },
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_workflow_register_description_too_long(self, client):
        """POST /api/workflows/register with description > 500 chars → 422."""
        r = await client.post(
            "/api/workflows/register",
            json={
                "name": "Valid Name",
                "description": "D" * 501,
                "chain": ["audit"],
                "api_key": "ak-test",
            },
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_workflow_register_chain_comma_string(self, client):
        """POST /api/workflows/register chain as comma-separated string — accepted."""
        r = await client.post(
            "/api/workflows/register",
            json={
                "name": "Test WF",
                "description": "Test description",
                "chain": "audit, refactor",
                "api_key": "ak-test",
            },
        )
        # Will fail on auth (invalid key), but schema validation passed
        assert r.status_code == 401  # Not 422! Chain parsed successfully.

    @pytest.mark.asyncio
    async def test_workflow_register_chain_json_string(self, client):
        """POST /api/workflows/register chain as JSON-array string — accepted."""
        r = await client.post(
            "/api/workflows/register",
            json={
                "name": "Test WF",
                "description": "Test description",
                "chain": '["audit", "refactor"]',
                "api_key": "ak-test",
            },
        )
        # Schema validation passed → auth error
        assert r.status_code == 401  # Not 422!
