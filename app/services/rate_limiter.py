"""Simple in-memory rate limiter: 10 requests/minute per IP, 100 max tracked."""
import time
import threading

MAX_REQUESTS_PER_MINUTE = 10
MAX_TRACKED_IPS = 500
CLEANUP_EVERY = 60  # seconds between cleanup passes

_lock = threading.Lock()
_ips: dict[str, list[float]] = {}
_last_cleanup = time.time()
_blocks_total: int = 0  # cumulative blocks since restart


def _cleanup():
    """Remove expired entries and excess IPs."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < CLEANUP_EVERY:
        return
    _last_cleanup = now
    cutoff = now - 60
    stale = [ip for ip, times in _ips.items() if not any(t > cutoff for t in times)]
    for ip in stale:
        del _ips[ip]
    if len(_ips) > MAX_TRACKED_IPS:
        sorted_ips = sorted(_ips.items(), key=lambda x: len(x[1]), reverse=True)
        for ip, _ in sorted_ips[MAX_TRACKED_IPS:]:
            del _ips[ip]


def is_allowed(ip: str) -> bool:
    """Check if IP is within rate limit. Thread-safe."""
    now = time.time()
    with _lock:
        _cleanup()
        if ip not in _ips:
            _ips[ip] = []
        window = [t for t in _ips[ip] if now - t < 60]
        _ips[ip] = window
        if len(window) >= MAX_REQUESTS_PER_MINUTE:
            global _blocks_total
            _blocks_total += 1
            return False
        _ips[ip].append(now)
        return True


def reset() -> None:
    """Clear all rate limit state. Used in tests."""
    global _ips
    with _lock:
        _ips = {}


def get_stats() -> dict:
    with _lock:
        return {
            "tracked_ips": len(_ips),
            "limited_ips": sum(1 for times in _ips.values() if len(times) >= MAX_REQUESTS_PER_MINUTE),
            "blocks_total": _blocks_total,
        }
