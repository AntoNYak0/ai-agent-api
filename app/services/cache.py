"""Simple in-memory response cache — avoids redundant DeepSeek calls.

SHA-256 hash of (tool_name + input) → stored result. 10-minute TTL.
Reduces AI costs for identical requests.
"""
import time
import hashlib
import threading
import logging

logger = logging.getLogger("cache")

TTL_SECONDS = 600  # 10 minutes
MAX_ENTRIES = 1000

_cache: dict = {}
_lock = threading.Lock()


def _key(tool: str, content: str) -> str:
    return hashlib.sha256(f"{tool}:{content}".encode()).hexdigest()


def get(tool: str, content: str) -> str | None:
    key = _key(tool, content)
    with _lock:
        entry = _cache.get(key)
        if entry and time.time() - entry["ts"] < TTL_SECONDS:
            logger.info("Cache HIT: %s (age %.1fs)", tool, time.time() - entry["ts"])
            return entry["result"]
    return None


def set(tool: str, content: str, result: str) -> None:
    key = _key(tool, content)
    with _lock:
        if len(_cache) >= MAX_ENTRIES:
            # Evict oldest 10%
            sorted_keys = sorted(_cache, key=lambda k: _cache[k]["ts"])
            for old_key in sorted_keys[: int(MAX_ENTRIES * 0.1)]:
                del _cache[old_key]
        _cache[key] = {"ts": time.time(), "result": result}
        logger.debug("Cache SET: %s", tool)


def stats() -> dict:
    with _lock:
        return {"entries": len(_cache), "max": MAX_ENTRIES, "ttl": TTL_SECONDS}


async def cached_completion(tool: str, user_content: str, system_prompt: str, context: str | None = None, json_mode: bool = True):
    """Cache-aware DeepSeek call. Returns (result, tokens) tuple.
    Checks cache before calling DeepSeek. Stores result on cache miss.
    """
    cache_content = f"{system_prompt[:100]}|{user_content[:200]}"
    cached = get(tool, cache_content)
    if cached:
        return cached, 0  # 0 tokens = cache hit, no cost

    from app.services.deepseek import deepseek_completion
    result, tokens = await deepseek_completion(system_prompt, user_content, context, json_mode)
    set(tool, cache_content, result)
    return result, tokens
