"""Simple in-memory response cache — avoids redundant DeepSeek calls.

SHA-256 hash of (model + tool_name + input) → stored result. 10-minute TTL.
Reduces AI costs for identical requests.

Model-aware: cache key includes model so Flash results aren't served for Pro
requests and vice versa. The model in the key is the one that WAS used to
generate the cached result — on a cache hit we skip the LLM call entirely,
so the model parameter doesn't matter.
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


def _key(model: str, tool: str, content: str) -> str:
    return hashlib.sha256(f"{model}:{tool}:{content}".encode()).hexdigest()


def get(model: str, tool: str, content: str) -> str | None:
    key = _key(model, tool, content)
    with _lock:
        entry = _cache.get(key)
        if entry and time.time() - entry["ts"] < TTL_SECONDS:
            logger.info("Cache HIT: %s (model=%s age=%.1fs)", tool, model, time.time() - entry["ts"])
            return entry["result"]
    return None


def set(model: str, tool: str, content: str, result: str) -> None:
    key = _key(model, tool, content)
    with _lock:
        if len(_cache) >= MAX_ENTRIES:
            # Evict oldest 10%
            sorted_keys = sorted(_cache, key=lambda k: _cache[k]["ts"])
            for old_key in sorted_keys[: int(MAX_ENTRIES * 0.1)]:
                del _cache[old_key]
        _cache[key] = {"ts": time.time(), "result": result}
        logger.debug("Cache SET: %s (model=%s)", tool, model)


def stats() -> dict:
    with _lock:
        return {"entries": len(_cache), "max": MAX_ENTRIES, "ttl": TTL_SECONDS}


async def cached_completion(
    tool: str,
    user_content: str,
    system_prompt: str,
    context: str | None = None,
    json_mode: bool = True,
    max_tokens: int = 2048,
    model: str | None = None,
    force_model: str | None = None,
):
    """Cache-aware DeepSeek call. Returns (result, tokens, was_compressed) tuple.

    Checks cache before calling DeepSeek. Stores result on cache miss.
    Cache hits: was_compressed=False (stored result, no compression needed).

    Model is auto-selected by complexity unless model= or force_model= is provided.
    Cache key includes the model actually used.
    """
    from app.services.deepseek import deepseek_completion, select_model as _select_model

    # Determine which model will be used (for cache key)
    input_len = len(user_content) + (len(context) if context else 0)
    effective_model = model or _select_model(max_tokens, input_len, force_model)

    cache_content = f"{system_prompt}|{user_content}"
    cached = get(effective_model, tool, cache_content)
    if cached:
        return cached, 0, False  # 0 tokens = cache hit, no compression

    result, tokens, compressed = await deepseek_completion(
        system_prompt, user_content, context, json_mode, max_tokens,
        model=model, force_model=force_model, tool=tool,
    )
    set(effective_model, tool, cache_content, result)
    return result, tokens, compressed
