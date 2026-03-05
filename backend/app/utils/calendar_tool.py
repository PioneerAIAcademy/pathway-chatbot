"""
Calendar tool: LLM-invoked tool for academic calendar queries.

Flow:
1. LLM decides to call `lookup_academic_calendar` with typed args
2. Tool queries Pinecone with calendar-specific metadata filters
3. LLM extracts structured data from chunks (strict JSON schema)
4. Deterministic Python computes date classifications, countdowns, urgency
5. Returns CalendarCardData dict ready for frontend
"""

import json
import logging
from datetime import date, datetime
from typing import Optional

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.settings import Settings
from zoneinfo import ZoneInfo

from app.utils.calendar_schema import (
    CalendarToolArgs,
    ExtractedCalendarData,
    ExtractedCalendarEvent,
)

logger = logging.getLogger("uvicorn")

ACADEMIC_CALENDAR_SOURCE_URL = (
    "https://studentservices.byupathway.edu/studentservices/academic-calendar"
)


# ---------------------------------------------------------------------------
# OpenAI function schema (used by the pre-flight router)
# ---------------------------------------------------------------------------

def get_calendar_tool_definition() -> dict:
    """Return the OpenAI-compatible function schema for the calendar tool."""
    return {
        "type": "function",
        "function": {
            "name": "lookup_academic_calendar",
            "description": (
                "Look up BYU-Pathway academic calendar dates, deadlines, "
                "block/semester schedules, and graduation information. "
                "Call this when the user is clearly asking about academic calendar "
                "dates, registration deadlines, block start/end dates, payment "
                "deadlines, drop deadlines, graduation dates, or commencement. "
                "Do NOT call this for questions about gatherings, classes, "
                "certificates, or general scheduling unrelated to the academic calendar."
            ),
            "parameters": CalendarToolArgs.model_json_schema(),
        },
    }


# ---------------------------------------------------------------------------
# Deterministic date helpers
# ---------------------------------------------------------------------------

def _get_today(user_timezone: str) -> date:
    """Get today's date in the user's timezone."""
    try:
        return datetime.now(ZoneInfo(user_timezone)).date()
    except Exception:
        return datetime.now(ZoneInfo("UTC")).date()


def _classify_date(event_date: date, today: date) -> str:
    """Classify a date relative to today."""
    delta = (event_date - today).days
    if delta < 0:
        return "past"
    if delta == 0:
        return "today"
    if delta <= 7:
        return "soon"
    return "upcoming"


def _countdown_str(event_date: date, today: date) -> str:
    """Human-readable countdown string."""
    delta = (event_date - today).days
    if delta < 0:
        return "Passed"
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return f"{delta} days"


def _urgency_for_status(status: str) -> str:
    """Map date status to urgency level for frontend styling."""
    return {
        "past": "calm",
        "today": "urgent",
        "soon": "warning",
        "upcoming": "info",
    }.get(status, "info")


def _season_for_block(block_number: Optional[int]) -> Optional[str]:
    """Derive the canonical season name from BYU-Pathway block number."""
    if block_number in (1, 2):
        return "winter"
    if block_number in (3, 4):
        return "spring"
    if block_number in (5, 6):
        return "fall"
    return None


# ---------------------------------------------------------------------------
# Pinecone query
# ---------------------------------------------------------------------------

async def query_pinecone_for_calendar(
    args: CalendarToolArgs,
    retriever,
) -> list:
    """Query Pinecone with a natural-language query built from typed args."""
    query_parts = ["academic calendar"]
    year_included = False

    if args.season:
        query_parts.append(f"{args.season} {args.year}")
        year_included = True
    if args.block_number:
        query_parts.append(f"block {args.block_number}")
    if args.specific_deadline:
        # Humanize underscored deadline names for better retrieval
        deadline_label = args.specific_deadline.replace("_", " ")
        query_parts.append(f"{deadline_label} deadline")
    if args.query_type.value == "graduation":
        query_parts.append("graduation commencement")
    if not year_included:
        query_parts.append(str(args.year))

    query_text = " ".join(query_parts)
    logger.info(f"Calendar Pinecone query: {query_text}")

    nodes = await retriever.aretrieve(query_text)
    return nodes


# ---------------------------------------------------------------------------
# Structured extraction via LLM
# ---------------------------------------------------------------------------

# Max characters of context to send to the extraction LLM.
# Calendar chunks can be enormous (full year tables); cap to keep latency low.
_MAX_CONTEXT_CHARS = 4000

_EXTRACTION_SYSTEM = (
    "You extract structured academic calendar data from documents. "
    "Respond with ONLY a JSON object (no markdown fences, no explanation). "
    "Use this exact schema:\n"
    "{\n"
    '  "title": "string, e.g. Winter 2026 — Block 2",\n'
    '  "subtitle": "string, date range e.g. March 2 – April 18, 2026",\n'
    '  "block_or_semester_start": "YYYY-MM-DD or null",\n'
    '  "block_or_semester_end": "YYYY-MM-DD or null",\n'
    '  "events": [{"date": "YYYY-MM-DD", "name": "string", "description": "string"}],\n'
    '  "source_url": "string or null",\n'
    '  "footnote": "string or null",\n'
    '  "blocks": null or [{"block_label": "Block 1", "events": [...same event shape...]}]\n'
    "}\n"
    "Rules:\n"
    "- Only include events matching the query.\n"
    "- Dates MUST be ISO format YYYY-MM-DD. Omit events with ambiguous dates.\n"
    "- For semester queries, group events by block in the 'blocks' field.\n"
    "- For single-block queries, leave 'blocks' as null.\n"
    "- IMPORTANT: Every event MUST have a short 'description' (1 sentence, max 15 words). "
    "Explain what it means for the student, e.g. 'Last day to add a course without "
    "instructor permission', 'Last day to drop without a W on transcript & get full "
    "refund', 'Classes begin — first day of instruction'. Never leave description empty.\n"
)


_MAX_EXTRACTION_ATTEMPTS = 2


async def extract_structured_data(
    nodes: list,
    args: CalendarToolArgs,
) -> Optional[ExtractedCalendarData]:
    """Extract calendar data from chunks via direct JSON completion.

    Retries once if the first attempt fails (agentic self-verification).
    """
    if not nodes:
        return None

    # Build context from top chunks, capped to avoid token overflow
    context_parts: list[str] = []
    total_chars = 0
    for node in nodes[:10]:
        text = node.text
        if total_chars + len(text) > _MAX_CONTEXT_CHARS:
            remaining = _MAX_CONTEXT_CHARS - total_chars
            if remaining > 200:
                context_parts.append(text[:remaining] + "\n[...truncated]")
            break
        context_parts.append(text)
        total_chars += len(text)
    context = "\n\n---\n\n".join(context_parts)

    # Build query description
    query_desc = args.query_type.value
    if args.season:
        query_desc += f" for {args.season} {args.year}"
    if args.block_number:
        query_desc += f" block {args.block_number}"
    if args.specific_deadline:
        query_desc += f", specifically the {args.specific_deadline} deadline"

    user_content = (
        f"Extract calendar data for: {query_desc}\n\n"
        f"Documents:\n{context}"
    )

    last_error: Optional[str] = None

    for attempt in range(1, _MAX_EXTRACTION_ATTEMPTS + 1):
        try:
            logger.info(f"Extraction attempt {attempt}/{_MAX_EXTRACTION_ATTEMPTS}")
            response = await Settings.llm.achat(
                messages=[
                    ChatMessage(role=MessageRole.SYSTEM, content=_EXTRACTION_SYSTEM),
                    ChatMessage(role=MessageRole.USER, content=user_content),
                ],
            )
            raw = response.message.content.strip()
            logger.info(f"Extraction raw response length: {len(raw)} chars")

            # Strip markdown fences if LLM wraps in ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3].strip()

            data = json.loads(raw)

            # Sanitize: remove keys where LLM returned null (or the string
            # "null") for fields that have non-None defaults, so Pydantic uses
            # the default instead of failing.
            _DEFAULTED_KEYS = {"title", "subtitle", "events", "source_url"}
            for key in _DEFAULTED_KEYS:
                if key in data and (data[key] is None or data[key] == "null"):
                    del data[key]

            extracted = ExtractedCalendarData(**data)

            # Self-verification: does the extraction look reasonable?
            if not extracted.events:
                last_error = "extraction returned 0 events"
                logger.warning(
                    f"Attempt {attempt}: {last_error} — "
                    f"{'retrying' if attempt < _MAX_EXTRACTION_ATTEMPTS else 'giving up'}"
                )
                continue

            logger.info(
                f"Extraction succeeded on attempt {attempt}: "
                f"{len(extracted.events)} events, title={extracted.title!r}"
            )
            return extracted

        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            logger.warning(
                f"Attempt {attempt}: {last_error} — "
                f"{'retrying' if attempt < _MAX_EXTRACTION_ATTEMPTS else 'giving up'}"
            )
        except Exception as e:
            last_error = f"extraction error: {e}"
            logger.error(
                f"Attempt {attempt}: {last_error} — "
                f"{'retrying' if attempt < _MAX_EXTRACTION_ATTEMPTS else 'giving up'}"
            )

    logger.error(f"All {_MAX_EXTRACTION_ATTEMPTS} extraction attempts failed. Last: {last_error}")
    return None


# ---------------------------------------------------------------------------
# Build final CalendarCardData (matches frontend TypeScript type)
# ---------------------------------------------------------------------------

def build_calendar_card(
    extracted: ExtractedCalendarData,
    args: CalendarToolArgs,
    today: date,
) -> Optional[dict]:
    """Apply deterministic date math to produce the final card data."""
    # Determine card-level status
    card_status = "upcoming"
    if extracted.block_or_semester_start and extracted.block_or_semester_end:
        try:
            start = date.fromisoformat(extracted.block_or_semester_start)
            end = date.fromisoformat(extracted.block_or_semester_end)
            if today > end:
                card_status = "past"
            elif today >= start:
                card_status = "active"
        except ValueError:
            pass

    # Process events with deterministic classification
    events = []
    spotlight = None

    for evt in extracted.events:
        try:
            evt_date = date.fromisoformat(evt.date)
        except ValueError:
            continue

        status = _classify_date(evt_date, today)
        countdown = _countdown_str(evt_date, today)

        event_dict = {
            "date": evt.date,
            "name": evt.name,
            "status": status,
            "countdown": countdown,
        }
        if evt.description:
            event_dict["description"] = evt.description

        # Assign section for timeline grouping
        if status == "past":
            event_dict["section"] = "Past"
        elif status == "today":
            event_dict["section"] = "Today"
        else:
            event_dict["section"] = "Coming Up"

        events.append(event_dict)

    # Select spotlight (priority: today > soon > first upcoming)
    for evt_dict in events:
        if evt_dict["status"] == "today":
            spotlight = {
                "urgency": "urgent",
                "date": evt_dict["date"],
                "title": evt_dict["name"],
                "description": evt_dict.get("description", ""),
                "countdown": "Due by end of day",
            }
            break

    if not spotlight:
        for evt_dict in events:
            if evt_dict["status"] in ("soon", "upcoming"):
                spotlight = {
                    "urgency": _urgency_for_status(evt_dict["status"]),
                    "date": evt_dict["date"],
                    "title": evt_dict["name"],
                    "description": evt_dict.get("description", ""),
                    "countdown": f"{evt_dict['countdown']} remaining",
                }
                break

    # Build tabs for semester view (from extracted blocks data)
    tabs = None
    if args.query_type.value == "semester" and extracted.blocks:
        tabs = []
        for i, block_data in enumerate(extracted.blocks):
            block_events = []
            for evt in block_data.events:
                try:
                    evt_date = date.fromisoformat(evt.date)
                except ValueError:
                    continue
                status = _classify_date(evt_date, today)
                countdown = _countdown_str(evt_date, today)
                section = (
                    "Past" if status == "past" else "Today" if status == "today" else "Coming Up"
                )
                block_events.append({
                    "date": evt.date,
                    "name": evt.name,
                    "status": status,
                    "countdown": countdown,
                    "description": evt.description or "",
                    "section": section,
                })
            tabs.append({
                "label": block_data.block_label,
                "active": i == 0,
                "events": block_events,
            })

    # Normalize title for block queries to avoid incorrect LLM season labels.
    normalized_title = extracted.title
    if args.query_type.value == "block" and args.block_number:
        season = _season_for_block(args.block_number) or args.season
        if season:
            normalized_title = (
                f"{season.capitalize()} {args.year} — Block {args.block_number}"
            )

    card = {
        "type": args.query_type.value,
        "title": normalized_title,
        "subtitle": extracted.subtitle or "",
        "status": card_status,
        "spotlight": spotlight,
        "events": events,
        "tabs": tabs,
        "sourceUrl": extracted.source_url or ACADEMIC_CALENDAR_SOURCE_URL,
        "suggestedQuestions": [],
        "footnote": extracted.footnote,
    }

    # ----------------------------------------------------------------
    # Self-verification: is this card worth showing?
    # If the pipeline produced garbage, return None so the frontend
    # falls back to a normal text response.
    # ----------------------------------------------------------------
    if not _verify_card(card):
        logger.warning(
            "Card self-verification FAILED — title=%r, subtitle=%r, "
            "events=%d, spotlight=%s",
            card.get("title"),
            card.get("subtitle"),
            len(events),
            bool(spotlight),
        )
        return None

    return card


# ---------------------------------------------------------------------------
# Self-verification
# ---------------------------------------------------------------------------

def _verify_card(card: dict) -> bool:
    """
    Agentic self-check: "Am I done? Did I do it correctly?"

    Returns False if the card is too broken to show to the user.
    """
    # Must have at least one event or a spotlight
    events = card.get("events", [])
    if not events and not card.get("spotlight"):
        logger.warning("Verification: no events and no spotlight")
        return False

    # Title must be meaningful (not empty or generic placeholder)
    title = (card.get("title") or "").strip()
    if not title or title.lower() in ("academic calendar", "calendar", "null"):
        logger.warning(f"Verification: weak title '{title}'")
        return False

    # Subtitle must not be the literal string "null"
    subtitle = (card.get("subtitle") or "").strip()
    if subtitle.lower() == "null":
        card["subtitle"] = ""  # Fix in-place

    return True


# ---------------------------------------------------------------------------
# Suggested follow-up questions
# ---------------------------------------------------------------------------

def compute_suggestions(
    args: CalendarToolArgs,
    extracted: ExtractedCalendarData,
) -> list[str]:
    """Generate contextual follow-up question suggestions."""
    suggestions: list[str] = []

    if args.query_type.value == "block" and args.block_number:
        other = args.block_number + 1 if args.block_number % 2 == 1 else args.block_number - 1
        if 1 <= other <= 6:
            suggestions.append(f"Show me Block {other} dates")
        if args.season:
            suggestions.append(f"Full {args.season.capitalize()} {args.year} semester")
    elif args.query_type.value == "semester" and args.season:
        season_order = ["winter", "spring", "fall"]
        idx = season_order.index(args.season) if args.season in season_order else 0
        next_season = season_order[(idx + 1) % 3]
        suggestions.append(f"{next_season.capitalize()} {args.year} semester")
    elif args.query_type.value == "graduation":
        suggestions.append("When is the next graduation?")

    if args.specific_deadline:
        suggestions.append("Show all deadlines for this block")

    if not suggestions:
        suggestions.append("Show the full academic calendar")

    return suggestions[:3]
