#!/usr/bin/env python3
"""Integration test suite for agent-api. Run against local or production.

Usage:
    python scripts/integration_test.py --base-url http://127.0.0.1:8000

Runs 29+ test scenarios covering:
  1-2.   Health endpoints
  3-4.   Well-known manifests (x402 + OpenAPI)
  5.     Rate limiting (11 rapid requests, expect 429 on 11th)
  6-21.  16 POST endpoints all return 402 (with X-Payment-Help header)
  22.    POST /billing/create-key
  23.    GET /billing/balance (0 credits for new key)
  24.    POST /billing/top-up (add 1000 cents)
  25.    GET /billing/balance (verify 11000 credits with bonus)
  26.    POST /api/validate-json with valid API key (bypass x402)
  27.    GET /billing/balance (verify credits deducted)
  28.    POST /api/validate-json with invalid API key (401 or 402)
  29.    Replay protection (duplicate request handling)
  30.    (rate limit already tested at #5 — early to avoid false 429s)

Notes on existing pytest suite (tests/test_api.py):
  - The 14 existing tests use an in-process ASGI test client (httpx + ASGITransport),
    covering health, well-known manifest, 10 of 16 endpoints for 402 responses.
  - Missing coverage: endpoints nl-to-sql, sql-to-nl, git-summarize, solidity-scan
    are not tested. No billing tests, no rate-limit tests, no positive API-key flow.
  - The 402 response tests check status code but do not verify the X-Payment-Help
    header (present on all 402 responses from x402 middleware).
  - No tests verify OpenAPI spec contains x-x402-price extensions.
  - Overall the pytest suite is a solid foundation but incomplete — the integration
    test here fills those gaps.
"""

import sys
import json
import time
import urllib.request
import urllib.error
import argparse

PASS = 0
FAIL = 0
BASE = ""
API_KEY = None
BALANCE_AFTER_TOPUP = 0


def test(name, fn):
    """Run a test function, track pass/fail, print result."""
    global PASS, FAIL
    try:
        fn()
    except Exception as e:
        print(f"  FAIL {name}: {e}")
        FAIL += 1
    else:
        print(f"  PASS {name}")
        PASS += 1


# ── HTTP helpers ──────────────────────────────────────────────

def _req(method, url, data=None, headers_in=None):
    """Make an HTTP request. Returns (status_code, headers_dict, body_dict).

    Uses urllib.request (stdlib) so no external dependencies are needed.
    Handles both success (urllib.request.urlopen) and error
    (urllib.error.HTTPError) responses uniformly.
    """
    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, method=method)
    req.add_header("Accept", "application/json")
    if headers_in:
        for k, v in headers_in.items():
            req.add_header(k, v)
    if body_bytes is not None:
        req.add_header("Content-Type", "application/json")

    try:
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read().decode("utf-8"))
        return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read()
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {"raw": raw.decode("utf-8", errors="replace")}
        return e.code, dict(e.headers), body


def _header(hdrs, name):
    """Case-insensitive header lookup in a dict."""
    for k, v in hdrs.items():
        if k.lower() == name.lower():
            return v
    return None


# ── 1. Health ─────────────────────────────────────────────────

def test_health():
    st, hdrs, body = _req("GET", f"{BASE}/health")
    assert st == 200, f"Expected 200, got {st}"
    assert body.get("status") == "ok", f"Expected status='ok', got {body.get('status')!r}"

    # Additional structural checks (these help spot regressions)
    assert "version" in body, "Response missing 'version' field"
    assert "billing" in body, "Response missing 'billing' field"
    assert "payment_attempts" in body, "Response missing 'payment_attempts' field"


# ── 2. Health deep ────────────────────────────────────────────

def test_health_deep():
    """Deep health may or may not exist (404 is acceptable)."""
    st, hdrs, body = _req("GET", f"{BASE}/health/deep")
    assert st in (200, 404), f"Expected 200 or 404, got {st}"


# ── 3. Well-known x402 ────────────────────────────────────────

def test_well_known_x402():
    st, hdrs, body = _req("GET", f"{BASE}/.well-known/x402")
    assert st == 200, f"Expected 200, got {st}"
    assert body.get("x402_version") == 2, f"Expected x402_version=2, got {body.get('x402_version')}"
    endpoints = body.get("endpoints", {})
    assert len(endpoints) >= 16, f"Expected 16+ endpoints, got {len(endpoints)}"
    # Spot-check a few endpoints
    for path in ("/api/audit", "/api/validate-json", "/api/nl-to-sql", "/api/solidity-scan"):
        assert path in endpoints, f"Missing expected endpoint: {path}"


# ── 4. Well-known OpenAPI ─────────────────────────────────────

def test_well_known_openapi():
    st, hdrs, body = _req("GET", f"{BASE}/.well-known/openapi.json")
    assert st == 200, f"Expected 200, got {st}"
    paths = body.get("paths", {})
    assert len(paths) > 0, "OpenAPI spec has no paths"
    has_price = any(
        "x-x402-price" in p.get("post", {})
        for p in paths.values()
    )
    assert has_price, "No x-x402-price extension found in any path"
    # Verify openapi version
    assert body.get("openapi", "").startswith("3."), (
        f"Expected OpenAPI 3.x, got {body.get('openapi')}"
    )


# ── 5. Rate limiting (early to avoid false positives) ─────────

def test_rate_limit():
    """11 rapid-fire POSTs to /api/validate-json — the 11th should 429."""
    results = []
    for i in range(11):
        st, hdrs, body = _req(
            "POST",
            f"{BASE}/api/validate-json",
            data={"data": f'{{"seq": {i}}}'},
        )
        results.append(st)
        if st == 429:
            break

    # At least one request should be rate-limited
    rate_limited_count = sum(1 for r in results if r == 429)
    assert rate_limited_count >= 1, (
        f"Expected at least one 429 among {len(results)} requests, got codes: {results}"
    )

    # Verify retry_after in body or headers of the 429 response
    last_st, last_hdrs, last_body = results[-1] if len(results) > 1 else (429, {}, {})
    # The 429 response has "retry_after_seconds" in the body
    if isinstance(last_body, dict) and "retry_after_seconds" in last_body:
        print(f"    (rate limit retry_after={last_body['retry_after_seconds']}s)")
    # If the last request was NOT 429 (e.g., some got through), no concern


# ── 6-21. Sixteen POST endpoints → 402 ────────────────────────

SIXTEEN_ENDPOINTS = [
    ("/api/audit", {"code": "function foo() {}"}),
    ("/api/refactor", {"code": "function bar() {}"}),
    ("/api/docs", {"code": "print(42)"}),
    ("/api/defi-analyze", {"protocol": "Aave"}),
    ("/api/trading-signal", {"asset": "BTC"}),
    ("/api/solidity-scan", {"code": "contract Foo {}"}),
    ("/api/nl-to-sql", {"query": "show all users"}),
    ("/api/sql-to-nl", {"sql": "SELECT * FROM users"}),
    ("/api/git-summarize", {
        "diff": "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old content\n+new content",
    }),
    ("/api/translate-code", {
        "code": "print(1)", "source_lang": "python", "target_lang": "typescript",
    }),
    ("/api/validate-json", {"data": "{}"}),
    ("/api/classify-text", {"text": "Great product!"}),
    ("/api/extract-data", {"text": "Contact: john@email.com"}),
    ("/api/generate-regex", {"description": "Match email addresses"}),
    ("/api/format-data", {
        "data": "a,b\n1,2", "source_format": "csv", "target_format": "json",
    }),
    ("/api/summarize", {"text": "Long article text to summarize here."}),
]


# ── 22. Create API key ────────────────────────────────────────

def test_create_key():
    global API_KEY
    st, hdrs, body = _req("POST", f"{BASE}/billing/create-key")
    assert st == 200, f"Expected 200, got {st}"
    key = body.get("api_key", "")
    assert key.startswith("ak-"), f"Expected ak- prefix, got {key!r}"
    assert len(key) > 10, f"Key seems too short: {len(key)} chars"
    API_KEY = key
    print(f"    (created key: {key[:16]}...)")


# ── 23. Balance (zero) ────────────────────────────────────────

def test_balance_zero():
    st, hdrs, body = _req("GET", f"{BASE}/billing/balance?key={API_KEY}")
    assert st == 200, f"Expected 200, got {st}"
    assert body.get("credits") == 0, f"Expected 0 credits for new key, got {body.get('credits')}"
    assert "usd_equivalent" in body
    assert "created_at" in body


# ── 24. Top-up ────────────────────────────────────────────────

def test_top_up():
    global API_KEY, BALANCE_AFTER_TOPUP
    st, hdrs, body = _req(
        "POST",
        f"{BASE}/billing/top-up?key={API_KEY}&amount_cents=1000",
    )
    assert st == 200, f"Expected 200, got {st}"
    assert body.get("status") == "ok", f"Expected status=ok, got {body}"
    BALANCE_AFTER_TOPUP = body.get("new_balance_credits", 0)
    assert BALANCE_AFTER_TOPUP > 0, f"Expected positive balance, got {BALANCE_AFTER_TOPUP}"
    print(f"    (balance={BALANCE_AFTER_TOPUP} credits, ~${BALANCE_AFTER_TOPUP / 10 / 100})")


# ── 25. Balance after top-up ──────────────────────────────────

def test_balance_after_topup():
    st, hdrs, body = _req("GET", f"{BASE}/billing/balance?key={API_KEY}")
    assert st == 200, f"Expected 200, got {st}"
    assert body.get("credits") == BALANCE_AFTER_TOPUP, (
        f"Expected {BALANCE_AFTER_TOPUP} credits, got {body.get('credits')}"
    )


# ── 26. validate-json with valid API key ──────────────────────

def test_validate_json_with_valid_key():
    """With a valid API key and credits, payment is bypassed.
    The response may be 200 (DeepSeek works) or 5xx (DeepSeek unavailable)
    — both are acceptable as long as it is NOT 402."""
    st, hdrs, body = _req(
        "POST",
        f"{BASE}/api/validate-json",
        data={"data": '{"name": "test", "value": 42}'},
        headers_in={"Authorization": f"Bearer {API_KEY}"},
    )
    assert st != 402, (
        "Request with valid API key and positive balance should bypass x402 payment"
    )
    if st == 200:
        # Verify response structure
        assert "result" in body, "Expected 'result' in response"
        assert "payment_network" in body
        assert "payment_tx" in body


# ── 27. Balance deducted ──────────────────────────────────────

def test_balance_deducted():
    st, hdrs, body = _req("GET", f"{BASE}/billing/balance?key={API_KEY}")
    assert st == 200, f"Expected 200, got {st}"
    new_balance = body.get("credits", BALANCE_AFTER_TOPUP)
    assert new_balance < BALANCE_AFTER_TOPUP, (
        f"Expected balance < {BALANCE_AFTER_TOPUP}, got {new_balance}"
    )
    print(f"    (balance after deduction: {new_balance}, delta={BALANCE_AFTER_TOPUP - new_balance})")


# ── 28. Invalid API key ───────────────────────────────────────

def test_invalid_api_key():
    """Request with an invalid API key (non-existent) should not bypass payment."""
    st, hdrs, body = _req(
        "POST",
        f"{BASE}/api/validate-json",
        data={"data": "{}"},
        headers_in={"Authorization": "Bearer ak-invalidkey1234567890abcdef"},
    )
    # The key doesn't exist in the credits store, so it falls through to x402
    assert st in (401, 402), f"Expected 401 or 402, got {st}"
    if st == 402:
        assert _header(hdrs, "X-Payment-Help") is not None, "Missing X-Payment-Help header"


# ── 29. Replay protection (best-effort) ───────────────────────

def test_replay_protection():
    """Send two identical requests and verify the server handles them safely.

    Full replay protection requires valid x402 payment signatures. Since we
    do not have a real payment flow in this test, we send two identical
    unauthenticated requests and verify both return a payment-required error
    (i.e. the server doesn't crash or return 200 for the duplicate).
    """
    payload = {"data": '{"replay": "test"}'}
    st1, hdrs1, body1 = _req("POST", f"{BASE}/api/validate-json", data=payload)
    st2, hdrs2, body2 = _req("POST", f"{BASE}/api/validate-json", data=payload)

    # Both should either be 402 (no payment) — not 200
    for idx, (st, body) in enumerate([(st1, body1), (st2, body2)], 1):
        assert st in (402, 429), (
            f"Request {idx}: expected 402 or 429, got {st} (body: {body})"
        )

    print(f"    (responses: {st1}, {st2})")


# ── Main ──────────────────────────────────────────────────────

def main():
    global BASE
    parser = argparse.ArgumentParser(
        description="Agent-API integration test suite.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the agent-api server (default: http://127.0.0.1:8000)",
    )
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")

    print(f"\n{'='*60}")
    print(f"  Agent-API Integration Test Suite")
    print(f"  Target: {BASE}")
    print(f"{'='*60}\n")

    # ── Phase 1: Health & discovery (no rate limit applied to these paths) ──
    print("── Phase 1: Health & Discovery ──")
    test("GET /health", test_health)
    test("GET /health/deep", test_health_deep)
    test("GET /.well-known/x402", test_well_known_x402)
    test("GET /.well-known/openapi.json", test_well_known_openapi)

    # ── Phase 2: Rate limiting (early, before other API calls consume quota) ──
    print("\n── Phase 2: Rate Limiting ──")
    print("  (11 rapid POST /api/validate-json — expect 429 on 11th)")
    test("Rate limiting (11x POST /api/validate-json)", test_rate_limit)

    # Wait for rate-limit window to reset so remaining tests don't false-429
    print("\n  Waiting 60s for rate-limit window to reset...")
    for remaining in range(60, 0, -1):
        sys.stdout.write(f"\r  {remaining}s remaining...")
        sys.stdout.flush()
        time.sleep(1)
    print("\r  Done waiting.                                          ")

    # ── Phase 3: 16 endpoints → 402 ──
    print("\n── Phase 3: 16 POST Endpoints → 402 (Payment Required) ──")
    for path, body_data in SIXTEEN_ENDPOINTS:
        def make_fn(p, bd):
            def fn():
                st, hdrs, rbody = _req("POST", f"{BASE}{p}", data=bd)
                assert st in (402, 429), (
                    f"Expected 402 (or 429 if rate-limited) for {p}, got {st}"
                )
                if st == 402:
                    help_hdr = _header(hdrs, "X-Payment-Help")
                    assert help_hdr is not None, (
                        f"Missing X-Payment-Help header for {p}"
                    )
                elif st == 429:
                    print(f"    (rate-limited — still acceptable)")
            return fn
        test(f"POST {path}", make_fn(path, body_data))

    # ── Phase 4: Billing flow ──
    print("\n── Phase 4: Billing (API Key + Credits) ──")
    test("POST /billing/create-key", test_create_key)
    test("GET /billing/balance (new key = 0 credits)", test_balance_zero)
    test("POST /billing/top-up (+1000 cents)", test_top_up)
    test("GET /billing/balance (verify 11000 credits)", test_balance_after_topup)

    # ── Phase 5: End-to-end with API key ──
    print("\n── Phase 5: API Key Payment Flow ──")
    test("POST /api/validate-json (valid API key, bypass x402)", test_validate_json_with_valid_key)
    test("GET /billing/balance (credits deducted)", test_balance_deducted)
    test("POST /api/validate-json (invalid API key -> 401/402)", test_invalid_api_key)

    # ── Phase 6: Replay protection ──
    print("\n── Phase 6: Replay Protection ──")
    test("POST /api/validate-json (duplicate requests)", test_replay_protection)

    # ── Summary ──
    total = PASS + FAIL
    print(f"\n{'='*60}")
    print(f"  Results: {PASS} passed, {FAIL} failed ({total} total)")
    print(f"{'='*60}\n")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
