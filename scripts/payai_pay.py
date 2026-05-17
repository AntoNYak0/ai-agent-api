"""Pay via PayAI facilitator (gasless EIP-3009) + API call."""

import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from scripts/ directory, then project root
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
API_URL = os.getenv("API_URL", "https://agent-api-ai.duckdns.org")

if not PRIVATE_KEY:
    print("Need PRIVATE_KEY in scripts/.env")
    sys.exit(1)


async def main():
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients.httpx import x402HttpxClient
    from x402.mechanisms.evm import EthAccountSigner
    from x402.mechanisms.evm.exact.register import register_exact_evm_client

    account = Account.from_key(PRIVATE_KEY)
    print(f"Payer: {account.address}")
    print(f"API:   {API_URL}")

    # Setup x402 client
    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(account))

    print("Calling /api/validate-json via PayAI facilitator (gasless)...")

    async with x402HttpxClient(client, base_url=API_URL) as http:
        resp = await http.post(
            "/api/validate-json",
            json={"data": '{"name":"PayAI","status":"listed"}'},
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:300]}")
        if resp.status_code == 200:
            print("SUCCESS! PayAI processed the payment.")
            print("Our service should now appear in PayAI discovery catalog.")


asyncio.run(main())