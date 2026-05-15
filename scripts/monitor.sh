#!/bin/bash
# Uptime monitor — add to crontab: */5 * * * * /opt/agent-api/scripts/monitor.sh
# After 3 consecutive failures, prints service status

URL="https://agent-api-ai.duckdns.org/health"
FAIL_FILE="/tmp/agent-api-fail-count"

if ! curl -sf --max-time 10 "$URL" > /dev/null 2>&1; then
    count=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
    count=$((count + 1))
    echo "$count" > "$FAIL_FILE"

    if [ "$count" -ge 3 ]; then
        echo "[$(date)] agent-api DOWN after $count consecutive failures"
        echo "=== Service Status ==="
        systemctl status agent-api --no-pager 2>/dev/null || echo "systemctl not available"
        echo "=== Last 20 log lines ==="
        journalctl -u agent-api --no-pager -n 20 2>/dev/null || tail -20 /opt/agent-api/logs/app.log 2>/dev/null
    fi
else
    echo "0" > "$FAIL_FILE"
fi
