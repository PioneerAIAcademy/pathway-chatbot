"""
In-memory TTL cache for calendar pipeline results.

Caches the final (card, metadata) tuple keyed on the canonical calendar
arguments so repeated identical queries skip Pinecone + LLM extraction
entirely.  Safe for single-process deployments (Uvicorn workers).
"""

import logging
import time
from typing import Any, Optional

from app.tools.calendar.config import CALENDAR_CACHE_MAX_SIZE, CALENDAR_CACHE_TTL
from app.tools.calendar.schema import CalendarToolArgs

logger = logging.getLogger("uvicorn")


def _cache_key(args: CalendarToolArgs) -> str:
    """Deterministic string key from the calendar arguments that matter."""
    return (
        f"{args.year}|{args.query_type.value}|"
        f"{(getattr(args, 'scope', 'term') or 'term').lower()}|"
        f"{(args.season or '').lower()}|"
        f"{args.block_number or ''}|"
        f"{(args.specific_deadline or '').lower()}"
    )


class CalendarCache:
    """Thread-safe (GIL) in-memory LRU/TTL cache."""

    def __init__(self, ttl: float = CALENDAR_CACHE_TTL, max_size: int = CALENDAR_CACHE_MAX_SIZE):
        self._ttl = ttl
        self._max_size = max_size
        # {key: (timestamp, card, metadata)}
        self._store: dict[str, tuple[float, Optional[dict], dict[str, Any]]] = {}

    def get(self, args: CalendarToolArgs) -> Optional[tuple[Optional[dict], dict[str, Any]]]:
        key = _cache_key(args)
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, card, metadata = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            logger.info("Calendar cache expired: %s", key)
            return None
        logger.info("Calendar cache HIT: %s", key)
        return card, metadata

    def put(self, args: CalendarToolArgs, card: Optional[dict], metadata: dict[str, Any]) -> None:
        key = _cache_key(args)
        # Evict oldest entries if at capacity
        if len(self._store) >= self._max_size and key not in self._store:
            oldest_key = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest_key]
        self._store[key] = (time.monotonic(), card, metadata)
        logger.info("Calendar cache PUT: %s", key)

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# Module-level singleton shared across requests in the same process.
calendar_cache = CalendarCache()
