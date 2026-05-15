"""Lightweight analytics — tracks API calls, revenue, errors.

Stored in /opt/agent-api/data/analytics.json (rotating daily, max 10K entries).
"""
import json
import time
import threading
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path("/opt/agent-api/data")
ANALYTICS_FILE = DATA_DIR / "analytics.json"
MAX_ENTRIES = 10_000
DAYS_KEEP = 30

_lock = threading.Lock()


def _load() -> list[dict]:
    if not ANALYTICS_FILE.exists():
        return []
    try:
        with open(ANALYTICS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Prune old entries
    cutoff = time.time() - DAYS_KEEP * 86400
    entries = [e for e in entries if e.get("timestamp", 0) > cutoff]
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(entries, f)


def track(tool: str, payment_method: str = "x402", success: bool = True,
          tokens_used: int = 0, amount_usd: float = 0, error: str = ""):
    """Record an API call. Safe to call from any thread."""
    entry = {
        "tool": tool,
        "timestamp": time.time(),
        "payment_method": payment_method,
        "success": success,
        "tokens_used": tokens_used,
        "amount_usd": amount_usd,
        "error": error,
    }
    with _lock:
        entries = _load()
        entries.append(entry)
        _save(entries)


# In-memory attempt counter (resets on restart, good enough for visibility)
_attempts: dict[str, int] = {}
_attempts_lock = threading.Lock()


def increment_attempt(path: str = "/") -> None:
    """Count a 402 payment attempt. Thread-safe."""
    with _attempts_lock:
        _attempts[path] = _attempts.get(path, 0) + 1


def get_attempts() -> dict:
    """Get attempt counts since last restart."""
    with _attempts_lock:
        return {"total_attempts": sum(_attempts.values()), "by_endpoint": dict(_attempts)}


def get_stats(days: int = 7) -> dict:
    """Get analytics for the last N days."""
    cutoff = time.time() - days * 86400
    with _lock:
        entries = [e for e in _load() if e.get("timestamp", 0) > cutoff]

    total = len(entries)
    if not total:
        return {"period_days": days, "total_calls": 0, "message": "No data yet"}

    success_count = sum(1 for e in entries if e.get("success"))
    error_count = total - success_count
    total_revenue = sum(e.get("amount_usd", 0) for e in entries)
    total_tokens = sum(e.get("tokens_used", 0) for e in entries)

    # By tool
    by_tool = defaultdict(lambda: {"calls": 0, "revenue": 0})
    for e in entries:
        t = e.get("tool", "unknown")
        by_tool[t]["calls"] += 1
        by_tool[t]["revenue"] += e.get("amount_usd", 0)

    # By payment method
    by_method = defaultdict(int)
    for e in entries:
        by_method[e.get("payment_method", "x402")] += 1

    # Daily revenue
    daily = defaultdict(float)
    for e in entries:
        day = time.strftime("%Y-%m-%d", time.localtime(e.get("timestamp", 0)))
        daily[day] += e.get("amount_usd", 0)

    return {
        "period_days": days,
        "total_calls": total,
        "success": success_count,
        "errors": error_count,
        "conversion_rate": round(success_count / total * 100, 1) if total else 0,
        "total_revenue_usd": round(total_revenue, 4),
        "total_tokens": total_tokens,
        "by_tool": dict(sorted(by_tool.items(), key=lambda x: x[1]["calls"], reverse=True)),
        "by_payment_method": dict(by_method),
        "daily_revenue": dict(sorted(daily.items())),
    }
