import re
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
