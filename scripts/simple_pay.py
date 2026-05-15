"""Платёж + вызов API для Bazaar индексации."""

import sys, json, base64, httpx
from web3 import Web3

PRIVATE_KEY = "[REDACTED-COMPROMISED-KEY]"
API_URL = "http://77.239.107.30:8000"
RECEIVER = "0xdE7eb04faE758055642f67f30D246CcB7136C95E"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
RPC_URL = "https://mainnet.base.org"
AMOUNT = 5000  # $0.005 USDC

w3 = Web3(Web3.HTTPProvider(RPC_URL))
acct = w3.eth.account.from_key(PRIVATE_KEY)

USDC_ABI = json.loads('[{"constant":false,"inputs":[{"name":"to","type":"address"},{"name":"value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}]')

print(f"From:    {acct.address}")
print(f"To:      {RECEIVER}")
print(f"Amount:  {AMOUNT/1e6} USDC")
print()

# Step 1: Send USDC
usdc = w3.eth.contract(address=USDC_BASE, abi=USDC_ABI)
tx = usdc.functions.transfer(RECEIVER, AMOUNT).build_transaction({
    'chainId': 8453, 'gas': 70000,
    'maxFeePerGas': w3.eth.gas_price,
    'maxPriorityFeePerGas': w3.to_wei(0.001, 'gwei'),
    'nonce': w3.eth.get_transaction_count(acct.address),
})
print("Sending USDC...")
signed = acct.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
tx_hex = '0x' + tx_hash.hex()
print(f"TX: {tx_hex}")

print("Waiting...")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
if receipt.status != 1:
    print("TX FAILED!")
    sys.exit(1)
print(f"Confirmed block {receipt.blockNumber}")
print()

# Step 2: Call API with x402 payment
# PaymentPayload V2 format, base64-encoded in PAYMENT-SIGNATURE header
payload = {
    "x402Version": 2,
    "payload": {
        "payer": acct.address,
        "transactionHash": tx_hex,
    },
    "accepted": {
        "scheme": "exact",
        "network": "eip155:8453",
        "asset": USDC_BASE,
        "amount": str(AMOUNT),
        "payTo": RECEIVER,
        "maxTimeoutSeconds": 300,
    },
}

header_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
print("Calling API with PAYMENT-SIGNATURE...")
resp = httpx.post(
    f"{API_URL}/api/validate-json",
    json={"data": '{"test": true, "status": "x402 micropayment works!"}'},
    headers={"Content-Type": "application/json", "PAYMENT-SIGNATURE": header_b64},
    timeout=60,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Response: {json.dumps(data, indent=2)[:300]}")
    print()
    print("SUCCESS! Payment went through x402.")
    print("Bazaar will index this service within minutes.")
    print("Check: https://agentic.market")
else:
    print(f"Body: {resp.text[:500]}")
