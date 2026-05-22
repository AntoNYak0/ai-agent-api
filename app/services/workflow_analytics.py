"""Workflow execution analytics — rolling 30-day JSON log.

Tracks per-workflow: call_count, success_rate, avg_latency_ms,
total_revenue_cents, author_earnings_cents, last_used_at.

Storage: JSON file at /opt/agent-api/data/workflow_analytics.json
In-memory stats computed on read for fast dashboard queries.
"""

import json
import time
import threading
from pathlib import Path

DATA_DIR = Path("/opt/agent-api/data")
ANALYTICS_FILE = DATA_DIR / "workflow_analytics.json"

_lock = threading.Lock()

ROLLING_DAYS = 30


def _load() -> dict:
    if not ANALYTICS_FILE.exists():
        return {"executions": []}
    with open(ANALYTICS_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    import tempfile, os as _os
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), prefix="wf_analytics_", suffix=".tmp")
    try:
        with _os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        _os.replace(tmp, str(ANALYTICS_FILE))
    except Exception:
        _os.unlink(tmp)
        raise


def _prune_old(data: dict) -> dict:
    """Remove executions older than ROLLING_DAYS."""
    cutoff = time.time() - ROLLING_DAYS * 86400
    data["executions"] = [e for e in data["executions"] if e.get("timestamp", 0) >= cutoff]
    return data


def log_execution(
    workflow_id: str,
    success: bool,
    latency_ms: int,
    tokens_used: int,
    revenue_cents: int,
    author_earnings_cents: int,
) -> None:
    """Log a single workflow execution."""
    with _lock:
        data = _load()
        data = _prune_old(data)
        data["executions"].append({
            "workflow_id": workflow_id,
            "success": success,
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "revenue_cents": revenue_cents,
            "author_earnings_cents": author_earnings_cents,
            "timestamp": time.time(),
        })
        # Keep max 10000 entries to bound file size
        if len(data["executions"]) > 10000:
            data["executions"] = data["executions"][-10000:]
        _save(data)


def get_workflow_stats(workflow_id: str) -> dict:
    """Compute stats for a specific workflow from rolling 30-day data."""
    data = _load()
    executions = [e for e in data["executions"] if e["workflow_id"] == workflow_id]

    if not executions:
        return {
            "workflow_id": workflow_id,
            "total_calls": 0,
            "success_rate": 0,
            "avg_latency_ms": 0,
            "avg_tokens_per_call": 0,
            "total_revenue_cents": 0,
            "author_earnings_cents": 0,
            "last_used_at": None,
        }

    total = len(executions)
    success_count = sum(1 for e in executions if e["success"])
    avg_latency = sum(e["latency_ms"] for e in executions) / total
    avg_tokens = sum(e["tokens_used"] for e in executions) / total
    total_revenue = sum(e["revenue_cents"] for e in executions)
    total_author = sum(e["author_earnings_cents"] for e in executions)
    last_used = max(e["timestamp"] for e in executions)

    return {
        "workflow_id": workflow_id,
        "total_calls": total,
        "success_rate": round(success_count / total * 100, 1),
        "avg_latency_ms": round(avg_latency, 1),
        "avg_tokens_per_call": round(avg_tokens, 1),
        "total_revenue_cents": total_revenue,
        "author_earnings_cents": total_author,
        "last_used_at": last_used,
    }


def get_global_stats() -> dict:
    """Compute global stats across all workflows."""
    data = _load()
    if not data["executions"]:
        return {"total_calls": 0, "total_revenue_cents": 0, "active_workflows": 0}

    workflows_seen = set(e["workflow_id"] for e in data["executions"])
    total = len(data["executions"])
    total_revenue = sum(e["revenue_cents"] for e in data["executions"])

    return {
        "total_calls": total,
        "total_revenue_cents": total_revenue,
        "active_workflows": len(workflows_seen),
    }
