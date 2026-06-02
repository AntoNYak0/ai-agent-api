"""Integration tests for EIP-3009 verification against real Base RPC endpoints.

These tests make REAL RPC calls to Base mainnet/Sepolia.
Skip during normal runs:  pytest -m "not integration"
Run selectively:          pytest tests/test_eip3009_integration.py -v -m integration
"""

import os
import time

import pytest

from x402.schemas import PaymentPayload, PaymentRequirements
from app.facilitator import DirectFacilitator, EIP3009_DOMAINS, EIP3009_MIN_PAYMENT_MICROUNITS
from eth_account import Account
from eth_account.messages import encode_typed_data

pytestmark = pytest.mark.integration

# Test keypair
TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PAY_TO = "0xdE7eb04faE758055642f67f30D246CcB7136C95E"


def _sign_eip3009_auth(
    *,
    private_key: str,
    pay_to: str,
    network: str = "eip155:8453",
    value_microunits: int = 50_000,
    valid_after_offset: int = -3600,
    valid_before_offset: int = 86400,
) -> dict:
    """Build and sign a valid EIP-3009 ReceiveWithAuthorization."""
    domain = EIP3009_DOMAINS[network]
    signer = Account.from_key(private_key)
    now = int(time.time())
    nonce_bytes = os.urandom(32)  # bytes32 — 32 bytes exactly

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
            "from": signer.address,
            "to": pay_to,
            "value": value_microunits,
            "validAfter": now + valid_after_offset,
            "validBefore": now + valid_before_offset,
            "nonce": "0x" + nonce_bytes.hex(),
        },
    }

    encoded = encode_typed_data(full_message=typed_data)
    signed = Account._sign_hash(encoded.body, private_key)

    return {
        "from": signer.address,
        "to": pay_to,
        "value": str(value_microunits),
        "validAfter": typed_data["message"]["validAfter"],
        "validBefore": typed_data["message"]["validBefore"],
        "nonce": typed_data["message"]["nonce"],
        "v": signed.v,
        "r": "0x" + signed.r.to_bytes(32, "big").hex(),
        "s": "0x" + signed.s.to_bytes(32, "big").hex(),
    }


def _sign_eip3009_with_nonce(
    *,
    private_key: str,
    pay_to: str,
    network: str,
    value_microunits: int,
    nonce_bytes: bytes,
    valid_after_offset: int = -3600,
    valid_before_offset: int = 86400,
) -> dict:
    """Like _sign_eip3009_auth but with explicit nonce_bytes."""
    domain = EIP3009_DOMAINS[network]
    signer = Account.from_key(private_key)
    now = int(time.time())

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
            "from": signer.address,
            "to": pay_to,
            "value": value_microunits,
            "validAfter": now + valid_after_offset,
            "validBefore": now + valid_before_offset,
            "nonce": "0x" + nonce_bytes.hex(),
        },
    }

    encoded = encode_typed_data(full_message=typed_data)
    signed = Account._sign_hash(encoded.body, private_key)

    return {
        "from": signer.address,
        "to": pay_to,
        "value": str(value_microunits),
        "validAfter": typed_data["message"]["validAfter"],
        "validBefore": typed_data["message"]["validBefore"],
        "nonce": typed_data["message"]["nonce"],
        "v": signed.v,
        "r": "0x" + signed.r.to_bytes(32, "big").hex(),
        "s": "0x" + signed.s.to_bytes(32, "big").hex(),
    }


class TestEip3009RealRpc:
    """EIP-3009 verify() — REAL RPC calls to Base mainnet/Sepolia."""

    @pytest.mark.asyncio
    async def test_verify_valid_signature_against_mainnet(self):
        """Verify a properly signed EIP-3009 authorization against Base mainnet RPCs.

        Uses eth_call authorizationState(from, nonce) — read-only, zero risk.
        The random nonce guarantees authorizationState returns False (not used).
        """
        facilitator = DirectFacilitator(testnet=False, pay_to=PAY_TO)
        network = "eip155:8453"
        auth = _sign_eip3009_auth(
            private_key=TEST_PRIVATE_KEY,
            pay_to=PAY_TO,
            network=network,
            value_microunits=50_000,
        )

        requirements = PaymentRequirements(
            scheme="usdc",
            network=network,
            asset=EIP3009_DOMAINS[network]["verifyingContract"],
            amount="50000",
            payTo=PAY_TO,
            maxTimeoutSeconds=30,
        )

        payload = PaymentPayload(
            x402Version=2,
            payload={
                "payer": auth["from"],
                "authorization": auth,
            },
            accepted=requirements,
        )

        result = await facilitator.verify(payload, requirements)

        assert result.is_valid, (
            f"EIP-3009 verification should pass. "
            f"Got: reason={result.invalid_reason} msg={result.invalid_message}"
        )
        assert result.payer.lower() == TEST_ADDRESS.lower()

    @pytest.mark.asyncio
    async def test_verify_valid_signature_against_sepolia(self):
        """Verify EIP-3009 authorization against Base Sepolia testnet RPCs."""
        facilitator = DirectFacilitator(testnet=False, pay_to=PAY_TO)
        network = "eip155:84532"
        auth = _sign_eip3009_auth(
            private_key=TEST_PRIVATE_KEY,
            pay_to=PAY_TO,
            network=network,
            value_microunits=50_000,
        )

        requirements = PaymentRequirements(
            scheme="usdc",
            network=network,
            asset=EIP3009_DOMAINS[network]["verifyingContract"],
            amount="50000",
            payTo=PAY_TO,
            maxTimeoutSeconds=30,
        )

        payload = PaymentPayload(
            x402Version=2,
            payload={
                "payer": auth["from"],
                "authorization": auth,
            },
            accepted=requirements,
        )

        result = await facilitator.verify(payload, requirements)

        assert result.is_valid, (
            f"EIP-3009 verification on Sepolia should pass. "
            f"Got: reason={result.invalid_reason} msg={result.invalid_message}"
        )
        assert result.payer.lower() == TEST_ADDRESS.lower()

    @pytest.mark.asyncio
    async def test_verify_with_known_nonce(self):
        """Verify succeeds with a known nonce — checks RPC authorizationState call.

        Signs a proper EIP-3009 auth with a deterministic nonce (not random),
        then verifies against Base mainnet. This confirms the full flow works:
        ecrecover → authorizationState eth_call.
        """
        facilitator = DirectFacilitator(testnet=False, pay_to=PAY_TO)
        network = "eip155:8453"
        auth = _sign_eip3009_with_nonce(
            private_key=TEST_PRIVATE_KEY,
            pay_to=PAY_TO,
            network=network,
            value_microunits=50_000,
            nonce_bytes=b"\x01" * 32,  # deterministic, sign with this nonce
        )

        requirements = PaymentRequirements(
            scheme="usdc",
            network=network,
            asset=EIP3009_DOMAINS[network]["verifyingContract"],
            amount="50000",
            payTo=PAY_TO,
            maxTimeoutSeconds=30,
        )

        payload = PaymentPayload(
            x402Version=2,
            payload={
                "payer": auth["from"],
                "authorization": auth,
            },
            accepted=requirements,
        )

        result = await facilitator.verify(payload, requirements)

        assert result.is_valid, (
            f"EIP-3009 verification with known nonce should pass. "
            f"Got: reason={result.invalid_reason} msg={result.invalid_message}"
        )
        assert result.payer.lower() == TEST_ADDRESS.lower()

    @pytest.mark.asyncio
    async def test_verify_expired_authorization_fails(self):
        """EIP-3009 authorization with validBefore in the past should fail."""
        facilitator = DirectFacilitator(testnet=False, pay_to=PAY_TO)
        network = "eip155:8453"
        auth = _sign_eip3009_auth(
            private_key=TEST_PRIVATE_KEY,
            pay_to=PAY_TO,
            network=network,
            valid_before_offset=-3600,  # expired 1 hour ago
        )

        requirements = PaymentRequirements(
            scheme="usdc",
            network=network,
            asset=EIP3009_DOMAINS[network]["verifyingContract"],
            amount="50000",
            payTo=PAY_TO,
            maxTimeoutSeconds=30,
        )

        payload = PaymentPayload(
            x402Version=2,
            payload={
                "payer": auth["from"],
                "authorization": auth,
            },
            accepted=requirements,
        )

        result = await facilitator.verify(payload, requirements)

        assert not result.is_valid
        assert "expired" in result.invalid_reason.lower()

    @pytest.mark.asyncio
    async def test_verify_wrong_signature_fails(self):
        """EIP-3009 with corrupted signature should fail verification."""
        facilitator = DirectFacilitator(testnet=False, pay_to=PAY_TO)
        network = "eip155:8453"
        auth = _sign_eip3009_auth(
            private_key=TEST_PRIVATE_KEY,
            pay_to=PAY_TO,
            network=network,
        )
        # Corrupt the signature: flip a bit in s
        s_int = int(auth["s"], 16)
        auth["s"] = hex(s_int ^ 0xDEADBEEF)

        requirements = PaymentRequirements(
            scheme="usdc",
            network=network,
            asset=EIP3009_DOMAINS[network]["verifyingContract"],
            amount="50000",
            payTo=PAY_TO,
            maxTimeoutSeconds=30,
        )

        payload = PaymentPayload(
            x402Version=2,
            payload={
                "payer": auth["from"],
                "authorization": auth,
            },
            accepted=requirements,
        )

        result = await facilitator.verify(payload, requirements)

        assert not result.is_valid
        assert "signature" in result.invalid_reason.lower()

    @pytest.mark.asyncio
    async def test_verify_unsupported_network_fails(self):
        """EIP-3009 on unsupported network should fail with clear error."""
        facilitator = DirectFacilitator(testnet=False, pay_to=PAY_TO)
        auth = _sign_eip3009_auth(
            private_key=TEST_PRIVATE_KEY,
            pay_to=PAY_TO,
            network="eip155:8453",  # sign for mainnet
        )

        requirements = PaymentRequirements(
            scheme="usdc",
            network="eip155:99999",  # unsupported
            asset="0x0000000000000000000000000000000000000001",
            amount="50000",
            payTo=PAY_TO,
            maxTimeoutSeconds=30,
        )

        payload = PaymentPayload(
            x402Version=2,
            payload={
                "payer": auth["from"],
                "authorization": auth,
            },
            accepted=requirements,
        )

        result = await facilitator.verify(payload, requirements)

        assert not result.is_valid
        assert "network" in result.invalid_reason.lower()
