"""
Calendar pipeline configuration.

All tunable constants live here so they're easy to find and adjust.
Dev mode (ENVIRONMENT != "production") doubles timeouts to accommodate
slower local machines and debugger overhead.
"""

import os

# ── Environment Detection ───────────────────────────────────────────────
# "dev" unless explicitly set to "production" (matches chat.py convention).
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev").strip().lower()
IS_DEV = ENVIRONMENT != "production"

# In dev, double every timeout so slow laptops / debuggers don't trip them.
_TIMEOUT_MULTIPLIER = 2.0 if IS_DEV else 1.0


# ── Calendar Pipeline Timeouts (seconds) ────────────────────────────────

# Mixed-path timeout: calendar runs concurrently alongside RAG streaming.
# After this many seconds the calendar card is abandoned — the student
# already has RAG text, so they still get an answer.
CALENDAR_PIPELINE_TIMEOUT: float = 45.0 * _TIMEOUT_MULTIPLIER

# Calendar-only timeout: the student asked a pure calendar question, so
# the ENTIRE response depends on the pipeline finishing.  Longer than
# the mixed-path timeout because there's no fallback text displayed yet.
CALENDAR_ONLY_TIMEOUT: float = 120.0 * _TIMEOUT_MULTIPLIER


# ── Academic Calendar URL ────────────────────────────────────────────────

ACADEMIC_CALENDAR_URL = (
	"https://studentservices.byupathway.edu/studentservices/academic-calendar"
)


# ── Streaming Behaviour ─────────────────────────────────────────────────

# In the mixed (RAG + calendar) path, wait until at least this many text
# tokens have been streamed before emitting calendar card patches.  This
# ensures the student sees some context-setting text before the card.
MIN_TOKENS_BEFORE_CALENDAR: int = 15


# ── Calendar Cache ───────────────────────────────────────────────────────

# Time-to-live for cached calendar results (seconds).  Academic calendar
# data rarely changes mid-day, so 1 hour keeps things fresh enough.
CALENDAR_CACHE_TTL: float = 3600.0

# Maximum number of distinct query keys held in the cache at once.
CALENDAR_CACHE_MAX_SIZE: int = 64
