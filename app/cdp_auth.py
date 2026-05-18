"""CDP JWT authentication provider for x402 HTTP facilitator.

Generates Ed25519-signed JWTs per-request as required by the CDP facilitator.
Each endpoint (verify, settle, supported) gets its own JWT with matching URI claim.
"""

from __future__ import annotations

import logging

from x402.http.facilitator_client_base import AuthHeaders, AuthProvider, CreateHeadersAuthProvider

logger = logging.getLogger("cdp_auth")


def create_cdp_auth_provider(api_key_id: str, api_key_secret: str) -> AuthProvider:
    """Build an AuthProvider that generates CDP JWTs on demand.

    Each call to get_auth_headers() produces fresh JWTs for the three facilitator
    endpoints. JWTs expire after 120 seconds but are regenerated per-request so
    expiration is not a concern.
    """

    def _make_jwt(method: str, path: str) -> str:
        from cdp.auth.utils.jwt import JwtOptions, generate_jwt

        return generate_jwt(
            JwtOptions(
                api_key_id=api_key_id,
                api_key_secret=api_key_secret,
                request_method=method,
                request_host="api.cdp.coinbase.com",
                request_path=path,
                expires_in=120,
            )
        )

    def create_headers() -> dict[str, dict[str, str]]:
        return {
            "verify": {"Authorization": f"Bearer {_make_jwt('POST', '/platform/v2/x402/verify')}"},
            "settle": {"Authorization": f"Bearer {_make_jwt('POST', '/platform/v2/x402/settle')}"},
            "supported": {"Authorization": f"Bearer {_make_jwt('GET', '/platform/v2/x402/supported')}"},
        }

    logger.info("CDP auth provider created for key %s", api_key_id[:8] + "...")
    return CreateHeadersAuthProvider(create_headers)
