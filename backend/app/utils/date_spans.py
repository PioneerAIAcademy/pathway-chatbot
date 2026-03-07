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


def _sanitize_span(raw: str) -> str:
    span = (raw or "").strip(" \t\n\r,.;:()[]{}")
    span = re.sub(r"\s+", " ", span).strip()
    return span


def _looks_like_full_date(span: str) -> bool:
    if not span:
        return False

    if re.search(r"\b\d{4}\b", span):
        return True

    if re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", span):
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

        if len(phrases) < _MAX_DATE_SPANS:
            fallback = search_dates(text, settings=settings)
            _collect(fallback)
    except Exception:
        return phrases

    return phrases[:_MAX_DATE_SPANS]
