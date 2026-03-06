import re
from difflib import SequenceMatcher
from typing import Optional


_DEADLINE_ALIASES: dict[str, tuple[str, ...]] = {
    "financial_hold": (
        "financial hold",
        "financial holds",
        "holds applied",
        "holds",
        "hold",
        "clear hold",
        "clear holds",
        "account hold",
        "registration hold",
    ),
    "priority_registration": (
        "priority registration",
        "priority registration deadline",
    ),
    "registration": (
        "registration opens",
        "registration open",
        "registration",
        "register",
    ),
    "application": (
        "application deadline",
        "application",
    ),
    "add_course": (
        "add course deadline",
        "add course",
        "add class",
    ),
    "drop": (
        "drop/auto-drop",
        "drop auto drop",
        "auto-drop",
        "autodrop",
        "drop deadline",
        "drop course",
        "drop",
    ),
    "refund": (
        "last day for a refund",
        "refund deadline",
        "refund",
    ),
    "payment": (
        "payment deadline",
        "payment due",
        "payment",
        "tuition due",
    ),
    "late_fees": (
        "late fees applied",
        "late fee",
        "late fees",
    ),
    "withdraw": (
        "last day to withdraw",
        "withdraw with a w",
        "withdraw",
    ),
    "tuition_discount": (
        "tuition discount deadline",
        "tuition discount",
    ),
    "grades": (
        "grades available",
        "grades",
    ),
}

_FULL_YEAR_ALIASES: tuple[str, ...] = (
    "full year",
    "whole year",
    "entire year",
    "all year",
    "for the year",
    "for this year",
    "this year",
    "year overview",
    "all terms",
    "all blocks",
    "all semesters",
)


_EVENT_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    "financial_hold": ("financial hold",),
    "priority_registration": ("priority registration",),
    "registration": ("registration open", "registration opens", "registration"),
    "application": ("application deadline", "application"),
    "add_course": ("add course deadline", "add course"),
    "drop": ("drop/auto-drop", "auto-drop", "drop"),
    "refund": ("refund",),
    "payment": ("payment deadline", "payment"),
    "late_fees": ("late fee", "late fees"),
    "withdraw": ("withdraw",),
    "tuition_discount": ("tuition discount",),
    "grades": ("grades available", "grades"),
}


def _normalize_text(text: str) -> str:
    lowered = (text or "").lower().strip()
    return re.sub(r"[^a-z0-9]+", " ", lowered)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_alias_match(normalized_text: str, alias_norm: str) -> bool:
    text_tokens = normalized_text.split()
    alias_tokens = alias_norm.split()
    if not text_tokens or not alias_tokens:
        return False

    if len(text_tokens) < len(alias_tokens):
        windows = [text_tokens]
    else:
        windows = [
            text_tokens[i : i + len(alias_tokens)]
            for i in range(0, len(text_tokens) - len(alias_tokens) + 1)
        ]

    for window in windows:
        scores = [_similar(t, a) for t, a in zip(window, alias_tokens)]
        if scores and min(scores) >= 0.82 and sum(scores) / len(scores) >= 0.88:
            return True
    return False


def normalize_deadline_term(text: str) -> Optional[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    best_key: Optional[str] = None
    best_score = -1
    matched_keys: set[str] = set()

    for key, aliases in _DEADLINE_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalize_text(alias)
            if not alias_norm:
                continue
            if alias_norm in normalized:
                matched_keys.add(key)
                score = len(alias_norm)
                if score > best_score:
                    best_score = score
                    best_key = key
            elif _fuzzy_alias_match(normalized, alias_norm):
                matched_keys.add(key)
                score = max(1, len(alias_norm) - 1)
                if score > best_score:
                    best_score = score
                    best_key = key

    if "financial_hold" in matched_keys and re.search(r"\bholds?\b", normalized):
        return "financial_hold"

    return best_key


def event_matches_deadline(event_name: str, specific_deadline: Optional[str]) -> bool:
    if not specific_deadline:
        return True

    patterns = _EVENT_NAME_PATTERNS.get(specific_deadline, ())
    if not patterns:
        return True

    value = _normalize_text(event_name)
    return any(_normalize_text(pattern) in value for pattern in patterns)


def normalize_query_scope(text: str) -> Optional[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    if any(_normalize_text(alias) in normalized for alias in _FULL_YEAR_ALIASES):
        return "full_year"

    if re.search(r"\b(?:all|entire|full)\s+(?:registration|deadline|deadlines|holds|payments|fees|grades)\b", normalized):
        return "full_year"

    return None
