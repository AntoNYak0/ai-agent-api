"""Centralized error hierarchy for the AI Agent API.

Pattern adapted from ECC fastapi-patterns:
  - Domain-specific exception classes with status_code, code, message
  - Single register_exception_handlers() called during app construction
  - Consistent error shape: {"error": {"code": "...", "message": "..."}}

Usage in routes:
    raise NotFound("API key not found")
    raise InsufficientCredits("Not enough credits for this operation")
    raise Unauthorized("Invalid admin key")

Payment errors (402) are kept as direct JSONResponse returns in routes
because they need custom headers (PAYMENT-REQUIRED, etc.).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Base domain exception — all API errors inherit from this.

    Derived from HTTPException pattern but decoupled from FastAPI,
    making route code testable without HTTP context.
    """
    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None, **kwargs):
        self.message = message or self.message
        self.detail = kwargs  # extra context for logging, not exposed
        super().__init__(self.message)

    def to_response(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }


class NotFound(ApiError):
    """Resource not found — 404."""
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class ValidationFailed(ApiError):
    """Client input validation failed — 400."""
    status_code = 400
    code = "validation_failed"
    message = "Validation failed"


class Unauthorized(ApiError):
    """Missing or invalid credentials — 401/403."""
    status_code = 401
    code = "unauthorized"
    message = "Authentication required"


class Forbidden(ApiError):
    """Valid credentials but insufficient permissions — 403."""
    status_code = 403
    code = "forbidden"
    message = "Access denied"


class RateLimitExceeded(ApiError):
    """Too many requests — 429."""
    status_code = 429
    code = "rate_limit_exceeded"
    message = "Too many requests"

    def __init__(self, message: str | None = None, retry_after_seconds: int = 60, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after_seconds = retry_after_seconds

    def to_response(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retry_after_seconds": self.retry_after_seconds,
            }
        }


class ServiceUnavailable(ApiError):
    """Upstream dependency is down — 503."""
    status_code = 503
    code = "service_unavailable"
    message = "Service temporarily unavailable"

    def __init__(self, message: str | None = None, retry_after_seconds: int = 30, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after_seconds = retry_after_seconds

    def to_response(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retry_after_seconds": self.retry_after_seconds,
            }
        }


class Conflict(ApiError):
    """Resource already exists — 409."""
    status_code = 409
    code = "conflict"
    message = "Resource already exists"


# ── Payment-domain errors (not HTTP exceptions — they're caught and
#    converted to 402 by the route, not the global handler) ──────────

class PaymentError(ApiError):
    """Base for payment-domain errors. Routes catch these to return 402."""
    status_code = 402
    code = "payment_required"
    message = "Payment required"


class InsufficientCredits(PaymentError):
    """API key has insufficient credits."""
    status_code = 402
    code = "insufficient_credits"
    message = "Insufficient credits"


class CircuitBreakerOpen(ApiError):
    """Circuit breaker is OPEN — upstream service is failing, fast-fail enabled."""
    status_code = 503
    code = "circuit_breaker_open"
    message = "Circuit breaker is open — service temporarily unavailable"

    def __init__(
        self,
        message: str | None = None,
        service_name: str = "",
        retry_after_seconds: int = 60,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.service_name = service_name
        self.retry_after_seconds = retry_after_seconds

    def to_response(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "service_name": self.service_name,
                "retry_after_seconds": self.retry_after_seconds,
            }
        }


# ── Exception handler registration ─────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    """Register centralized exception handlers on the FastAPI app.

    Called once during app construction (after create_app() or in main.py).
    Error shape: {"error": {"code": "...", "message": "...", ...}}
    """

    async def _handler(request: Request, exc: ApiError) -> JSONResponse:
        # Log 5xx server errors, skip 4xx client errors
        if exc.status_code >= 500:
            import logging
            logger = logging.getLogger("api.errors")
            logger.error(
                "API error %s (status=%d): %s",
                exc.code, exc.status_code, exc.message,
                extra={"path": str(request.url), "detail": exc.detail} if exc.detail else {},
            )

        headers: dict = {}
        if hasattr(exc, "retry_after_seconds"):
            headers["Retry-After"] = str(exc.retry_after_seconds)

        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response(),
            headers=headers,
        )

    # Register one handler for all ApiError subclasses
    app.add_exception_handler(ApiError, _handler)
