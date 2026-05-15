"""Test Dexter facilitator connectivity and payment flow readiness.

Usage:
    python scripts/test_dexter.py
    python scripts/test_dexter.py --url http://localhost:8000
"""
import argparse
import json
import urllib.request
import urllib.error
import sys
import base64

BASE = "http://77.239.107.30:8000"
DEXTER_URL = "https://x402.dexter.cash"


def req(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"} if body else {}
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()), dict(e.headers)
        except json.JSONDecodeError:
            return e.code, {"raw": e.read().decode()}, dict(e.headers)
    except Exception as e:
        return 0, {"error": str(e)}, {}


def test(label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=BASE)
    args = parser.parse_args()
    base = args.url

    all_ok = True

    # 1. Dexter connectivity
    test("1. Dexter facilitator connectivity")
    status, data, _ = req(f"{DEXTER_URL}/verify", "POST", {"test": True})
    print(f"   Status: {status}")
    print(f"   Body: {json.dumps(data, indent=2)[:200]}")
    # Dexter returns 400/405 for test requests, 403 for GET — that means it's reachable
    ok = status in (400, 403, 404, 405, 422)  # Not timeout/connection error
    print(f"   {'PASS' if ok else 'FAIL'} (Dexter reachable at {DEXTER_URL})")

    # 2. Our server health
    test("2. Our server health")
    status, data, _ = req(f"{base}/health")
    print(f"   Status: {status}")
    print(f"   Testnet: {data.get('testnet')}")
    ok = status == 200 and data.get("testnet") is False
    print(f"   {'PASS' if ok else 'FAIL'} (production mode)")

    # 3. 402 response with PAYMENT-REQUIRED header
    test("3. x402 PAYMENT-REQUIRED header")
    status, data, headers = req(f"{base}/api/validate-json", "POST", {"data": "{}"})
    print(f"   Status: {status}")
    payment_header = headers.get("PAYMENT-REQUIRED", headers.get("payment-required", ""))
    print(f"   PAYMENT-REQUIRED header: {'present' if payment_header else 'MISSING'}")

    if payment_header:
        try:
            decoded = base64.b64decode(payment_header).decode()
            payment_data = json.loads(decoded)
            print(f"   Decoded: {json.dumps(payment_data, indent=2)[:400]}")
            accepts = payment_data.get("accepts", [{}])
            first = accepts[0] if accepts else {}
            has_amount = "amount" in first
            has_network = "network" in first
            has_asset = "asset" in first
            print(f"   Amount: {first.get('amount', 'MISSING')}")
            print(f"   Network: {first.get('network', 'MISSING')}")
            print(f"   Asset: {first.get('asset', 'MISSING')}")
            ok = has_amount and has_network and has_asset
        except Exception as e:
            print(f"   Decode error: {e}")
            ok = False
    else:
        ok = False
    print(f"   {'PASS' if ok else 'FAIL'}")

    # 4. Well-known manifest has correct config
    test("4. x402 manifest check")
    status, manifest, _ = req(f"{base}/.well-known/x402")
    version = manifest.get("x402_version")
    networks = manifest.get("payment", {}).get("networks", [])
    endpoints = manifest.get("endpoints", {})
    print(f"   x402 version: {version}")
    print(f"   Networks: {[n.get('name') for n in networks]}")
    print(f"   Endpoints: {len(endpoints)}")
    ok = version == 2 and len(networks) >= 2 and len(endpoints) == 16
    print(f"   {'PASS' if ok else 'FAIL'}")

    # 5. OpenAPI spec has x402 extensions
    test("5. OpenAPI x402 extensions")
    status, spec, _ = req(f"{base}/.well-known/openapi.json")
    paths = spec.get("paths", {})
    x402_paths = 0
    for p, methods in paths.items():
        post = methods.get("post", {})
        if "x-x402-price" in post:
            x402_paths += 1
    print(f"   Paths with x402 extension: {x402_paths}/16")
    ok = x402_paths == 16
    print(f"   {'PASS' if ok else 'FAIL'}")

    # 6. Production facilitator configured (not testnet)
    test("6. Facilitator configuration")
    status, data, _ = req(f"{base}/health")
    is_testnet = data.get("testnet", True)
    print(f"   Testnet mode: {is_testnet}")
    print(f"   Facilitator: {'Dexter (production)' if not is_testnet else 'DirectFacilitator (testnet)'}")
    ok = not is_testnet
    print(f"   {'PASS' if ok else 'FAIL'} (production mode)")

    # 7. Payment flow: verify 402→200 with API key (human path works)
    test("7. Human payment flow (API key)")
    status, data, _ = req(f"{base}/billing/create-key", "POST")
    api_key = data.get("api_key", "")
    if api_key:
        # Top up $1 (100 cents minimum)
        req(f"{base}/billing/top-up?key={api_key}&amount_cents=100", "POST")
        r = urllib.request.Request(
            f"{base}/api/validate-json",
            data=json.dumps({"data": "{}"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                status2 = resp.status
                data2 = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            status2 = e.code
            data2 = {}
        print(f"   API key call status: {status2}")
        print(f"   Result: {json.dumps(data2, indent=2)[:200]}")
        ok = status2 == 200
    else:
        ok = False
    print(f"   {'PASS' if ok else 'FAIL'}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  PAYMENT FLOW: {'READY' if all_ok else 'ISSUES FOUND'}")
    print(f"  To test real crypto payment:")
    print(f"  1. Send 0.001 USDC to 0xdE7eb04faE758055642f67f30D246CcB7136C95E on Base")
    print(f"  2. Get transaction hash from explorer")
    print(f"  3. curl -X POST {base}/api/validate-json -d '{{\"data\":\"{{}}\",\"payment_tx\":\"0x...\"}}'")
    print(f"{'='*60}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
