"""Tests for DirectFacilitator — Transfer + EIP-3009 receiveWithAuthorization.

Tests cover:
- Testnet auto-approve (both Transfer and EIP-3009 paths)
- EIP-3009 validation: missing fields, time window, minimum payment
- EIP-712 signature verification (ecrecover)
- Settlement without private key
- Dispatch logic (Transfer vs EIP-3009 routing)
"""

import time
from unittest.mock import patch

import pytest

from x402.schemas import PaymentPayload, PaymentRequirements
from app.facilitator import DirectFacilitator, EIP3009_DOMAINS, EIP3009_MIN_PAYMENT_MICROUNITS
from eth_account import Account

# ── Test keypair for EIP-712 signature generation ──────────────────────
TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PAY_TO = "0xdE7eb04faE758055642f67f30D246CcB7136C95E"


def _build_eip3009_auth(*, from_addr=None, to_addr=None, value=50_000,
                        valid_after=None, valid_before=None,
                        nonce=b"\x01" * 32, v=None, r=None, s=None):
    """Build an EIP-3009 authorization dict with sensible defaults.

    Args:
        from_addr: signer address (defaults to TEST_ADDRESS)
        to_addr: recipient (defaults to PAY_TO)
        value: USDC amount in microunits (default 50_000 = $0.05)
        valid_after: Unix timestamp (default: 1 hour ago)
        valid_before: Unix timestamp (default: 24 hours from now)
        nonce: bytes32 (default: b'\\x01' * 32)
        v, r, s: signature components (default: unsigned zeros)
    """
    now = int(time.time())
    return {
        "from": from_addr or TEST_ADDRESS,
        "to": to_addr or PAY_TO,
        "value": str(value),
        "validAfter": valid_after or (now - 3600),
        "validBefore": valid_before or (now + 86400),
        "nonce": "0x" + (nonce if isinstance(nonce, bytes) else nonce.encode()).hex(),
        "v": v or 0,
        "r": r or "0x" + "00" * 32,
        "s": s or "0x" + "00" * 32,
    }


def _sign_eip3009_auth(auth: dict, private_key: str = TEST_PRIVATE_KEY) -> dict:
    """Sign an EIP-3009 authorization dict with the given private key.

    Uses pure EIP-712 signing — Account._sign_hash(msg.body) — because
    USDC's receiveWithAuthorization uses EIP-712 directly, not EIP-191.

    Returns a new dict with v, r, s populated.
    """
    from eth_account.messages import encode_typed_data

    from_addr = auth["from"]
    to_addr = auth["to"]
    value = int(auth["value"])
    valid_after = int(auth["validAfter"])
    valid_before = int(auth["validBefore"])
    nonce_hex = auth["nonce"]

    domain = EIP3009_DOMAINS["eip155:8453"]

    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "ReceiveWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "primaryType": "ReceiveWithAuthorization",
        "domain": domain,
        "message": {
            "from": from_addr,
            "to": to_addr,
            "value": value,
            "validAfter": valid_after,
            "validBefore": valid_before,
            "nonce": nonce_hex,
        },
    }

    encoded = encode_typed_data(full_message=typed_data)
    # Pure EIP-712: sign the body (EIP-712 digest), NOT EIP-191 wrapped
    signed = Account._sign_hash(encoded.body, private_key)

    return {
        **auth,
        "v": signed.v,
        "r": "0x" + signed.r.to_bytes(32, "big").hex(),
        "s": "0x" + signed.s.to_bytes(32, "big").hex(),
    }


def _make_requirements(network="eip155:8453", **overrides) -> PaymentRequirements:
    """Build valid PaymentRequirements for testing."""
    defaults = {
        "scheme": "usdc",
        "network": network,
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "amount": "50000",
        "payTo": PAY_TO,
        "maxTimeoutSeconds": 30,
    }
    defaults.update(overrides)
    return PaymentRequirements(**defaults)


def _make_payload(authorization=None, tx_hash=None, payer=None) -> PaymentPayload:
    """Build a PaymentPayload for testing."""
    payload_dict = {}
    if authorization is not None:
        payload_dict["authorization"] = authorization
    if tx_hash is not None:
        payload_dict["transactionHash"] = tx_hash
    if payer is not None:
        payload_dict["payer"] = payer
    elif authorization and isinstance(authorization, dict):
        payload_dict["payer"] = authorization.get("from", TEST_ADDRESS)

    return PaymentPayload(
        x402Version=2,
        payload=payload_dict,
        accepted=_make_requirements(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Testnet: auto-approve (both paths)
# ═══════════════════════════════════════════════════════════════════════════


class TestTestnetAutoApprove:
    """Testnet mode auto-approves payments for testing."""

    @pytest.fixture
    def facilitator(self):
        return DirectFacilitator(testnet=True, pay_to=PAY_TO)

    @pytest.mark.asyncio
    async def test_transfer_path_auto_approves(self, facilitator):
        """Transfer path (no authorization) auto-approves on testnet."""
        payload = _make_payload(
            tx_hash="0xabc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890",
            payer=TEST_ADDRESS,
        )
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is True
        assert result.payer == TEST_ADDRESS

    @pytest.mark.asyncio
    async def test_eip3009_path_auto_approves(self, facilitator):
        """EIP-3009 path (with authorization) auto-approves on testnet."""
        auth = _build_eip3009_auth()
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is True
        assert result.payer == TEST_ADDRESS

    @pytest.mark.asyncio
    async def test_settle_eip3009_testnet_returns_success(self, facilitator):
        """settle() on testnet returns success with nonce identifier."""
        auth = _build_eip3009_auth()
        payload = _make_payload(authorization=auth)
        result = await facilitator.settle(payload, payload.accepted)
        assert result.success is True
        assert result.payer == TEST_ADDRESS


# ═══════════════════════════════════════════════════════════════════════════
# EIP-3009 validation: field-level checks (before RPC)
# ═══════════════════════════════════════════════════════════════════════════


class TestEip3009Validation:
    """Field-level validation that happens before RPC calls."""

    @pytest.fixture
    def facilitator(self):
        return DirectFacilitator(testnet=False, pay_to=PAY_TO)

    @pytest.mark.asyncio
    async def test_missing_authorization_goes_to_onchain_evm(self, facilitator):
        """When authorization is absent, route to _verify_onchain_evm."""
        payload = _make_payload(
            tx_hash="0xabc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890",
            payer=TEST_ADDRESS,
        )
        # Should NOT raise KeyError from missing authorization fields
        result = await facilitator.verify(payload, payload.accepted)
        # Will fail because RPC can't find the tx — but routing worked
        assert result.is_valid is False
        reason = (result.invalid_reason or "").lower()
        assert any(word in reason for word in ("not_found", "transaction", "rpc", "invalid"))

    @pytest.mark.asyncio
    async def test_authorization_not_a_dict(self, facilitator):
        """authorization must be a dict, not a string."""
        payload = _make_payload(authorization="not-a-dict")  # type: ignore
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "invalid" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_missing_from_field(self, facilitator):
        """Missing 'from' field → invalid."""
        auth = _build_eip3009_auth()
        del auth["from"]
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "missing" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_missing_nonce_field(self, facilitator):
        """Missing 'nonce' field → invalid."""
        auth = _build_eip3009_auth()
        del auth["nonce"]
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "missing" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_missing_signature_fields(self, facilitator):
        """Missing r, s, v fields → invalid."""
        for field in ("r", "s", "v"):
            auth = _build_eip3009_auth()
            del auth[field]
            payload = _make_payload(authorization=auth)
            result = await facilitator.verify(payload, payload.accepted)
            assert result.is_valid is False, f"Missing {field} should be rejected"

    @pytest.mark.asyncio
    async def test_auth_not_yet_valid(self, facilitator):
        """validAfter is in the future → auth_not_yet_valid."""
        future = int(time.time()) + 86400  # tomorrow
        auth = _build_eip3009_auth(valid_after=future)
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "not_yet_valid" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_auth_expired(self, facilitator):
        """validBefore is in the past → auth_expired."""
        past = int(time.time()) - 86400  # yesterday
        auth = _build_eip3009_auth(valid_before=past)
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "expired" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_below_minimum_payment(self, facilitator):
        """Value below EIP3009_MIN_PAYMENT_MICROUNITS → amount_too_small."""
        auth = _build_eip3009_auth(value=5_000)  # $0.005 < $0.01 minimum
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "too_small" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_unsupported_network(self, facilitator):
        """Network not in EIP3009_DOMAINS → unsupported_network."""
        auth = _build_eip3009_auth()
        payload = _make_payload(authorization=auth)
        payload.accepted.network = "eip155:1"  # Ethereum mainnet — no domain
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        assert "unsupported" in (result.invalid_reason or "")

    @pytest.mark.asyncio
    async def test_wrong_recipient(self, facilitator):
        """Authorization 'to' doesn't match pay_to → wrong_recipient."""
        auth = _build_eip3009_auth(to_addr="0x0000000000000000000000000000000000000001")
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False
        reason = (result.invalid_reason or "").lower()
        assert any(w in reason for w in ("recipient", "wrong"))

    @pytest.mark.asyncio
    async def test_garbage_hex_fields(self, facilitator):
        """Malformed hex fields → parse error."""
        auth = _build_eip3009_auth(from_addr="not-a-hex-address")
        payload = _make_payload(authorization=auth)
        result = await facilitator.verify(payload, payload.accepted)
        assert result.is_valid is False


# ═══════════════════════════════════════════════════════════════════════════
# EIP-712 signature verification (ecrecover)
# ═══════════════════════════════════════════════════════════════════════════


class _FakeRpcResponse:
    """Simulates httpx.Response for eth_call — synchronous json()."""
    def __init__(self, status_code=200, result="0x" + "00" * 32):
        self.status_code = status_code
        self._result = result
    def json(self):
        return {"result": self._result}


class _FakeAsyncClient:
    """Simulates `async with httpx.AsyncClient() as client:`."""
    def __init__(self, post_response=_FakeRpcResponse()):
        self._post_response = post_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        return self._post_response


def _fake_async_client_factory(post_response):
    """Return a callable that mimics httpx.AsyncClient(...)."""
    def _factory(*args, **kwargs):
        return _FakeAsyncClient(post_response)
    return _factory


class TestEip3009SignatureVerification:
    """EIP-712 signature recovery tests.

    These tests generate real EIP-712 signatures and verify the ecrecover
    path. The eth_call to authorizationState is mocked to return "not used".
    """

    @pytest.fixture
    def facilitator(self):
        return DirectFacilitator(testnet=False, pay_to=PAY_TO)

    _rpc_ok = _FakeRpcResponse(200, "0x" + "00" * 32)  # nonce NOT used

    @pytest.mark.asyncio
    async def test_valid_signature_passes_ecrecover(self, facilitator):
        """A properly signed EIP-712 authorization passes ecrecover."""
        auth = _build_eip3009_auth()
        signed = _sign_eip3009_auth(auth, TEST_PRIVATE_KEY)
        payload = _make_payload(authorization=signed)

        with patch("httpx.AsyncClient", _fake_async_client_factory(self._rpc_ok)):
            result = await facilitator.verify(payload, payload.accepted)
            assert result.is_valid is True, f"Expected valid, got: {result.invalid_reason} — {result.invalid_message}"
            assert result.payer.lower() == TEST_ADDRESS.lower()

    @pytest.mark.asyncio
    async def test_tampered_signature_fails(self, facilitator):
        """Tampered signature → invalid_signature."""
        auth = _build_eip3009_auth()
        signed = _sign_eip3009_auth(auth, TEST_PRIVATE_KEY)
        tampered = dict(signed)
        tampered["r"] = "0x" + "ff" * 32
        payload = _make_payload(authorization=tampered)

        with patch("httpx.AsyncClient", _fake_async_client_factory(self._rpc_ok)):
            result = await facilitator.verify(payload, payload.accepted)
            assert result.is_valid is False
            reason = (result.invalid_reason or "").lower()
            msg = (result.invalid_message or "").lower()
            assert "signature" in reason or "signature" in msg

    @pytest.mark.asyncio
    async def test_wrong_signer_fails(self, facilitator):
        """Signature from a different key → invalid_signature."""
        auth = _build_eip3009_auth()
        other_key = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
        signed = _sign_eip3009_auth(auth, other_key)
        payload = _make_payload(authorization=signed)

        with patch("httpx.AsyncClient", _fake_async_client_factory(self._rpc_ok)):
            result = await facilitator.verify(payload, payload.accepted)
            assert result.is_valid is False
            reason = (result.invalid_reason or "").lower()
            msg = (result.invalid_message or "").lower()
            assert "signature" in reason or "recovered" in msg

    @pytest.mark.asyncio
    async def test_v_normalization_0_to_27(self, facilitator):
        """v=0/1 is normalized to v=27/28 before ecrecover."""
        auth = _build_eip3009_auth()
        signed = _sign_eip3009_auth(auth, TEST_PRIVATE_KEY)
        # _sign_hash returns v=27 or 28. External signers may use 0/1.
        original_v = signed["v"]  # 27 or 28
        signed["v"] = original_v - 27  # map to 0 or 1
        payload = _make_payload(authorization=signed)

        with patch("httpx.AsyncClient", _fake_async_client_factory(self._rpc_ok)):
            result = await facilitator.verify(payload, payload.accepted)
            assert result.is_valid is True, f"Expected valid, got: {result.invalid_reason} — {result.invalid_message}"
            assert result.payer.lower() == TEST_ADDRESS.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Settlement
# ═══════════════════════════════════════════════════════════════════════════


class TestEip3009Settlement:
    """EIP-3009 settlement tests."""

    @pytest.fixture
    def facilitator(self):
        return DirectFacilitator(testnet=False, pay_to=PAY_TO)

    @pytest.mark.asyncio
    async def test_settle_no_private_key_configured(self, facilitator, monkeypatch):
        """settle() without private key → eip3009_not_configured."""
        monkeypatch.setattr("app.facilitator.settings.facilitator_eip3009_private_key", "")
        auth = _build_eip3009_auth()
        payload = _make_payload(authorization=auth)
        result = await facilitator.settle(payload, payload.accepted)
        assert result.success is False
        assert "not_configured" in (result.error_reason or "")

    @pytest.mark.asyncio
    async def test_settle_transfer_path_noop(self, facilitator):
        """settle() for Transfer path is a no-op (client already paid gas)."""
        payload = _make_payload(
            tx_hash="0xabc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890",
            payer=TEST_ADDRESS,
        )
        result = await facilitator.settle(payload, payload.accepted)
        assert result.success is True
        assert result.transaction == payload.payload["transactionHash"]


# ═══════════════════════════════════════════════════════════════════════════
# Dry-run: signature generation round-trip
# ═══════════════════════════════════════════════════════════════════════════


class TestEip3009RoundTrip:
    """End-to-end signature round-trip: sign → recover without RPC.

    These tests verify that our signing helper produces valid EIP-712
    signatures that recover to the correct address using ecrecover.
    """

    def test_sign_and_recover_round_trip(self):
        """A signed authorization recovers to the signing address."""
        auth = _build_eip3009_auth()
        signed = _sign_eip3009_auth(auth, TEST_PRIVATE_KEY)

        from eth_account.messages import encode_typed_data

        domain = EIP3009_DOMAINS["eip155:8453"]
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "ReceiveWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "ReceiveWithAuthorization",
            "domain": domain,
            "message": {
                "from": auth["from"],
                "to": auth["to"],
                "value": int(auth["value"]),
                "validAfter": int(auth["validAfter"]),
                "validBefore": int(auth["validBefore"]),
                "nonce": auth["nonce"],
            },
        }

        encoded = encode_typed_data(full_message=typed_data)
        recovered = Account._recover_hash(
            encoded.body,  # pure EIP-712 digest
            vrs=(signed["v"],
                 bytes.fromhex(signed["r"][2:]),
                 bytes.fromhex(signed["s"][2:])),
        )
        assert recovered.lower() == TEST_ADDRESS.lower()

    def test_sign_and_recover_fails_with_wrong_key(self):
        """Signature from a different key doesn't recover to TEST_ADDRESS."""
        auth = _build_eip3009_auth()
        other_key = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
        signed = _sign_eip3009_auth(auth, other_key)

        from eth_account.messages import encode_typed_data

        domain = EIP3009_DOMAINS["eip155:8453"]
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "ReceiveWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "ReceiveWithAuthorization",
            "domain": domain,
            "message": {
                "from": auth["from"],
                "to": auth["to"],
                "value": int(auth["value"]),
                "validAfter": int(auth["validAfter"]),
                "validBefore": int(auth["validBefore"]),
                "nonce": auth["nonce"],
            },
        }

        encoded = encode_typed_data(full_message=typed_data)
        recovered = Account._recover_hash(
            encoded.body,
            vrs=(signed["v"],
                 bytes.fromhex(signed["r"][2:]),
                 bytes.fromhex(signed["s"][2:])),
        )
        # Other key recovers to a different address, not TEST_ADDRESS
        assert recovered.lower() != TEST_ADDRESS.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Constants validation
# ═══════════════════════════════════════════════════════════════════════════


class TestConstants:
    """Sanity-check EIP-3009 constants."""

    def test_domains_have_required_fields(self):
        """Each EIP-3009 domain has name, version, chainId, verifyingContract."""
        for network, domain in EIP3009_DOMAINS.items():
            assert "name" in domain, f"{network} missing name"
            assert "version" in domain, f"{network} missing version"
            assert "chainId" in domain, f"{network} missing chainId"
            assert "verifyingContract" in domain, f"{network} missing verifyingContract"
            assert domain["verifyingContract"].startswith("0x")

    def test_selectors_not_empty(self):
        """Selector constants are non-empty."""
        from app.facilitator import (
            AUTHORIZATION_USED_TOPIC,
            RECEIVE_WITH_AUTH_TYPEHASH,
            RECEIVE_WITH_AUTH_SELECTOR,
        )
        assert len(AUTHORIZATION_USED_TOPIC) == 66  # 0x + 64 hex
        assert len(RECEIVE_WITH_AUTH_TYPEHASH) == 66
        assert len(RECEIVE_WITH_AUTH_SELECTOR) == 10  # 0x + 8 hex

    def test_minimum_payment_positive(self):
        """EIP3009_MIN_PAYMENT_MICROUNITS is a positive integer."""
        assert EIP3009_MIN_PAYMENT_MICROUNITS > 0
        assert isinstance(EIP3009_MIN_PAYMENT_MICROUNITS, int)
