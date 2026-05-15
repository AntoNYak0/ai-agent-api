#!/bin/bash
echo "=== NGINX ACCESS LOG (last 30 requests) ==="
tail -30 /var/log/nginx/access.log

echo ""
echo "=== UNIQUE IPs TODAY ==="
cat /var/log/nginx/access.log | awk '{print $1}' | sort -u | wc -l

echo ""
echo "=== TOP IPs ==="
cat /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -15

echo ""
echo "=== MCP / SSE connections ==="
grep "mcp/sse" /var/log/nginx/access.log | head -15

echo ""
echo "=== Agent requests (openapi / x402 / well-known) ==="
grep -E "openapi|x402|well-known" /var/log/nginx/access.log | head -15

echo ""
echo "=== USER AGENTS ==="
cat /var/log/nginx/access.log | awk -F'"' '{print $6}' | sort | uniq -c | sort -rn | head -15

echo ""
echo "=== BILLING STATS ==="
curl -s http://localhost:8000/health | python3 -m json.tool

echo ""
echo "=== API KEY USAGE ==="
cat /opt/agent-api/data/credits.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
keys = d.get('keys', {})
for k, v in sorted(keys.items(), key=lambda x: x[1].get('total_spent_credits', 0), reverse=True)[:10]:
    spent = v.get('total_spent_credits', 0)
    credits = v.get('credits', 0)
    last = v.get('last_used', 'never')
    print(f'{k[:20]}... | balance: {credits:5d} | spent: {spent:5d} | last: {last}')
"
