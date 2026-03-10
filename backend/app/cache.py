"""
Simple in-memory response cache for the chat endpoint.

Identical questions (same text + role) are served from cache for 1 hour,
avoiding redundant LLM calls and reducing API costs.
"""

import hashlib
import logging
from cachetools import TTLCache

logger = logging.getLogger("uvicorn")

# Max 100 cached responses; each expires after 1 hour
_cache: TTLCache = TTLCache(maxsize=100, ttl=3600)


def cache_key(question: str, role: str) -> str:
    """Generate a stable cache key from the question text and user role."""
    raw = f"{role}:{question.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_response(key: str) -> str | None:
    """Return the cached response text, or None if not found / expired."""
    value = _cache.get(key)
    if value is not None:
        logger.info(f"Cache hit for key {key[:8]}...")
    return value


def set_cached_response(key: str, response: str) -> None:
    """Store a response in the cache."""
    _cache[key] = response
    logger.info(f"Cached response for key {key[:8]}... ({len(response)} chars)")
