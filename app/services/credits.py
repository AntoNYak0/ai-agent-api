"""API-key based credits system for human developers.

Humans pay via Stripe (or manual top-up) → get API key + credits.
AI agents pay via x402 (USDC crypto). This hybrid model solves the
"1.8M API requests, $0 revenue" problem — 99% of human devs don't have
crypto wallets.

Storage: JSON file at /opt/agent-api/data/credits.json
Keys stored as SHA-256 hashes — plaintext keys never written to disk.
"""

import json
import secrets
import hashlib
import time
import threading
from pathlib import Path

DATA_DIR = Path("/opt/agent-api/data")
CREDITS_FILE = DATA_DIR / "credits.json"

_lock = threading.Lock()

# Credit prices: 1 credit = $0.001 USDC equivalent
# Stripe commission ~3%, so human price is ~1.5x crypto price
CREDITS_PER_CENT = 10  # 10 credits = $0.01


def _hash_key(api_key: str) -> str:
    """SHA-256 hash of API key — never store plaintext on disk."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _resolve_key(data: dict, api_key: str) -> str | None:
    """Look up API key with backward compatibility.
    New keys stored as SHA-256 hashes; old keys may still be raw strings.
    Returns the storage key if found, None otherwise.
    """
    key_hash = _hash_key(api_key)
    if key_hash in data["keys"]:
        return key_hash
    if api_key in data["keys"]:
        return api_key
    return None


def _migrate_key(data: dict, api_key: str) -> str:
    """Migrate a raw API key to SHA-256 hash. Returns the new storage key."""
    key_hash = _hash_key(api_key)
    if api_key in data["keys"]:
        data["keys"][key_hash] = data["keys"].pop(api_key)
    return key_hash


def _load() -> dict:
    if not CREDITS_FILE.exists():
        return {"keys": {}, "total_revenue_cents": 0}
    with open(CREDITS_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    import tempfile, os as _os
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), prefix="credits_", suffix=".tmp")
    try:
        with _os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        _os.replace(tmp, str(CREDITS_FILE))  # atomic rename
    except Exception:
        _os.unlink(tmp)
        raise


def generate_api_key() -> str:
    """Generate a new API key. Returns raw key (store it — never shown again)."""
    key = "ak-" + secrets.token_hex(16)
    with _lock:
        data = _load()
        data["keys"][_hash_key(key)] = {
            "credits": 0,
            "total_spent_credits": 0,
            "created_at": time.time(),
            "last_used": None,
        }
        _save(data)
    return key


def get_bonus_rate(amount_cents: int) -> tuple[int, float]:
    """Return (bonus_percent, multiplier) for bulk top-ups.

    - $10 (1000 cents): 10% bonus
    - $50 (5000 cents): 20% bonus
    - $100 (10000 cents): 30% bonus
    """
    if amount_cents >= 10000:
        return 30, 1.30
    elif amount_cents >= 5000:
        return 20, 1.20
    elif amount_cents >= 1000:
        return 10, 1.10
    return 0, 1.0


def add_credits(api_key: str, amount_cents: int) -> int:
    """Add credits with bulk bonus. Returns new balance in credits."""
    bonus_pct, multiplier = get_bonus_rate(amount_cents)
    credits_to_add = int(amount_cents * CREDITS_PER_CENT * multiplier)
    with _lock:
        data = _load()
        storage_key = _resolve_key(data, api_key)
        if not storage_key:
            raise ValueError("Unknown API key")
        storage_key = _migrate_key(data, api_key)
        data["keys"][storage_key]["credits"] += credits_to_add
        if "total_revenue_cents" not in data:
            data["total_revenue_cents"] = data.get("total_topup_cents", 0)
        data["total_revenue_cents"] += amount_cents
        _save(data)
    return data["keys"][storage_key]["credits"]


def spend_credits(api_key: str, amount_cents: int) -> bool:
    """Deduct credits for an API call. Returns True if sufficient balance."""
    credits_needed = amount_cents * CREDITS_PER_CENT
    with _lock:
        data = _load()
        storage_key = _resolve_key(data, api_key)
        if not storage_key:
            return False
        entry = data["keys"][storage_key]
        if entry["credits"] < credits_needed:
            return False
        entry["credits"] -= credits_needed
        entry["total_spent_credits"] += credits_needed
        entry["last_used"] = time.time()
        _save(data)
    return True


def get_balance(api_key: str) -> dict | None:
    """Return balance info for an API key."""
    data = _load()
    storage_key = _resolve_key(data, api_key)
    if not storage_key:
        return None
    entry = data["keys"][storage_key]
    return {
        "credits": entry["credits"],
        "usd_equivalent": entry["credits"] / CREDITS_PER_CENT / 100,
        "total_spent_usd": entry["total_spent_credits"] / CREDITS_PER_CENT / 100,
        "created_at": entry["created_at"],
        "last_used": entry["last_used"],
    }


def get_stats() -> dict:
    """Return global stats."""
    data = _load()
    active_keys = sum(1 for v in data["keys"].values() if v["credits"] > 0)
    revenue_cents = data.get("total_revenue_cents", data.get("total_topup_cents", 0))
    return {
        "total_keys": len(data["keys"]),
        "active_keys": active_keys,
        "total_revenue_usd": revenue_cents / 100,
    }
