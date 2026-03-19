import re
from typing import Optional

try:
    from dateparser.search import search_dates

    _DATEPARSER_AVAILABLE = True
except Exception:
    _DATEPARSER_AVAILABLE = False


_MAX_DATE_SPANS = 40
_MIN_SPAN_LENGTH = 6
_MAX_SPAN_LENGTH = 80

# Strip markdown-style citation markers like [1], [2], [^1], etc. that confuse
# dateparser when they appear immediately after a year (e.g. "2026 [1]").
_CITATION_MARKER = re.compile(r"\s*\[\^?\d+\]\.?", re.IGNORECASE)

# Compiled once at module level — reused across every call to _sanitize_span.
# Symmetric: the same connector words are stripped from both ends.
_LEAD_CONNECTORS = re.compile(
    r"^(?:on|by|from|until|till|through|between)\s+",
    re.IGNORECASE,
)
_TRAIL_CONNECTORS = re.compile(
    r"\s+(?:and|or|to|on|by|from|until|till|through|between)$",
    re.IGNORECASE,
)
_STRIP_CHARS = " \t\n\r,.;:()[]{}"


def _sanitize_span(raw: str) -> str:
    span = (raw or "").strip(_STRIP_CHARS)
    span = re.sub(r"\s+", " ", span).strip()

    # Loop until stable: handles chained connectors on either end
    # e.g. "on by March 15, 2025 and" → "March 15, 2025"
    while True:
        cleaned = _LEAD_CONNECTORS.sub("", span)
        cleaned = _TRAIL_CONNECTORS.sub("", cleaned)
        cleaned = cleaned.strip(_STRIP_CHARS)
        if cleaned == span:
            break
        span = cleaned

    return span


def _looks_like_full_date(span: str) -> bool:
    if not span:
        return False

    # A 4-digit year is the only reliable anchor for a "full" date.
    # The ISO pattern (2025-03-15) is a subset of this check, so no
    # second branch is needed.
    if re.search(r"\b\d{4}\b", span):
        return True

    return False


def _normalized_language(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    normalized = code.strip().lower()
    if not normalized:
        return None
    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]
    if "_" in normalized:
        normalized = normalized.split("_", 1)[0]
    return normalized


def extract_date_spans(text: str, language_code: Optional[str] = None) -> list[str]:
    """Extract likely date phrases from natural language text.

    Deterministic, parser-based extraction for multilingual responses.
    Returns deduplicated phrases in original order.
    """
    if not text or not text.strip() or not _DATEPARSER_AVAILABLE:
        return []

    # Remove citation markers (e.g. "[1]", "[2].") that prevent dateparser
    # from recognizing adjacent dates.
    text = _CITATION_MARKER.sub("", text)

    settings = {
        "STRICT_PARSING": True,
        "PREFER_LOCALE_DATE_ORDER": True,
    }

    lang = _normalized_language(language_code)
    phrases: list[str] = []
    seen: set[str] = set()

    def _collect(matches: list[tuple[str, object]] | None) -> None:
        if not matches:
            return
        for matched, _ in matches:
            span = _sanitize_span(matched)
            if not span:
                continue
            if len(span) < _MIN_SPAN_LENGTH or len(span) > _MAX_SPAN_LENGTH:
                continue
            if not _looks_like_full_date(span):
                continue
            key = span.casefold()
            if key in seen:
                continue
            seen.add(key)
            phrases.append(span)
            if len(phrases) >= _MAX_DATE_SPANS:
                return

    try:
        if lang:
            primary = search_dates(
                text,
                languages=[lang],
                settings=settings,
            )
            _collect(primary)

        # Only fall back to unconstrained auto-detect if the language-specific
        # pass found nothing. Auto-detect is noisier and can misread words in
        # one language as dates in another.
        if not phrases:
            fallback = search_dates(text, settings=settings)
            _collect(fallback)
    except Exception:
        return phrases

    return phrases[:_MAX_DATE_SPANS]