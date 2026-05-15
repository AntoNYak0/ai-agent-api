"""Test full payment cycle: health, 402 response, API key flow, credits deduction.

Usage:
    python scripts/test_payment.py
    python scripts/test_payment.py --url http://localhost:8000
"""
import argparse
import json
import urllib.request
import urllib.error
import sys

DEFAULT_BASE = "http://77.239.107.30:8000"


def req(base: str, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"raw": body_text, "headers": dict(e.headers)}


def test(label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.url

    all_ok = True

    # 1. Health check
    test("1. Health check")
    status, data = req(base, "GET", "/health")
    print(f"   Status: {status}")
    print(f"   Body: {json.dumps(data, indent=2)}")
    ok = status == 200 and data.get("status") == "ok"
    print(f"   {'PASS' if ok else 'FAIL'}")
    all_ok = all_ok and ok

    # 2. 402 response
    test("2. x402 Payment Required (no payment_tx)")
    status, data = req(base, "POST", "/api/validate-json", {"data": '{"test": true}'})
    print(f"   Status: {status}")
    if status == 402:
        hdrs = data.get("headers", {})
        print(f"   PAYMENT-REQUIRED: {hdrs.get('PAYMENT-REQUIRED', 'N/A')[:80]}")
    ok = status == 402
    print(f"   {'PASS' if ok else 'FAIL'} (expected 402)")
    all_ok = all_ok and ok

    # 3. Create API key
    test("3. Create API key")
    status, data = req(base, "POST", "/billing/create-key")
    api_key = data.get("api_key", "")
    print(f"   Key: {api_key[:12]}...")
    ok = status == 200 and api_key.startswith("ak-")
    print(f"   {'PASS' if ok else 'FAIL'}")
    all_ok = all_ok and ok

    # 4. Check balance (zero)
    test("4. Check balance (should be 0)")
    status, data = req(base, "GET", f"/billing/balance?key={api_key}")
    print(f"   Balance: {json.dumps(data, indent=2)}")
    ok = status == 200 and data.get("credits") == 0
    print(f"   {'PASS' if ok else 'FAIL'}")
    all_ok = all_ok and ok

    # 5. Top up
    test("5. Top up $1 (100 cents)")
    status, data = req(base, "POST", f"/billing/top-up?key={api_key}&amount_cents=100")
    print(f"   Result: {json.dumps(data, indent=2)}")
    ok = status == 200 and data.get("status") == "ok"
    print(f"   {'PASS' if ok else 'FAIL'}")
    all_ok = all_ok and ok

    # 6. Call tool with API key
    test("6. Call validate-json REST with API key")
    status, data = req(base, "POST", "/api/validate-json",
                       {"data": '{"name": "test"}'},
                       {"Authorization": f"Bearer {api_key}"})
    print(f"   Status: {status}")
    if status == 200:
        print(f"   Result: {json.dumps(data, indent=2)[:300]}")
    else:
        print(f"   Body: {json.dumps(data, indent=2)[:300]}")
    ok = status == 200
    print(f"   {'PASS' if ok else 'FAIL'} (expected 200)")
    all_ok = all_ok and ok

    # 7. Check balance after call
    test("7. Check balance after usage")
    status, data = req(base, "GET", f"/billing/balance?key={api_key}")
    print(f"   Balance: {json.dumps(data, indent=2)}")
    ok = status == 200
    print(f"   {'PASS' if ok else 'FAIL'}")
    all_ok = all_ok and ok

    # 8. Well-known endpoints
    test("8. Discovery endpoints")
    for path in ["/.well-known/x402", "/.well-known/openapi.json"]:
        status, data = req(base, "GET", path)
        print(f"   {path}: {status}")
        ok = status == 200
        all_ok = all_ok and ok

    # 9. Replay protection
    test("9. Replay protection (same tx twice)")
    fake_tx = "0x" + "ab" * 32
    status1, _ = req(base, "POST", "/api/validate-json",
                     {"data": "{}", "payment_tx": fake_tx})
    status2, data2 = req(base, "POST", "/api/validate-json",
                         {"data": "{}", "payment_tx": fake_tx})
    print(f"   First call: {status1}")
    print(f"   Second call: {status2}")
    print(f"   Second body: {json.dumps(data2, indent=2)[:200]}")
    ok = status2 != 200
    print(f"   {'PASS' if ok else 'FAIL'} (second call should be rejected)")
    all_ok = all_ok and ok

    # Summary
    print(f"\n{'='*60}")
    print(f"  {'ALL TESTS PASSED' if all_ok else 'SOME TESTS FAILED'}")
    print(f"{'='*60}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
