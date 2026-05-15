"""Replay attack protection — tracks used payment_tx hashes with TTL.

x402 has no built-in nonce mechanism. An attacker could replay the same
payment_tx hash to consume multiple paid API calls. This module prevents that
by fingerprinting each (payment_tx, tool_name) pair with a time-bounded cache.
"""

import time
import hashlib
import logging

logger = logging.getLogger("replay_guard")

TTL_SECONDS = 600  # 10 minutes
MAX_ENTRIES = 100_000

_ledger: dict[str, float] = {}


def _prune() -> None:
    """Remove expired entries. Called on each check."""
    now = time.time()
    expired = [k for k, ts in _ledger.items() if now - ts > TTL_SECONDS]
    for k in expired:
        del _ledger[k]
    if len(_ledger) > MAX_ENTRIES:
        sorted_entries = sorted(_ledger.items(), key=lambda x: x[1])
        for k, _ in sorted_entries[: len(_ledger) - MAX_ENTRIES]:
            del _ledger[k]


def is_replay(payment_tx: str, tool_name: str) -> bool:
    """Return True if this payment_tx was already used for this tool."""
    if not payment_tx:
        return False

    fingerprint = hashlib.sha256(
        f"{payment_tx}:{tool_name}".encode()
    ).hexdigest()

    _prune()

    now = time.time()
    if fingerprint in _ledger:
        age = now - _ledger[fingerprint]
        logger.warning(
            f"Replay detected: tool={tool_name} tx={payment_tx[:16]}... "
            f"age={age:.1f}s"
        )
        return True

    _ledger[fingerprint] = now
    return False
