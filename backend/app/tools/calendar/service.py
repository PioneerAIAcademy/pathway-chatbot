import hashlib
import json
import logging
import re
from datetime import date
from typing import Any, Optional

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.settings import Settings

from app.tools.calendar.schema import CalendarToolArgs
from app.tools.calendar.tool import (
    _get_today,
    build_calendar_card,
    compute_suggestions,
    extract_structured_data,
    query_pinecone_for_calendar,
)

logger = logging.getLogger("uvicorn")

_YEAR_PATTERN = re.compile(r"\b20\d{2}\b")


def _available_years_from_nodes(nodes: list[Any]) -> list[int]:
    years: set[int] = set()
    for node in nodes or []:
        text = getattr(node, "text", "") or ""
        for match in _YEAR_PATTERN.findall(text):
            year = int(match)
            if 2025 <= year <= 2100:
                years.add(year)
    return sorted(years)


def _node_key(node: Any) -> str:
    metadata = getattr(getattr(node, "node", None), "metadata", None) or {}
    node_id = getattr(getattr(node, "node", None), "node_id", None)
    url = metadata.get("url") if isinstance(metadata, dict) else None
    text = (getattr(node, "text", "") or "")[:120]
    return f"{node_id}|{url}|{text}"


def _merge_nodes(primary: list[Any], extra: list[Any], max_nodes: int = 18) -> list[Any]:
    seen: set[str] = set()
    merged: list[Any] = []
    for node in [*(primary or []), *(extra or [])]:
        key = _node_key(node)
        if key in seen:
            continue
        seen.add(key)
        merged.append(node)
        if len(merged) >= max_nodes:
            break
    return merged


def _prioritize_nodes_for_year(
    nodes: list[Any],
    year: int,
    *,
    max_nodes: int = 12,
) -> list[Any]:
    year_str = str(year)
    matching: list[Any] = []
    non_matching: list[Any] = []

    for node in nodes or []:
        text = getattr(node, "text", "") or ""
        if year_str in text:
            matching.append(node)
        else:
            non_matching.append(node)

    prioritized = [*matching, *non_matching]
    return prioritized[:max_nodes]


async def localize_calendar_intro(
    intro_text: str,
    user_language: Optional[str],
    original_user_message: str,
) -> str:
    """
    Localize intro text using the configured LLM so we don't hardcode templates
    for every language.
    """
    if not intro_text:
        return intro_text

    language = (user_language or "").strip().lower()
    if language in {"", "en"}:
        return intro_text

    prompt = (
        "Translate the assistant intro sentence into the same language as the user message. "
        "Keep meaning, tone, and punctuation. Keep it concise. "
        "Return only the translated sentence."
    )

    try:
        response = await Settings.llm.achat(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=prompt),
                ChatMessage(
                    role=MessageRole.USER,
                    content=(
                        f"User message language sample: {original_user_message}\n\n"
                        f"Intro to translate: {intro_text}"
                    ),
                ),
            ]
        )
        translated = (response.message.content or "").strip()
        return translated if translated else intro_text
    except Exception as e:
        logger.warning(f"Calendar intro localization failed: {e}")
        return intro_text


def _extract_translatable_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": card.get("title"),
        "subtitle": card.get("subtitle"),
        "footnote": card.get("footnote"),
        "textFormatOffer": card.get("textFormatOffer"),
        "suggestedQuestions": card.get("suggestedQuestions", []),
        "spotlight": {
            "title": (card.get("spotlight") or {}).get("title"),
            "description": (card.get("spotlight") or {}).get("description"),
            "countdown": (card.get("spotlight") or {}).get("countdown"),
        }
        if card.get("spotlight")
        else None,
        "events": [
            {
                "name": evt.get("name"),
                "description": evt.get("description"),
                "countdown": evt.get("countdown"),
                "section": evt.get("section"),
            }
            for evt in card.get("events", [])
        ],
        "tabs": [
            {
                "label": tab.get("label"),
                "events": [
                    {
                        "name": evt.get("name"),
                        "description": evt.get("description"),
                        "countdown": evt.get("countdown"),
                        "section": evt.get("section"),
                    }
                    for evt in (tab.get("events") or [])
                ],
            }
            for tab in (card.get("tabs") or [])
        ],
    }


def _apply_translated_card(card: dict[str, Any], translated: dict[str, Any]) -> dict[str, Any]:
    for key in ("title", "subtitle", "footnote", "textFormatOffer"):
        if key in translated and translated.get(key) is not None:
            card[key] = translated.get(key)

    translated_questions = translated.get("suggestedQuestions")
    if isinstance(translated_questions, list):
        card["suggestedQuestions"] = [str(q) for q in translated_questions if q]

    if card.get("spotlight") and isinstance(translated.get("spotlight"), dict):
        for key in ("title", "description", "countdown"):
            value = translated["spotlight"].get(key)
            if value is not None:
                card["spotlight"][key] = value

    translated_events = translated.get("events")
    if isinstance(translated_events, list):
        for idx, evt in enumerate(card.get("events", [])):
            if idx >= len(translated_events) or not isinstance(translated_events[idx], dict):
                continue
            for key in ("name", "description", "countdown", "section"):
                value = translated_events[idx].get(key)
                if value is not None:
                    evt[key] = value

    translated_tabs = translated.get("tabs")
    if isinstance(translated_tabs, list):
        for tab_idx, tab in enumerate(card.get("tabs", [])):
            if tab_idx >= len(translated_tabs) or not isinstance(translated_tabs[tab_idx], dict):
                continue
            tab_label = translated_tabs[tab_idx].get("label")
            if tab_label is not None:
                tab["label"] = tab_label

            tab_events = translated_tabs[tab_idx].get("events")
            if not isinstance(tab_events, list):
                continue
            for evt_idx, evt in enumerate(tab.get("events", [])):
                if evt_idx >= len(tab_events) or not isinstance(tab_events[evt_idx], dict):
                    continue
                for key in ("name", "description", "countdown", "section"):
                    value = tab_events[evt_idx].get(key)
                    if value is not None:
                        evt[key] = value

    return card


def _parse_translation_json(raw: str) -> Optional[dict[str, Any]]:
    candidate = raw.strip()
    if not candidate:
        return None

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 2:
            if lines[-1].strip().startswith("```"):
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            candidate = "\n".join(lines).strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


async def localize_calendar_card(
    card: dict[str, Any],
    user_language: Optional[str],
    original_user_message: str,
) -> dict[str, Any]:
    language = (user_language or "").strip().lower()
    if language in {"", "en"}:
        return card

    payload = _extract_translatable_card(card)
    prompt = (
        "SYSTEM TASK: LOCALIZE JSON DISPLAY TEXT.\n"
        "WARNING: STRICT OUTPUT CONTRACT — VIOLATIONS ARE NOT ACCEPTABLE.\n\n"
        "RULES (MANDATORY):\n"
        "1) TRANSLATE ONLY HUMAN-READABLE DISPLAY STRINGS.\n"
        "2) DO NOT ADD, REMOVE, OR RENAME ANY KEYS.\n"
        "3) PRESERVE JSON SHAPE EXACTLY (OBJECT/LIST STRUCTURE, LIST LENGTHS, ORDER).\n"
        "4) DO NOT CHANGE DATES, NUMBERS, ISO STRINGS, IDS, OR STATUS-LIKE CODES.\n"
        "5) DO NOT WRITE EXPLANATIONS, NOTES, OR MARKDOWN.\n"
        "6) OUTPUT MUST BE EXACTLY ONE VALID JSON OBJECT.\n\n"
        "IF YOU CANNOT COMPLY, RETURN THE ORIGINAL JSON UNCHANGED."
    )

    try:
        response = await Settings.llm.achat(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=prompt),
                ChatMessage(
                    role=MessageRole.USER,
                    content=(
                        f"User message language sample: {original_user_message}\n\n"
                        f"JSON:\n{json.dumps(payload, ensure_ascii=False)}"
                    ),
                ),
            ]
        )
        translated = _parse_translation_json(response.message.content or "")
        if translated is not None:
            return _apply_translated_card(card, translated)
        return card
    except Exception as e:
        logger.warning(f"Calendar card localization failed: {e}")
        return card


def _pick(options: list[str], key: str) -> str:
    """Deterministic pseudo-random variant picker for stable variety."""
    if not options:
        return ""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(options)
    return options[index]


def _normalize_season(raw: Optional[str]) -> str:
    value = (raw or "").strip().lower()
    if value == "summer":
        return "spring"
    if value in {"winter", "spring", "fall"}:
        return value
    return ""


def _season_for_block(block_number: Optional[int]) -> str:
    if block_number in (1, 2):
        return "winter"
    if block_number in (3, 4):
        return "spring"
    if block_number in (5, 6):
        return "fall"
    return ""


def _humanize_deadline(deadline: Optional[str]) -> str:
    if not deadline:
        return "deadline"
    label = deadline.replace("_", " ").strip().lower()
    if label == "drop":
        return "drop / auto-drop"
    if label == "add course":
        return "add course"
    return label


def build_calendar_intro(args: CalendarToolArgs) -> str:
    """Build a short, humanized intro sentence for a calendar card."""
    qt = args.query_type.value
    scope = (getattr(args, "scope", "term") or "term").lower()
    season_raw = _normalize_season(args.season)
    season = season_raw.capitalize() if season_raw else ""
    year = args.year
    variant_key = (
        f"{qt}|{season_raw}|{year}|{args.block_number}|{args.specific_deadline}"
    )

    if qt == "block" and args.block_number:
        canonical = _season_for_block(args.block_number) or season_raw
        if canonical:
            label = f"{canonical.capitalize()} {year} — Block {args.block_number}"
            return _pick(
                [
                    f"Here are the key dates for {label}:",
                    f"Let me pull up the calendar for {label}:",
                    f"Here’s {label} at a glance:",
                ],
                variant_key,
            )
        return _pick(
            [
                f"Here are the key dates for Block {args.block_number} ({year}):",
                f"Let me pull up the calendar for Block {args.block_number} ({year}):",
            ],
            variant_key,
        )

    if qt == "semester" and scope == "full_year":
        return _pick(
            [
                f"Here’s the full {year} academic calendar at a glance:",
                f"Let me pull up all {year} terms and deadlines:",
                f"Here are the key dates across all {year} terms:",
            ],
            variant_key,
        )

    if qt == "semester" and season:
        return _pick(
            [
                f"Here's the {season} {year} semester at a glance:",
                f"Let me pull up the full {season} {year} semester:",
                f"Here are the key dates for {season} {year}:",
            ],
            variant_key,
        )

    if qt == "deadline" and args.specific_deadline:
        deadline = _humanize_deadline(args.specific_deadline)
        if scope == "full_year":
            return _pick(
                [
                    f"Here are all {deadline} dates for {year}:",
                    f"Let me pull up {year} {deadline} deadlines across all terms:",
                ],
                variant_key,
            )
        if args.block_number:
            canonical = _season_for_block(args.block_number) or season_raw
            if canonical:
                label = f"{canonical.capitalize()} {year} — Block {args.block_number}"
                return _pick(
                    [
                        f"Here’s the {deadline} deadline for {label}:",
                        f"Let me look up the {deadline} deadline for {label}:",
                        f"Here’s what to know about the {deadline} deadline for {label}:",
                    ],
                    variant_key,
                )
            return _pick(
                [
                    f"Here’s the {deadline} deadline for Block {args.block_number}:",
                    f"Let me look up the {deadline} deadline for Block {args.block_number}:",
                ],
                variant_key,
            )
        if season:
            return _pick(
                [
                    f"Here’s the {deadline} deadline for {season} {year}:",
                    f"Let me look up the {deadline} deadline for {season} {year}:",
                ],
                variant_key,
            )
        return _pick(
            [f"Here’s the {deadline} deadline:", f"Let me look up the {deadline} deadline:"],
            variant_key,
        )

    if qt == "deadline" and args.block_number:
        canonical = _season_for_block(args.block_number) or season_raw
        if canonical:
            label = f"{canonical.capitalize()} {year} — Block {args.block_number}"
            return _pick(
                [
                    f"Here are the key deadlines for {label}:",
                    f"Let me pull up the key deadlines for {label}:",
                ],
                variant_key,
            )
        return _pick(
            [
                f"Here are the key deadlines for Block {args.block_number}:",
                f"Let me pull up the key deadlines for Block {args.block_number}:",
            ],
            variant_key,
        )

    if qt == "graduation":
        if season:
            return _pick(
                [
                    f"Here are the {season} {year} graduation dates:",
                    f"Let me pull up graduation dates for {season} {year}:",
                ],
                variant_key,
            )
        return _pick(
            [
                f"Here are the {year} graduation dates:",
                f"Let me pull up the {year} graduation dates:",
            ],
            variant_key,
        )

    if season:
        return _pick(
            [
                f"Here’s the {season} {year} calendar at a glance:",
                f"Let me pull up the {season} {year} calendar:",
            ],
            variant_key,
        )
    return _pick(
        [
            f"Here’s the academic calendar for {year}:",
            f"Let me pull up the academic calendar for {year}:",
        ],
        variant_key,
    )


def build_initial_calendar_metadata(args: CalendarToolArgs) -> dict[str, Any]:
    return {
        "mode": "calendar",
        "router_args": {
            "query_type": args.query_type.value,
            "scope": getattr(args, "scope", "term"),
            "year": args.year,
            "season": args.season,
            "block_number": args.block_number,
            "specific_deadline": args.specific_deadline,
            "timezone": args.timezone,
        },
        "pipeline_status": "detected",
    }


async def run_calendar_pipeline(
    calendar_args: Optional[CalendarToolArgs],
    shared_index: Any,
    user_query: Optional[str] = None,
    user_language: Optional[str] = None,
) -> tuple[Optional[dict], dict[str, Any]]:
    """Run calendar retrieval+extraction+card build, returning card and metadata."""
    metadata: dict[str, Any] = {}

    if calendar_args is None:
        logger.warning("Calendar pipeline: calendar_args is None, skipping")
        metadata["pipeline_status"] = "skipped_no_args"
        return None, metadata

    try:
        if shared_index is None:
            logger.warning("Calendar pipeline: shared_index is None, skipping")
            metadata["pipeline_status"] = "skipped_no_index"
            return None, metadata

        logger.info("Calendar pipeline: creating retriever...")
        scope = (getattr(calendar_args, "scope", "term") or "term").lower()
        if scope == "full_year":
            retriever = shared_index.as_retriever(similarity_top_k=8, sparse_top_k=30)
        else:
            retriever = shared_index.as_retriever(similarity_top_k=3, sparse_top_k=15)

        logger.info("Calendar pipeline: querying Pinecone...")
        nodes = await query_pinecone_for_calendar(calendar_args, retriever)

        if (
            scope == "full_year"
            and calendar_args.query_type.value == "semester"
            and calendar_args.year
        ):
            expanded_nodes: list[Any] = []
            for season in ("winter", "spring", "fall"):
                expanded_query = (
                    f"academic calendar {calendar_args.year} {season} "
                    f"start end dates deadlines block"
                )
                try:
                    season_nodes = await retriever.aretrieve(expanded_query)
                    expanded_nodes = _merge_nodes(expanded_nodes, season_nodes, max_nodes=24)
                except Exception as e:
                    logger.warning(
                        "Calendar pipeline: season expansion query failed (%s): %s",
                        season,
                        e,
                    )

            if expanded_nodes:
                nodes = _merge_nodes(nodes, expanded_nodes, max_nodes=24)
                metadata["retrieval_mode"] = "full_year_expanded"

            nodes = _prioritize_nodes_for_year(
                nodes,
                calendar_args.year,
                max_nodes=12,
            )
            metadata["retrieval_mode"] = (
                f"{metadata.get('retrieval_mode', 'full_year')}+year_prioritized"
            )

        if not nodes:
            logger.warning("Calendar pipeline: no Pinecone nodes returned")
            metadata["pipeline_status"] = "no_nodes"
            return None, metadata

        logger.info("Calendar pipeline: got %d nodes", len(nodes))
        metadata["retrieved_nodes_count"] = len(nodes)

        available_years = _available_years_from_nodes(nodes)
        if available_years:
            metadata["available_years_from_nodes"] = available_years
            if calendar_args.year not in available_years:
                logger.warning(
                    "Calendar pipeline: requested year %s not found in initial source years %s; retrying strict-year retrieval",
                    calendar_args.year,
                    available_years,
                )

                strict_query = (
                    f"academic calendar {calendar_args.year} "
                    f"{calendar_args.year} Start/End Dates & Deadlines"
                )
                if calendar_args.season:
                    strict_query += f" {calendar_args.season}"
                if calendar_args.block_number:
                    strict_query += f" block {calendar_args.block_number}"

                strict_nodes = await retriever.aretrieve(strict_query)
                if strict_nodes:
                    nodes = strict_nodes
                    metadata["retrieved_nodes_count"] = len(nodes)
                    metadata["retrieval_mode"] = "strict_year_retry"
                    available_years = _available_years_from_nodes(nodes)
                    metadata["available_years_from_nodes"] = available_years

                if calendar_args.year not in available_years:
                    logger.warning(
                        "Calendar pipeline: requested year %s still not found after strict retry; years=%s",
                        calendar_args.year,
                        available_years,
                    )
                    metadata["pipeline_status"] = "unsupported_year"
                    metadata["requested_year"] = calendar_args.year
                    return None, metadata

        logger.info("Calendar pipeline: extracting structured data...")
        extracted = await extract_structured_data(nodes, calendar_args)
        if not extracted:
            logger.warning("Calendar pipeline: structured extraction failed")
            metadata["pipeline_status"] = "extraction_failed"
            return None, metadata

        logger.info("Calendar pipeline: extracted %d events", len(extracted.events))
        metadata.update(
            {
                "pipeline_status": "extracted",
                "extracted": {
                    "title": extracted.title,
                    "subtitle": extracted.subtitle,
                    "start": extracted.block_or_semester_start,
                    "end": extracted.block_or_semester_end,
                    "event_count": len(extracted.events),
                    "events": [
                        {"date": evt.date, "name": evt.name}
                        for evt in extracted.events[:40]
                    ],
                },
            }
        )

        today: date = _get_today(calendar_args.timezone)
        card = build_calendar_card(extracted, calendar_args, today)
        if card is None:
            logger.warning(
                "Calendar pipeline: card failed self-verification — returning None"
            )
            metadata["pipeline_status"] = "card_verification_failed"
            return None, metadata

        card["suggestedQuestions"] = compute_suggestions(
            calendar_args,
            extracted,
            user_query=user_query,
        )
        card = await localize_calendar_card(
            card,
            user_language=user_language,
            original_user_message=user_query or "",
        )
        metadata.update(
            {
                "pipeline_status": "success",
                "card": {
                    "title": card.get("title"),
                    "subtitle": card.get("subtitle"),
                    "status": card.get("status"),
                    "type": card.get("type"),
                    "event_count": len(card.get("events", [])),
                    "spotlight": card.get("spotlight", {}).get("title")
                    if card.get("spotlight")
                    else None,
                },
            }
        )
        logger.info("Calendar pipeline: card built & verified successfully")
        return card, metadata

    except Exception as e:
        logger.error(f"Calendar pipeline error: {e}", exc_info=True)
        metadata.update({"pipeline_status": "error", "pipeline_error": str(e)})
        return None, metadata
