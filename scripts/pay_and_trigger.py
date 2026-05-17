#!/usr/bin/env python3
"""
x402 payer script — sends real payment to our API and triggers Bazaar indexing.

Usage:
  1. Create scripts/.env with PRIVATE_KEY=... (NOT the same wallet as PAY_TO!)
  2. Fund this wallet with ~$1 USDC on Base
  3. Run: python scripts/pay_and_trigger.py

What happens:
  - Script calls /api/validate-json with auto-payment of $0.005 USDC
  - Transaction goes through Base mainnet
  - Bazaar (Coinbase) sees the payment → service appears on agentic.market

Security:
  - Private key only in .env (in .gitignore)
  - Use a DIFFERENT wallet from the receiving one
  - Keep minimal USDC on it
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from scripts/ directory
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Also try agent-api/.env for fallback
load_dotenv(Path(__file__).parent.parent / ".env")

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
API_URL = os.getenv("API_URL", "https://agent-api-ai.duckdns.org")

if not PRIVATE_KEY:
    print("ERROR: PRIVATE_KEY not set.")
    print()
    print("Create file agent-api/scripts/.env with:")
    print("  PRIVATE_KEY=0xYOUR_PRIVATE_KEY_FROM_ANOTHER_WALLET")
    print()
    print("Steps:")
    print("  1. Create a new wallet in MetaMask/Rabby")
    print("  2. Export the private key")
    print("  3. Fund it with $1-2 USDC on Base (from exchange or bridge)")
    print("  4. Save the key in scripts/.env")
    sys.exit(1)


async def make_x402_payment():
    """Use the official x402 SDK to pay and call our API."""
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients.httpx import x402AsyncHTTPXClient
    from x402.mechanisms.evm import EthAccountSigner
    from x402.mechanisms.evm.exact.register import register_exact_evm_client

    print(f"Payer wallet: {Account.from_key(PRIVATE_KEY).address}")
    print(f"API: {API_URL}")
    print()

    # Setup x402 client with our wallet as payer
    client = x402Client()
    account = Account.from_key(PRIVATE_KEY)
    register_exact_evm_client(client, EthAccountSigner(account))

    print("Calling /api/validate-json with auto-payment $0.005 USDC...")

    async with x402AsyncHTTPXClient(client, base_url=API_URL) as http:
        response = await http.post(
            "/api/validate-json",
            json={"data": '{"name": "test", "value": 42}'},
        )
        data = response.json()
        print(f"Status: {response.status_code}")
        print(f"Response: {data}")

    print()
    print("DONE! Payment sent. Bazaar will index the service within minutes.")
    print("Check: https://agentic.market (search for 'AI Agent API')")


async def check_402_first():
    """Verify the API returns 402 before we try to pay."""
    import httpx

    print("Verifying API returns 402 without payment...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_URL}/api/validate-json",
            json={"data": "{}"},
        )
        if resp.status_code == 402:
            print("  OK — API requires payment (402)")
        else:
            print(f"  UNEXPECTED — status {resp.status_code}, expected 402")
    print()


async def main():
    await check_402_first()
    await make_x402_payment()


if __name__ == "__main__":
    asyncio.run(main())
