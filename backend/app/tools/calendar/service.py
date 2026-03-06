import hashlib
import logging
from datetime import date
from typing import Any, Optional

from app.tools.calendar.schema import CalendarToolArgs
from app.tools.calendar.tool import (
    _get_today,
    build_calendar_card,
    compute_suggestions,
    extract_structured_data,
    query_pinecone_for_calendar,
)

logger = logging.getLogger("uvicorn")


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
        retriever = shared_index.as_retriever(similarity_top_k=3, sparse_top_k=15)

        logger.info("Calendar pipeline: querying Pinecone...")
        nodes = await query_pinecone_for_calendar(calendar_args, retriever)
        if not nodes:
            logger.warning("Calendar pipeline: no Pinecone nodes returned")
            metadata["pipeline_status"] = "no_nodes"
            return None, metadata

        logger.info("Calendar pipeline: got %d nodes", len(nodes))
        metadata["retrieved_nodes_count"] = len(nodes)

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
