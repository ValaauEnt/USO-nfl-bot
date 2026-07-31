"""
In-memory TTL cache for API responses.
Prevents hammering the same ESPN endpoints on repeated questions.
"""
import time
import logging

log = logging.getLogger("uce.cache")

# TTL in seconds per data type (per spec)
CACHE_TTLS: dict[str, int] = {
    "scoreboard":  45,     # 45 s — tight during live games
    "standings":   21600,  # 6 h
    "schedule":    86400,  # 24 h
    "roster":      86400,  # 24 h
    "player":      86400,  # 24 h
    "stats":       600,    # 10 min
    "news":        300,    # 5 min
    "trade_news":  300,    # 5 min
    "leaders":     600,    # 10 min
}

# Internal store: key → (value, expires_at)
_store: dict[str, tuple] = {}


def get(key: str) -> tuple:
    """
    Return (value, hit: bool).
    value is None on a cache miss or expired entry.
    """
    entry = _store.get(key)
    if entry is None:
        return None, False
    value, expires = entry
    if time.monotonic() < expires:
        log.debug("Cache HIT  %s", key)
        return value, True
    # Expired
    del _store[key]
    log.debug("Cache MISS (expired) %s", key)
    return None, False


def set(key: str, value, ttl_key: str) -> None:
    """Store value under key with the TTL for ttl_key."""
    ttl = CACHE_TTLS.get(ttl_key, 300)
    _store[key] = (value, time.monotonic() + ttl)
    log.debug("Cache SET  %s  TTL=%ds", key, ttl)


def clear_expired() -> int:
    """Remove stale entries. Returns the number removed."""
    now = time.monotonic()
    stale = [k for k, (_, exp) in _store.items() if now >= exp]
    for k in stale:
        del _store[k]
    return len(stale)
