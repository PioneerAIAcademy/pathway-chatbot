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
    _season_for_block,
    build_calendar_card,
    compute_suggestions,
    extract_structured_data,
    is_block_extraction_misaligned,
    query_pinecone_for_calendar,
)

logger = logging.getLogger("uvicorn")

_YEAR_PATTERN = re.compile(r"\b20\d{2}\b")

_SECONDARY_TEXT_MODE_PROMPT = (
    "You classify whether a calendar response also needs a second text answer. "
    "Return JSON only with keys: mode, confidence, reason. "
    "mode must be one of: calendar_context, rag_context, clarification. "
    "Use rag_context when: "
    "(a) the user asks a non-calendar/process question alongside calendar data, OR "
    "(b) the user asks an informational/explanatory question about a calendar item "
    "(e.g. 'what should I know about…', 'tell me about…', 'what is…', 'explain…', 'what happens if…'). "
    "The calendar card only shows dates — it cannot explain meaning, consequences, or preparation steps. "
    "Use clarification when intent is truly ambiguous and you cannot determine what the user needs. "
    "Use calendar_context ONLY when the user asks a purely date/schedule question that the card fully answers "
    "(e.g. 'when is…', 'show me the dates'). "
    "confidence must be a float from 0 to 1."
)


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


def _prioritize_nodes_for_full_year_blocks(
    nodes: list[Any],
    year: int,
    *,
    max_nodes: int = 16,
) -> list[Any]:
    year_str = str(year)
    year_nodes: list[Any] = []
    fallback_nodes: list[Any] = []

    for node in nodes or []:
        text = getattr(node, "text", "") or ""
        if year_str in text:
            year_nodes.append(node)
        else:
            fallback_nodes.append(node)

    selected: list[Any] = []
    used: set[str] = set()

    def _add_node(node: Any) -> None:
        key = _node_key(node)
        if key in used:
            return
        used.add(key)
        selected.append(node)

    for block in range(1, 7):
        block_marker = f"block {block}"
        match = next(
            (
                node
                for node in year_nodes
                if block_marker in (getattr(node, "text", "") or "").lower()
            ),
            None,
        )
        if match is not None:
            _add_node(match)

    for node in [*year_nodes, *fallback_nodes]:
        if len(selected) >= max_nodes:
            break
        _add_node(node)

    return selected[:max_nodes]


def _build_retrieved_docs_metadata(
    nodes: list[Any],
    *,
    max_docs: int = 8,
    max_chars: int = 420,
) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    for idx, node in enumerate(nodes[:max_docs]):
        metadata = getattr(getattr(node, "node", None), "metadata", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}

        text = (getattr(node, "text", "") or "").strip()
        snippet = text[:max_chars]
        if len(text) > max_chars:
            snippet += "…"

        docs.append(
            {
                "rank": idx + 1,
                "score": getattr(node, "score", None),
                "url": metadata.get("url") or metadata.get("source_url"),
                "title": metadata.get("title") or metadata.get("file_name"),
                "snippet": snippet,
            }
        )

    return {
        "retrieved_nodes_count": len(nodes),
        "retrieved_docs_count": len(nodes),
        "retrieved_docs": docs,
    }


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


def _clamp_confidence(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return parsed


async def _classify_secondary_text_mode_llm(
    args: CalendarToolArgs,
    card: dict[str, Any],
    user_query: str,
) -> Optional[dict[str, Any]]:
    """Classify secondary text mode via a lightweight structured LLM call."""
    try:
        payload = {
            "user_query": user_query,
            "calendar_args": {
                "query_type": args.query_type.value,
                "scope": getattr(args, "scope", "term"),
                "season": args.season,
                "year": args.year,
                "block_number": args.block_number,
                "specific_deadline": args.specific_deadline,
            },
            "card_summary": {
                "title": card.get("title"),
                "subtitle": card.get("subtitle"),
                "spotlight_title": (card.get("spotlight") or {}).get("title"),
                "event_names": [
                    evt.get("name")
                    for evt in (card.get("events") or [])[:5]
                    if isinstance(evt, dict)
                ],
            },
        }

        response = await Settings.llm.achat(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=_SECONDARY_TEXT_MODE_PROMPT),
                ChatMessage(
                    role=MessageRole.USER,
                    content=json.dumps(payload, ensure_ascii=False),
                ),
            ],
        )

        parsed = _parse_translation_json(response.message.content or "")
        if not isinstance(parsed, dict):
            return None

        mode = str(parsed.get("mode") or "").strip().lower()
        if mode not in {"calendar_context", "rag_context", "clarification"}:
            return None

        confidence = _clamp_confidence(parsed.get("confidence"), default=0.0)
        reason = str(parsed.get("reason") or "llm_classifier").strip() or "llm_classifier"

        return {
            "mode": mode,
            "confidence": confidence,
            "reason": reason,
        }
    except Exception as e:
        logger.warning("Secondary text LLM classifier failed: %s", e)
        return None


def _card_explanation_prompt(today: date) -> str:
    return (
        "You are a BYU-Pathway student support assistant. A calendar card was just "
        "displayed to the student showing academic dates. Write 1-2 brief, helpful "
        "sentences that directly answer their question based on the card data and "
        "source documents below.\n\n"
        f"Today's date is {today.strftime('%B %d, %Y')}. Use this to determine "
        "whether dates are in the past or future.\n\n"
        "Rules:\n"
        "- Use the source_documents field (original academic calendar text) as your "
        "primary source of truth. The card data summarizes it, but the source has full details.\n"
        "- If a key deadline has already passed, briefly mention when the next "
        "block or term opens for that same thing (e.g. next registration window) "
        "if that information is available in the source documents.\n"
        "- Do NOT repeat the full list of dates — just answer the question conversationally.\n"
        "- Do NOT start with 'Based on the card' or similar meta-references.\n"
        "- NEVER say you 'can\'t provide' or 'don\'t have' information that the card "
        "already shows. The card IS your answer — summarize what it shows."
    )


async def _generate_card_explanation(
    card: dict[str, Any],
    user_query: str,
    source_context: str = "",
) -> str:
    """Generate a brief explanatory sentence from the card data and source documents."""
    spotlight = card.get("spotlight") or {}
    events = card.get("events") or []
    event_summaries = [
        f"{evt.get('name')}: {evt.get('date')} ({evt.get('status', '')})"
        for evt in events[:6]
        if isinstance(evt, dict)
    ]
    payload_dict: dict[str, Any] = {
        "user_question": user_query,
        "card_title": card.get("title"),
        "card_subtitle": card.get("subtitle"),
        "spotlight": {
            "title": spotlight.get("title"),
            "date": spotlight.get("date"),
            "status": spotlight.get("status"),
            "countdown": spotlight.get("countdown"),
        } if spotlight else None,
        "key_events": event_summaries,
    }
    tabs = card.get("tabs") or []
    if tabs:
        tab_summaries = []
        for tab in tabs:
            label = tab.get("label", "")
            tab_events = tab.get("events") or []
            tab_event_names = [e.get("name", "") for e in tab_events[:4] if isinstance(e, dict)]
            tab_summaries.append(f"{label}: {len(tab_events)} events ({', '.join(tab_event_names)})")
        payload_dict["blocks_shown"] = tab_summaries
    if source_context:
        payload_dict["source_documents"] = source_context[:2000]
    payload = json.dumps(payload_dict, ensure_ascii=False)

    today = date.today()
    try:
        response = await Settings.llm.achat(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=_card_explanation_prompt(today)),
                ChatMessage(role=MessageRole.USER, content=payload),
            ],
        )
        return (response.message.content or "").strip()
    except Exception as e:
        logger.warning("Card explanation generation failed: %s", e)
        return ""


async def build_secondary_calendar_text(
    args: CalendarToolArgs,
    card: dict[str, Any],
    user_query: Optional[str],
    source_context: str = "",
) -> dict[str, Any]:
    """Build post-card text plan using LLM classification."""
    query = (user_query or "").strip()
    if not query:
        return {"mode": "calendar_context", "confidence": 0.9, "reason": "no_query", "text": ""}

    llm_plan = await _classify_secondary_text_mode_llm(args, card, query)
    if not llm_plan:
        return {"mode": "calendar_context", "confidence": 0.5, "reason": "llm_failed", "text": ""}

    mode = str(llm_plan.get("mode") or "calendar_context").strip().lower()
    confidence = _clamp_confidence(llm_plan.get("confidence"), 0.5)
    reason = str(llm_plan.get("reason") or "llm_classifier").strip() or "llm_classifier"

    if mode == "rag_context":
        return {"mode": "rag_context", "confidence": confidence, "reason": reason, "text": ""}

    if mode == "clarification":
        return {
            "mode": "clarification",
            "confidence": confidence,
            "reason": reason,
            "text": (
                "I can walk you through the calendar deadlines here. "
                "Do you also want me to answer the non-calendar part separately?"
            ),
        }

    # For calendar_context: generate a brief explanation from the card data + source docs
    explanation = await _generate_card_explanation(card, query, source_context=source_context)
    return {"mode": "calendar_context", "confidence": confidence, "reason": reason, "text": explanation}


def build_calendar_intro(args: CalendarToolArgs) -> str:
    """Build a short intro sentence for a calendar card."""
    qt = args.query_type.value
    scope = (getattr(args, "scope", "term") or "term").lower()
    season_raw = _normalize_season(args.season)
    season = season_raw.capitalize() if season_raw else ""
    year = args.year

    def _block_label() -> str:
        canonical = _season_for_block(args.block_number) or season_raw
        if canonical:
            return f"{canonical.capitalize()} {year} \u2014 Block {args.block_number}"
        return f"Block {args.block_number} ({year})"

    def _scope_label() -> str:
        if args.block_number:
            return _block_label()
        if season:
            return f"{season} {year}"
        return str(year)

    if qt == "block" and args.block_number:
        return f"Here are the key dates for {_block_label()}:"

    if qt == "semester":
        if scope == "full_year":
            return f"Here's the full {year} academic calendar:"
        if season:
            return f"Here are the key dates for {season} {year}:"
        return f"Here's the {year} academic calendar:"

    if qt == "deadline":
        if args.specific_deadline:
            deadline = _humanize_deadline(args.specific_deadline)
            return f"Here's the {deadline} deadline for {_scope_label()}:"
        if args.block_number:
            return f"Here are the key deadlines for {_block_label()}:"
        return f"Here are the key deadlines for {_scope_label()}:"

    if qt == "graduation":
        if season:
            return f"Here are the {season} {year} graduation dates:"
        return f"Here are the {year} graduation dates:"

    if season:
        return f"Here's the {season} {year} calendar:"
    return f"Here's the academic calendar for {year}:"


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

            for block in range(1, 7):
                block_query = (
                    f"academic calendar {calendar_args.year} block {block} "
                    f"start end dates deadlines"
                )
                try:
                    block_nodes = await retriever.aretrieve(block_query)
                    expanded_nodes = _merge_nodes(expanded_nodes, block_nodes, max_nodes=30)
                except Exception as e:
                    logger.warning(
                        "Calendar pipeline: block expansion query failed (block %s): %s",
                        block,
                        e,
                    )

            if expanded_nodes:
                nodes = _merge_nodes(nodes, expanded_nodes, max_nodes=30)
                metadata["retrieval_mode"] = "full_year_expanded"

            nodes = _prioritize_nodes_for_full_year_blocks(
                nodes,
                calendar_args.year,
                max_nodes=16,
            )
            metadata["retrieval_mode"] = (
                f"{metadata.get('retrieval_mode', 'full_year')}+block_coverage_prioritized"
            )

        if not nodes:
            logger.warning("Calendar pipeline: no Pinecone nodes returned")
            metadata["pipeline_status"] = "no_nodes"
            return None, metadata

        logger.info("Calendar pipeline: got %d nodes", len(nodes))
        metadata.update(_build_retrieved_docs_metadata(nodes))

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
                resolved_season = calendar_args.season or _season_for_block(
                    calendar_args.block_number
                )
                if resolved_season:
                    strict_query += f" {resolved_season}"
                if calendar_args.block_number:
                    strict_query += f" block {calendar_args.block_number}"

                strict_nodes = await retriever.aretrieve(strict_query)
                if strict_nodes:
                    nodes = strict_nodes
                    metadata.update(_build_retrieved_docs_metadata(nodes))
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

        if (
            calendar_args.query_type.value == "block"
            and calendar_args.block_number
            and is_block_extraction_misaligned(extracted, calendar_args)
        ):
            logger.warning(
                "Calendar pipeline: block extraction appears misaligned (block=%s year=%s); retrying strict block extraction",
                calendar_args.block_number,
                calendar_args.year,
            )

            resolved_season = calendar_args.season or _season_for_block(
                calendar_args.block_number
            )
            strict_block_query = (
                f"academic calendar {calendar_args.year} "
                f"{resolved_season or ''} block {calendar_args.block_number} "
                "start end dates deadlines"
            ).strip()
            strict_block_nodes = await retriever.aretrieve(strict_block_query)
            if strict_block_nodes:
                metadata.update(_build_retrieved_docs_metadata(strict_block_nodes))
                metadata["retrieval_mode"] = "strict_block_retry"
                strict_extracted = await extract_structured_data(
                    strict_block_nodes,
                    calendar_args,
                )
                if strict_extracted and not is_block_extraction_misaligned(
                    strict_extracted,
                    calendar_args,
                ):
                    extracted = strict_extracted
                    logger.info("Calendar pipeline: strict block extraction corrected alignment")
                else:
                    logger.warning(
                        "Calendar pipeline: strict block retry did not improve alignment; keeping original extraction"
                    )

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

        # Build source context from raw Pinecone nodes so the explanation
        # LLM has full document data (like RAG would) to answer accurately.
        source_context = "\n\n---\n\n".join(
            n.text for n in nodes[:6] if hasattr(n, "text")
        )[:2000]

        secondary_plan = await build_secondary_calendar_text(
            calendar_args,
            card,
            user_query=user_query,
            source_context=source_context,
        )
        card["secondaryTextMode"] = secondary_plan.get("mode")
        card["secondaryTextConfidence"] = secondary_plan.get("confidence")

        secondary_text = str(secondary_plan.get("text") or "").strip()
        if secondary_text:
            secondary_text = await localize_calendar_intro(
                secondary_text,
                user_language=user_language,
                original_user_message=user_query or "",
            )
            card["postCardText"] = secondary_text

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
                "secondary_text": {
                    "mode": secondary_plan.get("mode"),
                    "confidence": secondary_plan.get("confidence"),
                    "reason": secondary_plan.get("reason"),
                },
            }
        )
        logger.info("Calendar pipeline: card built & verified successfully")
        return card, metadata

    except Exception as e:
        logger.error(f"Calendar pipeline error: {e}", exc_info=True)
        metadata.update({"pipeline_status": "error", "pipeline_error": str(e)})
        return None, metadata
