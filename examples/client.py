#!/usr/bin/env python3
"""AI Agent API — minimal Python client.

Shows both payment methods:
  1. API key (human developers) — create key, top up, call
  2. x402 USDC (AI agents) — send USDC, call with payment-signature

Usage:
    python client.py                          # API key flow (guided)
    python client.py --key ak-YOUR_KEY         # Use existing key
    python client.py --tx 0xYOUR_TX_HASH      # x402 payment flow
"""
import argparse
import json
import urllib.request
import urllib.error
import sys

BASE = "http://77.239.107.30:8000"


def req(method: str, path: str, body=None, headers=None, timeout=60):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    hdrs = headers or {}
    if body:
        hdrs.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()), dict(e.headers)
        except json.JSONDecodeError:
            return e.code, {"error": e.read().decode()}, dict(e.headers)


def main():
    parser = argparse.ArgumentParser(description="AI Agent API client")
    parser.add_argument("--key", help="API key (ak-...)")
    parser.add_argument("--tx", help="Transaction hash for x402 payment")
    parser.add_argument("--service", default="validate-json",
                        help="Service to call (default: validate-json)")
    parser.add_argument("--data", default='{"name":"test"}',
                        help="Input data for the service")
    args = parser.parse_args()

    print("AI Agent API Client")
    print(f"  Service: {args.service}")
    print(f"  Base URL: {BASE}")
    print()

    api_key = args.key
    payment_tx = args.tx

    # ── Use existing API key ──────────────────────────────────
    if api_key:
        print("1. Using API key...")
        status, data, _ = req("GET", f"/billing/balance?key={api_key}")
        if status == 404:
            print("   Invalid key. Create one with: python client.py")
            return 1
        bal = data.get("credits", 0)
        print(f"   Balance: {bal} credits (${data.get('usd_equivalent', 0)})")
        if bal <= 0:
            print("   No credits. Top up at /billing/top-up")
            return 1

        print(f"2. Calling {args.service}...")
        status, data, headers = req(
            "POST", f"/api/{args.service}",
            body={"data": args.data},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if status == 200:
            print("   Success!")
            result = data.get("result", json.dumps(data))
            try:
                parsed = json.loads(result)
                print(json.dumps(parsed, indent=2))
            except (json.JSONDecodeError, TypeError):
                print(result[:500])
        else:
            print(f"   Error {status}: {data}")
            return 1

        # Show updated balance
        _, data, _ = req("GET", f"/billing/balance?key={api_key}")
        print(f"\n3. Updated balance: {data['credits']} credits")

    # ── Use x402 payment (tx hash) ────────────────────────────
    elif payment_tx:
        print("1. Using transaction hash for x402 payment...")
        print(f"   TX: {payment_tx[:20]}...")

        # Build payment-signature header
        import base64
        payment_payload = {
            "x402Version": 2,
            "payload": {
                "transactionHash": payment_tx,
                "payer": "python-client",
            },
            "accepted": {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "amount": "1000",
                "payTo": "0xdE7eb04faE758055642f67f30D246CcB7136C95E",
                "maxTimeoutSeconds": 300,
            }
        }
        encoded = base64.b64encode(json.dumps(payment_payload).encode()).decode()
        print(f"   Payment-signature: {encoded[:60]}...")

        print(f"2. Calling {args.service}...")
        status, data, headers = req(
            "POST", f"/api/{args.service}",
            body={"data": args.data},
            headers={"payment-signature": encoded},
        )
        if status == 200:
            print("   Payment verified! Result:")
            result = data.get("result", json.dumps(data))
            try:
                parsed = json.loads(result)
                print(json.dumps(parsed, indent=2))
            except (json.JSONDecodeError, TypeError):
                print(result[:500])
        else:
            print(f"   Error {status}: {data}")
            return 1

    # ── No payment — show 402 flow ────────────────────────────
    else:
        print("1. No payment provided. Getting 402 Payment Required...")
        status, data, headers = req(
            "POST", f"/api/{args.service}",
            body={"data": args.data},
        )
        if status == 402:
            print("   Got 402 Payment Required!")
            msg = data.get("message", "")
            if msg:
                print(f"\n   How to pay:\n   {msg}\n")
            print("2. Create free API key:")
            status2, key_data, _ = req("POST", "/billing/create-key")
            if status2 == 200:
                api_key = key_data["api_key"]
                print(f"   Key: {api_key}")
                print(f"   3. Top up: POST /billing/top-up?key={api_key}&amount_cents=100")
                print(f"   4. Then: python client.py --key {api_key}")
        else:
            print(f"   Unexpected status: {status}")
            print(json.dumps(data, indent=2)[:500])

    return 0


if __name__ == "__main__":
    sys.exit(main())
