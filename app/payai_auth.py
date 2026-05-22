"""PayAI JWT authentication provider for x402 HTTP facilitator.

Generates Ed25519-signed JWTs per-request for the PayAI facilitator.
API key secret format: payai_sk_<base64-encoded Ed25519 PKCS#8 DER key>
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
import time

from x402.http.facilitator_client_base import AuthProvider, CreateHeadersAuthProvider

logger = logging.getLogger("payai_auth")


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _create_jwt(api_key_id: str, api_key_secret_b64: str, method: str, path: str) -> str:
    """Create an Ed25519-signed JWT for PayAI facilitator authentication."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    secret_b64 = api_key_secret_b64
    if secret_b64.startswith("payai_sk_"):
        secret_b64 = secret_b64[len("payai_sk_"):]

    try:
        private_key_bytes = base64.b64decode(secret_b64)
        private_key = serialization.load_der_private_key(private_key_bytes, password=None)
    except Exception:
        private_key_bytes = base64.b64decode(secret_b64)
        if len(private_key_bytes) == 32:
            private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        else:
            raise

    now = int(time.time())
    header = {"alg": "EdDSA", "typ": "JWT", "kid": api_key_id}
    payload = {
        "sub": api_key_id,
        "iss": "payai-merchant",
        "iat": now,
        "exp": now + 120,
        "jti": uuid.uuid4().hex,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = header_b64 + "." + payload_b64

    signature = private_key.sign(signing_input.encode())
    signature_b64 = _base64url_encode(signature)

    return signing_input + "." + signature_b64


def create_payai_auth_provider(api_key_id: str, api_key_secret: str) -> AuthProvider:
    """Build an AuthProvider that generates PayAI JWTs on demand."""

    def create_headers() -> dict:
        verify_path = "/verify"
        settle_path = "/settle"
        supported_path = "/supported"
        return {
            "verify": {
                "Authorization": "Bearer " + _create_jwt(api_key_id, api_key_secret, "POST", verify_path)
            },
            "settle": {
                "Authorization": "Bearer " + _create_jwt(api_key_id, api_key_secret, "POST", settle_path)
            },
            "supported": {
                "Authorization": "Bearer " + _create_jwt(api_key_id, api_key_secret, "GET", supported_path)
            },
        }

    logger.info("PayAI auth provider created for key %s...", api_key_id[:12])
    return CreateHeadersAuthProvider(create_headers)
