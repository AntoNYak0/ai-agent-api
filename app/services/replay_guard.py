"""Replay attack protection — SQLite-backed payment deduplication.

Survives restarts (unlike the previous in-memory dict). Each (payment_tx, tool_name)
pair is fingerprinted and stored with a 30-minute TTL.
"""

import os
import time
import hashlib
import sqlite3
import logging
import threading

logger = logging.getLogger("replay_guard")

TTL_SECONDS = 1800  # 30 minutes — survives service restart
MAX_ENTRIES = 100_000

DB_DIR = "/opt/agent-api/data"
DB_PATH = os.path.join(DB_DIR, "replay.db") if os.path.exists("/opt/agent-api") else "replay.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Persistent connection pool — single connection, reused across calls."""
    global _conn
    if _conn is not None:
        return _conn
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.execute(
        "CREATE TABLE IF NOT EXISTS fingerprints "
        "(hash TEXT PRIMARY KEY, tool_name TEXT, created_at REAL)"
    )
    _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def _prune(conn: sqlite3.Connection) -> None:
    """Remove expired entries and enforce MAX_ENTRIES."""
    cutoff = time.time() - TTL_SECONDS
    conn.execute("DELETE FROM fingerprints WHERE created_at < ?", (cutoff,))

    count = conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
    if count > MAX_ENTRIES:
        excess = count - MAX_ENTRIES
        conn.execute(
            "DELETE FROM fingerprints WHERE hash IN "
            "(SELECT hash FROM fingerprints ORDER BY created_at ASC LIMIT ?)",
            (excess,),
        )
    conn.commit()


def is_replay(payment_tx: str, tool_name: str) -> bool:
    """Return True if this payment_tx was already used for this tool."""
    if not payment_tx:
        return False

    fingerprint = hashlib.sha256(
        f"{payment_tx}:{tool_name}".encode()
    ).hexdigest()

    with _lock:
        conn = _get_conn()
        _prune(conn)

        row = conn.execute(
            "SELECT created_at FROM fingerprints WHERE hash = ?",
            (fingerprint,),
        ).fetchone()

        if row:
            age = time.time() - row[0]
            logger.warning(
                "Replay detected: tool=%s tx=%s... age=%.1fs",
                tool_name, payment_tx[:16], age,
            )
            return True

        conn.execute(
            "INSERT OR REPLACE INTO fingerprints (hash, tool_name, created_at) "
            "VALUES (?, ?, ?)",
            (fingerprint, tool_name, time.time()),
        )
        conn.commit()
        return False
