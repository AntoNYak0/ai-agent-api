"""User-defined composite workflow registry.

Authors register workflow chains (e.g., audit → refactor → docs).
Users execute them via run-workflow MCP tool or REST endpoint.
Rev-share: author gets (100 - platform_percent)% of each execution fee.

Storage: JSON file at /opt/agent-api/data/workflows.json
Thread-safe with threading.Lock, atomic writes (tempfile + os.replace).
"""

import json
import time
import threading
import secrets
from pathlib import Path

DATA_DIR = Path("/opt/agent-api/data")
WORKFLOWS_FILE = DATA_DIR / "workflows.json"

_lock = threading.Lock()

# Default platform cut: 15%
DEFAULT_PLATFORM_PERCENT = 15


def _load() -> dict:
    if not WORKFLOWS_FILE.exists():
        return {"workflows": {}, "total_executions": 0}
    with open(WORKFLOWS_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    import tempfile, os as _os
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), prefix="workflows_", suffix=".tmp")
    try:
        with _os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        _os.replace(tmp, str(WORKFLOWS_FILE))
    except Exception:
        _os.unlink(tmp)
        raise


def register_workflow(
    name: str,
    description: str,
    author_api_key: str,
    chain: list[str],
    price_cents: int,
    platform_percent: int = DEFAULT_PLATFORM_PERCENT,
) -> dict:
    """Register a new composite workflow. Returns the created workflow dict."""
    if platform_percent < 0 or platform_percent > 50:
        raise ValueError("platform_percent must be between 0 and 50")
    if price_cents < 1:
        raise ValueError("price_cents must be at least 1")
    if len(chain) < 2:
        raise ValueError("chain must have at least 2 tools")
    if len(chain) > 5:
        raise ValueError("chain must have at most 5 tools")

    workflow_id = "wf-" + secrets.token_hex(8)

    with _lock:
        data = _load()
        data["workflows"][workflow_id] = {
            "id": workflow_id,
            "name": name,
            "description": description,
            "author_api_key": author_api_key,
            "chain": chain,
            "price_cents": price_cents,
            "platform_percent": platform_percent,
            "created_at": time.time(),
            "enabled": True,
        }
        _save(data)

    return data["workflows"][workflow_id]


def get_workflow(workflow_id: str) -> dict | None:
    """Get a single workflow by ID."""
    data = _load()
    return data["workflows"].get(workflow_id)


def list_workflows() -> list[dict]:
    """List all enabled workflows."""
    data = _load()
    return [
        {k: v for k, v in wf.items() if k != "author_api_key"}
        for wf in data["workflows"].values()
        if wf.get("enabled", True)
    ]


def disable_workflow(workflow_id: str, author_api_key: str) -> bool:
    """Disable a workflow. Only the author can disable it."""
    with _lock:
        data = _load()
        wf = data["workflows"].get(workflow_id)
        if not wf or wf["author_api_key"] != author_api_key:
            return False
        wf["enabled"] = False
        _save(data)
    return True


def increment_executions() -> int:
    """Increment total execution counter. Returns new count."""
    with _lock:
        data = _load()
        data["total_executions"] = data.get("total_executions", 0) + 1
        _save(data)
    return data["total_executions"]


def get_total_executions() -> int:
    data = _load()
    return data.get("total_executions", 0)
