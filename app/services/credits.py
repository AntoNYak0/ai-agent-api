"""API-key based credits system for human developers.

Humans pay via Stripe (or manual top-up) → get API key + credits.
AI agents pay via x402 (USDC crypto). This hybrid model solves the
"1.8M API requests, $0 revenue" problem — 99% of human devs don't have
crypto wallets.

Storage: JSON file at /opt/agent-api/data/credits.json
"""

import json
import secrets
import time
import threading
from pathlib import Path

DATA_DIR = Path("/opt/agent-api/data")
CREDITS_FILE = DATA_DIR / "credits.json"

_lock = threading.Lock()

# Credit prices: 1 credit = $0.001 USDC equivalent
# Stripe commission ~3%, so human price is ~1.5x crypto price
CREDITS_PER_CENT = 10  # 10 credits = $0.01


def _load() -> dict:
    if not CREDITS_FILE.exists():
        return {"keys": {}, "total_revenue_cents": 0}
    with open(CREDITS_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CREDITS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def generate_api_key() -> str:
    """Generate a new API key and return it."""
    key = "ak-" + secrets.token_hex(16)
    with _lock:
        data = _load()
        data["keys"][key] = {
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
        if api_key not in data["keys"]:
            raise ValueError("Unknown API key")
        data["keys"][api_key]["credits"] += credits_to_add
        data["total_revenue_cents"] += amount_cents
        _save(data)
    return data["keys"][api_key]["credits"]


def spend_credits(api_key: str, amount_cents: int) -> bool:
    """Deduct credits for an API call. Returns True if sufficient balance."""
    credits_needed = amount_cents * CREDITS_PER_CENT
    with _lock:
        data = _load()
        entry = data["keys"].get(api_key)
        if not entry or entry["credits"] < credits_needed:
            return False
        entry["credits"] -= credits_needed
        entry["total_spent_credits"] += credits_needed
        entry["last_used"] = time.time()
        _save(data)
    return True


def get_balance(api_key: str) -> dict | None:
    """Return balance info for an API key."""
    data = _load()
    entry = data["keys"].get(api_key)
    if not entry:
        return None
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
    return {
        "total_keys": len(data["keys"]),
        "active_keys": active_keys,
        "total_revenue_usd": data["total_revenue_cents"] / 100,
    }
