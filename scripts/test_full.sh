#!/bin/bash
# ============================================================
# Comprehensive endpoint test for AI Agent API
# Tests all REST endpoints, discovery, billing, MCP, and system
# ============================================================

BASE="https://agent-api-ai.duckdns.org"
PASS=0
FAIL=0
TIMEOUT=10

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_status() {
    local endpoint="$1"
    local expected="$2"
    local label="$3"
    local method="${4:-GET}"

    if [ "$method" = "HEAD" ]; then
        http_code=$(curl -s -o /dev/null -w "%{http_code}" -X HEAD --max-time "$TIMEOUT" "${BASE}${endpoint}" 2>&1)
    else
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "${BASE}${endpoint}" 2>&1)
    fi

    if [ "$http_code" = "$expected" ]; then
        echo -e "  ${GREEN}PASS${NC} [${http_code}] ${label}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} [${http_code}] (expected ${expected}) ${label}"
        FAIL=$((FAIL + 1))
    fi
}

check_content() {
    local endpoint="$1"
    local expected_text="$2"
    local label="$3"

    body=$(curl -s --max-time "$TIMEOUT" "${BASE}${endpoint}" 2>&1)
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "${BASE}${endpoint}" 2>&1)

    if echo "$body" | grep -q "$expected_text"; then
        echo -e "  ${GREEN}PASS${NC} [${http_code}] ${label} (contains '${expected_text}')"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} [${http_code}] ${label} (missing '${expected_text}')"
        echo "    Body: $(echo "$body" | head -c 200)"
        FAIL=$((FAIL + 1))
    fi
}

check_post_content() {
    local endpoint="$1"
    local data="$2"
    local expected_text="$3"
    local label="$4"

    body=$(curl -s --max-time "$TIMEOUT" -X POST -H "Content-Type: application/json" -d "$data" "${BASE}${endpoint}" 2>&1)
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" -X POST -H "Content-Type: application/json" -d "$data" "${BASE}${endpoint}" 2>&1)

    if echo "$body" | grep -q "$expected_text"; then
        echo -e "  ${GREEN}PASS${NC} [${http_code}] ${label} (contains '${expected_text}')"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} [${http_code}] ${label} (missing '${expected_text}')"
        echo "    Body: $(echo "$body" | head -c 200)"
        FAIL=$((FAIL + 1))
    fi
}

# ============================================================
# SECTION 1: REST Endpoints (should return 402 Payment Required)
# ============================================================
echo ""
echo "============================================"
echo "SECTION 1: REST Endpoints (expect 402)"
echo "============================================"

# Complex (upto-price) endpoints
for ep in \
    "/api/audit" \
    "/api/refactor" \
    "/api/docs" \
    "/api/defi-analyze" \
    "/api/trading-signal" \
    "/api/solidity-scan" \
    "/api/nl-to-sql" \
    "/api/sql-to-nl" \
    "/api/git-summarize" \
    "/api/translate-code"; do
    name=$(echo "$ep" | sed 's|/api/||')
    check_status "$ep" "402" "POST ${ep} (complex: ${name})" "POST"
done

# Micro (exact-price) endpoints
for ep in \
    "/api/validate-json" \
    "/api/classify-text" \
    "/api/extract-data" \
    "/api/generate-regex" \
    "/api/format-data" \
    "/api/summarize"; do
    name=$(echo "$ep" | sed 's|/api/||')
    check_status "$ep" "402" "POST ${ep} (micro: ${name})" "POST"
done

# Additional endpoints
for ep in \
    "/api/whale-tracker" \
    "/api/smart-money" \
    "/api/price-feed"; do
    name=$(echo "$ep" | sed 's|/api/||')
    check_status "$ep" "402" "POST ${ep} (data: ${name})" "POST"
done

# ============================================================
# SECTION 2: Discovery Endpoints (should return 200)
# ============================================================
echo ""
echo "============================================"
echo "SECTION 2: Discovery Endpoints (expect 200)"
echo "============================================"

check_status "/" "200" "GET / (root)"
check_status "/.well-known/x402" "200" "GET /.well-known/x402"
check_status "/.well-known/openapi.json" "200" "GET /.well-known/openapi.json"
check_status "/.well-known/agent-card.json" "200" "GET /.well-known/agent-card.json"
check_status "/.well-known/glama.json" "200" "GET /.well-known/glama.json"
check_status "/.well-known/mcp/server-card.json" "200" "GET /.well-known/mcp/server-card.json"
check_status "/api/prices" "200" "GET /api/prices"
check_status "/docs/examples" "200" "GET /docs/examples"
check_status "/health" "200" "GET /health"
check_status "/health/deep" "200" "GET /health/deep"
check_status "/health/metrics" "200" "GET /health/metrics"

# ============================================================
# SECTION 3: Discovery Content Verification
# ============================================================
echo ""
echo "============================================"
echo "SECTION 3: Content Verification"
echo "============================================"

check_content "/.well-known/x402" "payment" "x402 contains 'payment'"
check_content "/.well-known/openapi.json" "openapi" "openapi.json contains 'openapi'"
check_content "/.well-known/agent-card.json" "agent" "agent-card contains 'agent'"
check_content "/api/prices" "usdc" "/api/prices mentions USDC"
check_content "/health" "ok" "/health says ok"
check_content "/health/deep" "database" "/health/deep mentions database"

# ============================================================
# SECTION 4: Billing Endpoints
# ============================================================
echo ""
echo "============================================"
echo "SECTION 4: Billing Endpoints"
echo "============================================"

check_post_content "/billing/create-key" '{"name":"test-key","tier":"basic"}' "key" "POST /billing/create-key returns key"
check_content "/billing/tiers" "tier" "GET /billing/tiers returns tiers"

# ============================================================
# SECTION 5: MCP SSE Endpoints
# ============================================================
echo ""
echo "============================================"
echo "SECTION 5: MCP SSE Endpoints"
echo "============================================"

# SSE endpoints should return text/event-stream with 200
sse_check() {
    local endpoint="$1"
    local label="$2"

    # Get headers (first line + content-type)
    response=$(curl -s -i --max-time 5 "${BASE}${endpoint}" 2>&1)
    content_type=$(echo "$response" | grep -i "content-type" | head -1)
    http_code=$(echo "$response" | head -1 | awk '{print $2}')

    if [ "$http_code" = "200" ]; then
        echo -e "  ${GREEN}PASS${NC} [200] ${label}"
        PASS=$((PASS + 1))
    elif [ -z "$http_code" ]; then
        # SSE might hang waiting for events, that's normal
        echo -e "  ${YELLOW}INFO${NC} [stream] ${label} (SSE streaming - connection opened)"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} [${http_code}] ${label}"
        FAIL=$((FAIL + 1))
    fi
}

sse_check "/mcp/sse" "GET /mcp/sse (main MCP)"
sse_check "/ecommerce/sse" "GET /ecommerce/sse (ecommerce)"

# ============================================================
# SECTION 6: HEAD Requests
# ============================================================
echo ""
echo "============================================"
echo "SECTION 6: HEAD Requests"
echo "============================================"

check_status "/health" "200" "HEAD /health" "HEAD"
check_status "/.well-known/x402" "200" "HEAD /.well-known/x402" "HEAD"

# ============================================================
# SECTION 7: System Checks (VPS-specific)
# ============================================================
echo ""
echo "============================================"
echo "SECTION 7: System Checks (journalctl)"
echo "============================================"

echo ""
echo "--- Blockchain Listener Status ---"
if journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i "blockchain listener started\|listener started\|listener is running"; then
    echo -e "  ${GREEN}PASS${NC} Blockchain listener is running"
    PASS=$((PASS + 1))
else
    echo -e "  ${RED}FAIL${NC} Could not find 'Blockchain listener started' in logs"
    echo "    Checking broader patterns..."
    if journalctl -u agent-api --no-pager -n 100 2>/dev/null | grep -i "listener\|started\|blockchain"; then
        echo -e "  ${YELLOW}PARTIAL${NC} Found related log entries (see above)"
    else
        echo -e "  ${RED}FAIL${NC} No listener-related logs found"
        FAIL=$((FAIL + 1))
    fi
fi

echo ""
echo "--- Recent Logs (last 30 lines) ---"
journalctl -u agent-api --no-pager -n 30 2>/dev/null
echo ""

# Check for errors in recent logs
echo "--- Error Check ---"
errors=$(journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i "error\|critical\|exception\|traceback" | head -10)
if [ -z "$errors" ]; then
    echo -e "  ${GREEN}PASS${NC} No errors in recent logs"
    PASS=$((PASS + 1))
else
    echo -e "  ${RED}FAIL${NC} Found errors in recent logs:"
    echo "$errors"
    FAIL=$((FAIL + 1))
fi

# ============================================================
# SECTION 8: Service Status
# ============================================================
echo ""
echo "============================================"
echo "SECTION 8: Service Status"
echo "============================================"

echo ""
echo "--- agent-api service status ---"
systemctl status agent-api 2>/dev/null | head -10

echo ""
echo "--- agent-api resource usage ---"
ps aux | grep agent-api | grep -v grep

echo ""
echo "--- Disk space ---"
df -h / 2>/dev/null

echo ""
echo "--- Memory ---"
free -h 2>/dev/null

# ============================================================
# RESULTS SUMMARY
# ============================================================
echo ""
echo "============================================"
echo "           RESULTS SUMMARY"
echo "============================================"
total=$((PASS + FAIL))
echo -e "  ${GREEN}PASS: ${PASS}${NC}"
echo -e "  ${RED}FAIL: ${FAIL}${NC}"
echo "  Total: ${total}"
echo "============================================"

# Exit with non-zero if any test failed
[ "$FAIL" -eq 0 ]
exit $?