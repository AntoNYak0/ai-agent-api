#!/usr/bin/env python3
"""E2E testnet verification for EIP-3009 receiveWithAuthorization.

Tests the full DirectFacilitator EIP-3009 flow:
  1. Off-chain EIP-712 signature generation
  2. verify() — ecrecover + authorizationState eth_call
  3. settle() — server-submitted receiveWithAuthorization (requires private key)

Usage:
  # Dry-run (no settlement): verify only
  python scripts/eip3009_testnet_verify.py --mode verify

  # Full settlement (needs FACILITATOR_EIP3009_PRIVATE_KEY in .env):
  python scripts/eip3009_testnet_verify.py --mode settle

  # Test against Base Sepolia testnet:
  python scripts/eip3009_testnet_verify.py --mode verify --network eip155:84532

Requirements:
  pip install web3 eth-account
"""

import argparse
import asyncio
import json
import os
import os
import sys
import time
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.facilitator import (
    DirectFacilitator,
    EIP3009_DOMAINS,
    EIP3009_MIN_PAYMENT_MICROUNITS,
)
from x402.schemas import PaymentPayload, PaymentRequirements
from eth_account import Account
from eth_account.messages import encode_typed_data


# ── Test accounts (Anvil/Hardhat default keys — NEVER use in production) ────
TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def green(s):
    return f"\033[92m{s}\033[0m"


def red(s):
    return f"\033[91m{s}\033[0m"


def yellow(s):
    return f"\033[93m{s}\033[0m"


def bold(s):
    return f"\033[1m{s}\033[0m"


def build_eip3009_authorization(
    *,
    private_key: str,
    pay_to: str,
    value_microunits: int = 50_000,
    network: str = "eip155:8453",
) -> dict:
    """Build and sign an EIP-3009 ReceiveWithAuthorization payload.

    Returns a dict with from, to, value, validAfter, validBefore,
    nonce, v, r, s — ready for the `authorization` field in x402 payload.
    """
    domain = EIP3009_DOMAINS[network]
    signer = Account.from_key(private_key)
    now = int(time.time())
    nonce = os.urandom(32)  # bytes32 — 32 bytes exactly

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
            "validAfter": now - 3600,  # 1 hour ago
            "validBefore": now + 86400,  # 24 hours from now
            "nonce": "0x" + nonce.hex(),
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


def print_separator(title: str):
    print(f"\n{bold('─' * 60)}")
    print(f"  {bold(title)}")
    print(f"{bold('─' * 60)}")


def print_auth(auth: dict):
    print(f"  from:        {auth['from']}")
    print(f"  to:          {auth['to']}")
    print(f"  value:       {auth['value']} microunits (${int(auth['value'])/1_000_000:.4f})")
    print(f"  validAfter:  {auth['validAfter']} ({datetime.fromtimestamp(auth['validAfter'])})")
    print(f"  validBefore: {auth['validBefore']} ({datetime.fromtimestamp(auth['validBefore'])})")
    print(f"  nonce:       {auth['nonce'][:30]}...")
    print(f"  v:           {auth['v']}")
    print(f"  r:           {auth['r'][:30]}...")
    print(f"  s:           {auth['s'][:30]}...")


async def test_verify(facilitator: DirectFacilitator, network: str, pay_to: str):
    """Test the verify() path: EIP-712 ecrecover + authorizationState."""
    print_separator("Phase 1: verify() — EIP-712 ecrecover + authorizationState")

    print(f"\n  {yellow('Generating EIP-3009 authorization...')}")
    auth = build_eip3009_authorization(
        private_key=TEST_PRIVATE_KEY,
        pay_to=pay_to,
        network=network,
        value_microunits=50_000,  # $0.05
    )
    print_auth(auth)

    requirements = PaymentRequirements(
        scheme="usdc",
        network=network,
        asset=EIP3009_DOMAINS[network]["verifyingContract"],
        amount="50000",
        payTo=pay_to,
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

    print(f"\n  {yellow('Calling facilitator.verify()...')}")
    result = await facilitator.verify(payload, requirements)

    if result.is_valid:
        print(f"\n  {green('✓ VERIFY PASSED')}")
        print(f"    payer: {result.payer}")
        return auth  # return auth for settlement phase
    else:
        print(f"\n  {red('✗ VERIFY FAILED')}")
        print(f"    reason:  {result.invalid_reason}")
        print(f"    message: {result.invalid_message}")
        return None


async def test_settle(facilitator: DirectFacilitator, network: str, pay_to: str, auth: dict):
    """Test the settle() path: submit receiveWithAuthorization on-chain."""
    print_separator("Phase 2: settle() — on-chain receiveWithAuthorization")

    if not settings.facilitator_eip3009_private_key:
        print(f"\n  {red('✗ FACILITATOR_EIP3009_PRIVATE_KEY not configured')}")
        print(f"  Set it in .env or environment to test settlement.")
        return False

    requirements = PaymentRequirements(
        scheme="usdc",
        network=network,
        asset=EIP3009_DOMAINS[network]["verifyingContract"],
        amount="50000",
        payTo=pay_to,
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

    print(f"\n  {yellow('Calling facilitator.settle()...')}")
    print(f"  Server will submit receiveWithAuthorization transaction.")
    print(f"  Estimated gas: ~55,000 on {network}")

    result = await facilitator.settle(payload, requirements)

    if result.success:
        print(f"\n  {green('✓ SETTLE PASSED')}")
        print(f"    payer:       {result.payer}")
        print(f"    transaction: {result.transaction}")
        print(f"    network:     {result.network}")
        print(f"    amount:      {result.amount}")
        return True
    else:
        print(f"\n  {red('✗ SETTLE FAILED')}")
        print(f"    reason:  {result.error_reason}")
        print(f"    message: {result.error_message}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="EIP-3009 testnet verification")
    parser.add_argument(
        "--mode",
        choices=["verify", "settle"],
        default="verify",
        help="verify only, or verify+settle",
    )
    parser.add_argument(
        "--network",
        choices=list(EIP3009_DOMAINS.keys()),
        default="eip155:8453",
        help="Network for EIP-3009 domain",
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use testnet mode (auto-approve, no RPC calls)",
    )
    args = parser.parse_args()

    network = args.network
    pay_to = settings.pay_to_address_evm
    testnet = args.testnet

    if not testnet and network == "eip155:8453":
        print(f"\n  {yellow('⚠ Running against Base MAINNET')}")
        print(f"  RPC calls will be made to real endpoints.")
        print(f"  authorizationState eth_call is read-only — safe.")
        print(f"  Settlement requires real USDC allowance.")
    elif not testnet and network == "eip155:84532":
        print(f"\n  {green('✓ Running against Base SEPOLIA (testnet)')}")

    facilitator = DirectFacilitator(testnet=testnet, pay_to=pay_to)

    print_separator("EIP-3009 Testnet Verification")
    print(f"  network:   {network}")
    print(f"  domain:    {EIP3009_DOMAINS[network]['name']} v{EIP3009_DOMAINS[network]['version']}")
    print(f"  USDC:      {EIP3009_DOMAINS[network]['verifyingContract']}")
    print(f"  pay_to:    {pay_to}")
    print(f"  testnet:   {testnet}")
    print(f"  signer:    {TEST_ADDRESS}")

    # Phase 1: Verify
    auth = await test_verify(facilitator, network, pay_to)

    if not auth:
        print(f"\n{red('Verification failed — stopping.')}")
        return 1

    # Phase 2: Settle (if requested)
    if args.mode == "settle":
        ok = await test_settle(facilitator, network, pay_to, auth)
        if not ok:
            return 1

    print_separator("All tests passed")
    print(f"\n  {green('✓ EIP-3009 flow verified')}")
    print(f"  Next: deploy to VPS and test with real USDC on Base Sepolia")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
