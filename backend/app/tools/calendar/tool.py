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
import re
from datetime import date, datetime
from typing import Optional

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.settings import Settings
from zoneinfo import ZoneInfo

from app.tools.calendar.schema import (
	CalendarToolArgs,
	ExtractedCalendarData,
	ExtractedCalendarEvent,
)
from app.tools.calendar.vocabulary import event_matches_deadline

logger = logging.getLogger("uvicorn")

ACADEMIC_CALENDAR_SOURCE_URL = (
	"https://studentservices.byupathway.edu/studentservices/academic-calendar"
)


def get_calendar_tool_definition() -> dict:
	"""Return the OpenAI-compatible function schema for the calendar tool."""
	return {
		"type": "function",
		"function": {
			"name": "lookup_academic_calendar",
			"description": (
				"Look up BYU-Pathway academic calendar dates, deadlines, "
				"block schedules, and graduation information. "
				"Call this when the user is clearly asking about academic calendar "
				"dates, registration deadlines, block start/end dates, payment "
				"deadlines, drop deadlines, graduation dates, or commencement. "
				"Note: students may say 'term', 'block', or 'semester' "
				"interchangeably \u2014 treat all three as synonyms. "
				"Do NOT call this for questions about gatherings, classes, "
				"certificates, or general scheduling unrelated to the academic calendar."
			),
			"parameters": CalendarToolArgs.model_json_schema(),
		},
	}


def _get_today(user_timezone: str) -> date:
	try:
		return datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		return datetime.now(ZoneInfo("UTC")).date()


def _classify_date(event_date: date, today: date) -> str:
	delta = (event_date - today).days
	if delta < 0:
		return "past"
	if delta == 0:
		return "today"
	if delta <= 7:
		return "soon"
	return "upcoming"


def _countdown_str(event_date: date, today: date) -> str:
	delta = (event_date - today).days
	if delta < 0:
		return "Passed"
	if delta == 0:
		return "Today"
	if delta == 1:
		return "Tomorrow"
	return f"{delta} days"


def _urgency_for_delta_days(delta_days: int) -> str:
	if delta_days < 0:
		return "calm"
	if delta_days <= 2:
		return "urgent"
	if delta_days <= 7:
		return "warning"
	return "info"


def _season_for_block(block_number: Optional[int]) -> Optional[str]:
	if block_number in (1, 2):
		return "winter"
	if block_number in (3, 4):
		return "spring"
	if block_number in (5, 6):
		return "fall"
	return None


def _in_block_window(event_date: date, block_number: int, year: int) -> bool:
	if block_number == 1:
		return (event_date.year == year - 1 and event_date.month in (11, 12)) or (
			event_date.year == year and event_date.month in (1, 2)
		)
	if block_number == 2:
		return event_date.year == year and event_date.month in (1, 2, 3, 4)
	if block_number == 3:
		return event_date.year == year and event_date.month in (3, 4, 5, 6)
	if block_number == 4:
		return event_date.year == year and event_date.month in (5, 6, 7, 8)
	if block_number == 5:
		return event_date.year == year and event_date.month in (7, 8, 9, 10)
	if block_number == 6:
		return event_date.year == year and event_date.month in (9, 10, 11, 12)
	return event_date.year == year


def is_block_extraction_misaligned(
	extracted: ExtractedCalendarData,
	args: CalendarToolArgs,
) -> bool:
	if args.query_type.value != "block" or not args.block_number:
		return False

	parsed_dates: list[date] = []
	for evt in extracted.events:
		try:
			parsed_dates.append(date.fromisoformat(evt.date))
		except ValueError:
			continue

	if len(parsed_dates) < 3:
		return False

	in_window = [
		evt_date
		for evt_date in parsed_dates
		if _in_block_window(evt_date, args.block_number, args.year)
	]
	ratio = len(in_window) / max(len(parsed_dates), 1)
	return ratio < 0.5


def _format_range(start_date: date, end_date: date) -> str:
	if start_date.year == end_date.year:
		return (
			f"{start_date.strftime('%B')} {start_date.day} – "
			f"{end_date.strftime('%B')} {end_date.day}, {start_date.year}"
		)
	return (
		f"{start_date.strftime('%B')} {start_date.day}, {start_date.year} – "
		f"{end_date.strftime('%B')} {end_date.day}, {end_date.year}"
	)

def _expected_blocks_for_scope(
	scope: str,
	season: Optional[str],
) -> list[int]:
	"""Return the block numbers expected for a given scope/season."""
	if scope == "full_year":
		return [1, 2, 3, 4, 5, 6]
	season_lower = (season or "").strip().lower()
	if season_lower in ("winter",):
		return [1, 2]
	if season_lower in ("spring", "summer"):
		return [3, 4]
	if season_lower in ("fall",):
		return [5, 6]
	return []


def _ensure_all_block_tabs(
	tabs: list[dict],
	flat_events: list[ExtractedCalendarEvent],
	expected_blocks: list[int],
	year: int,
	today: date,
) -> list[dict]:
	"""Ensure all expected block tabs exist; fill missing ones from flat events."""
	existing_block_nums: set[int] = set()
	for tab in tabs:
		m = re.search(r"\d+", tab.get("label") or "")
		if m:
			existing_block_nums.add(int(m.group()))

	missing = [b for b in expected_blocks if b not in existing_block_nums]
	if not missing:
		return tabs

	logger.warning(
		"Block tabs missing %s — filling from flat events (%d total)",
		missing,
		len(flat_events),
	)

	for block_num in missing:
		block_events = []
		for evt in flat_events:
			try:
				evt_date = date.fromisoformat(evt.date)
			except ValueError:
				continue
			if not _in_block_window(evt_date, block_num, year):
				continue
			status = _classify_date(evt_date, today)
			countdown = _countdown_str(evt_date, today)
			section = "Past" if status == "past" else "Today" if status == "today" else "Coming Up"
			block_events.append({
				"date": evt.date,
				"name": evt.name,
				"status": status,
				"countdown": countdown,
				"description": evt.description or "",
				"section": section,
			})
		tabs.append({
			"label": f"Block {block_num}",
			"active": False,
			"events": block_events,
		})

	# Sort tabs by block number
	def _tab_sort_key(tab: dict) -> int:
		m = re.search(r"\d+", tab.get("label") or "")
		return int(m.group()) if m else 999

	tabs.sort(key=_tab_sort_key)
	# Re-set active: first tab is active
	for i, tab in enumerate(tabs):
		tab["active"] = i == 0

	return tabs

async def query_pinecone_for_calendar(args: CalendarToolArgs, retriever) -> list:
	query_parts = ["academic calendar"]
	year_included = False
	scope = (getattr(args, "scope", "term") or "term").lower()
	resolved_season = args.season or _season_for_block(args.block_number)

	if scope == "full_year":
		query_parts.append(
			f"full year {args.year} winter spring fall all blocks start end dates deadlines"
		)
		year_included = True
	elif resolved_season:
		query_parts.append(f"{resolved_season} {args.year}")
		year_included = True
	if args.block_number:
		query_parts.append(f"block {args.block_number}")
	if args.specific_deadline:
		deadline_label = args.specific_deadline.replace("_", " ")
		query_parts.append(f"{deadline_label} deadline")
	if args.query_type.value == "graduation":
		query_parts.append("graduation commencement")
	if not year_included:
		query_parts.append(str(args.year))

	query_text = " ".join(query_parts)
	logger.info(f"Calendar Pinecone query: {query_text}")
	return await retriever.aretrieve(query_text)


_MAX_CONTEXT_CHARS = 4000
_MAX_CONTEXT_CHARS_FULL_YEAR = 14000
_MAX_CONTEXT_NODES_FULL_YEAR = 16
_MAX_EXTRACTION_ATTEMPTS = 2
_MAX_EXTRACTION_ATTEMPTS_FULL_YEAR = 1

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
	'  "blocks": null or [{"block_label": "Block 3", "events": [...same event shape...]}]\n'
	"}\n"
	"Rules:\n"
	"- WARNING: DO NOT INVENT, SHIFT, OR EXTRAPOLATE YEARS OR DATES. USE ONLY DATES EXPLICITLY PRESENT IN DOCUMENTS.\n"
	"- Include events matching the query AND closely related events that give "
	"the student a complete picture. For example, if the query is about "
	"'registration', include Registration Opens, Add/Drop Deadline, "
	"and any other dates that define the registration window. "
	"If the query is about a block or semester, include Start, End, "
	"and all key deadlines for that period.\n"
	"- If scope is full_year, include all relevant events across Winter, Spring, and Fall for that year, grouped by block where possible.\n"
	"- Dates MUST be ISO format YYYY-MM-DD. Omit events with ambiguous dates.\n"
	"- For semester queries, group events by block in the 'blocks' field.\n"
	"- CRITICAL: Each block must only contain dates that belong to THAT block. "
	"Do NOT put semester-level dates or other block dates under the wrong block. "
	"For example, Block 5 end date is NOT the same as the semester end date — "
	"use the specific block end date from the source documents.\n"
	"- CRITICAL: A full academic year ALWAYS has exactly 6 blocks: "
	"Block 1 & 2 (Winter), Block 3 & 4 (Spring), Block 5 & 6 (Fall). "
	"A single semester (Winter, Spring, or Fall) ALWAYS has exactly 2 blocks. "
	"You MUST include ALL blocks — never skip any.\n"
	"- CRITICAL: block_label MUST use the CANONICAL block number: "
	"Winter = Block 1, Block 2. Spring = Block 3, Block 4. Fall = Block 5, Block 6. "
	"Do NOT number blocks starting from 1 within each semester. "
	"The first Spring block is ALWAYS 'Block 3', NEVER 'Block 1'.\n"	"- For single-block queries, leave 'blocks' as null.\n"
	"- IMPORTANT: Every event MUST have a short 'description' (1 sentence, max 15 words). "
	"Explain what it means for the student.\n"
)


async def extract_structured_data(
	nodes: list,
	args: CalendarToolArgs,
) -> Optional[ExtractedCalendarData]:
	if not nodes:
		return None

	scope = (getattr(args, "scope", "term") or "term").lower()
	resolved_season = args.season or _season_for_block(args.block_number)
	max_chars = _MAX_CONTEXT_CHARS_FULL_YEAR if scope == "full_year" else _MAX_CONTEXT_CHARS
	max_nodes = _MAX_CONTEXT_NODES_FULL_YEAR if scope == "full_year" else 10
	max_attempts = (
		_MAX_EXTRACTION_ATTEMPTS_FULL_YEAR
		if scope == "full_year"
		else _MAX_EXTRACTION_ATTEMPTS
	)

	context_parts: list[str] = []
	total_chars = 0
	for node in nodes[:max_nodes]:
		text = node.text
		if total_chars + len(text) > max_chars:
			remaining = max_chars - total_chars
			if remaining > 200:
				context_parts.append(text[:remaining] + "\n[...truncated]")
			break
		context_parts.append(text)
		total_chars += len(text)
	context = "\n\n---\n\n".join(context_parts)

	query_desc = args.query_type.value
	if resolved_season:
		query_desc += f" for {resolved_season} {args.year}"
	elif scope == "full_year":
		query_desc += f" for full year {args.year}"
	if args.block_number:
		query_desc += f" block {args.block_number}"
	if args.specific_deadline:
		query_desc += f", specifically the {args.specific_deadline} deadline"

	user_content = f"Extract calendar data for: {query_desc}\n\nDocuments:\n{context}"
	last_error: Optional[str] = None

	for attempt in range(1, max_attempts + 1):
		try:
			logger.info(f"Extraction attempt {attempt}/{max_attempts}")
			response = await Settings.llm.achat(
				messages=[
					ChatMessage(role=MessageRole.SYSTEM, content=_EXTRACTION_SYSTEM),
					ChatMessage(role=MessageRole.USER, content=user_content),
				],
			)
			raw = response.message.content.strip()
			if raw.startswith("```"):
				raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
				if raw.endswith("```"):
					raw = raw[:-3].strip()

			data = json.loads(raw)
			for key in {"title", "subtitle", "events", "source_url"}:
				if key in data and (data[key] is None or data[key] == "null"):
					del data[key]

			extracted = ExtractedCalendarData(**data)
			if not extracted.events:
				last_error = "extraction returned 0 events"
				logger.warning(
					f"Attempt {attempt}: {last_error} — "
					f"{'retrying' if attempt < max_attempts else 'giving up'}"
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
				f"{'retrying' if attempt < max_attempts else 'giving up'}"
			)
		except Exception as e:
			last_error = f"extraction error: {e}"
			logger.error(
				f"Attempt {attempt}: {last_error} — "
				f"{'retrying' if attempt < max_attempts else 'giving up'}"
			)

	logger.error(f"All {max_attempts} extraction attempts failed. Last: {last_error}")
	return None


def build_calendar_card(
	extracted: ExtractedCalendarData,
	args: CalendarToolArgs,
	today: date,
) -> Optional[dict]:
	events_source = extracted.events
	if args.query_type.value == "block" and args.block_number:
		filtered_events: list[ExtractedCalendarEvent] = []
		for evt in extracted.events:
			try:
				evt_date = date.fromisoformat(evt.date)
			except ValueError:
				continue
			if _in_block_window(evt_date, args.block_number, args.year):
				filtered_events.append(evt)
		if filtered_events:
			events_source = filtered_events

	card_status = "upcoming"
	if extracted.block_or_semester_start and extracted.block_or_semester_end:
		try:
			start = date.fromisoformat(extracted.block_or_semester_start)
			end = date.fromisoformat(extracted.block_or_semester_end)
			if (
				args.query_type.value == "block"
				and args.block_number
				and (
					not _in_block_window(start, args.block_number, args.year)
					or not _in_block_window(end, args.block_number, args.year)
				)
			):
				start = None
				end = None
			if start is not None and end is not None:
				extracted.block_or_semester_start = start.isoformat()
				extracted.block_or_semester_end = end.isoformat()
				if today > end:
					card_status = "past"
				elif today >= start:
					card_status = "active"
		except ValueError:
			pass

	events = []
	spotlight = None
	parsed_events: list[tuple[date, ExtractedCalendarEvent]] = []
	for evt in events_source:
		try:
			evt_date = date.fromisoformat(evt.date)
		except ValueError:
			continue
		parsed_events.append((evt_date, evt))

	parsed_events.sort(key=lambda pair: pair[0])
	for evt_date, evt in parsed_events:
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
		event_dict["section"] = "Past" if status == "past" else "Today" if status == "today" else "Coming Up"
		events.append(event_dict)

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
				evt_date = date.fromisoformat(evt_dict["date"])
				delta_days = (evt_date - today).days
				spotlight = {
					"urgency": _urgency_for_delta_days(delta_days),
					"date": evt_dict["date"],
					"title": evt_dict["name"],
					"description": evt_dict.get("description", ""),
					"countdown": f"{evt_dict['countdown']} remaining",
				}
				break

	timeline_events = events
	if args.query_type.value == "deadline" and args.specific_deadline:
		filtered_events = [
			evt_dict
			for evt_dict in timeline_events
			if event_matches_deadline(evt_dict.get("name", ""), args.specific_deadline)
		]
		if filtered_events:
			timeline_events = filtered_events
			if spotlight and not event_matches_deadline(
				spotlight.get("title", ""),
				args.specific_deadline,
			):
				spotlight = None

	if spotlight:
		removed = False
		deduped_events = []
		for evt_dict in timeline_events:
			is_spotlight_match = (
				not removed
				and evt_dict.get("date") == spotlight.get("date")
				and evt_dict.get("name") == spotlight.get("title")
			)
			if is_spotlight_match:
				removed = True
				continue
			deduped_events.append(evt_dict)
		timeline_events = deduped_events

	tabs = None
	if args.query_type.value == "semester" and extracted.blocks:
		tabs = []
		for i, block_data in enumerate(extracted.blocks):
			# Parse block number from label (e.g. "Block 5" -> 5) for date filtering
			block_num_match = re.search(r"\d+", block_data.block_label or "")
			block_num = int(block_num_match.group()) if block_num_match else None

			block_events = []
			for evt in block_data.events:
				try:
					evt_date = date.fromisoformat(evt.date)
				except ValueError:
					continue
				# Filter out events that don't belong in this block's date window
				if block_num and not _in_block_window(evt_date, block_num, args.year):
					continue
				status = _classify_date(evt_date, today)
				countdown = _countdown_str(evt_date, today)
				section = "Past" if status == "past" else "Today" if status == "today" else "Coming Up"
				block_events.append({
					"date": evt.date,
					"name": evt.name,
					"status": status,
					"countdown": countdown,
					"description": evt.description or "",
					"section": section,
				})
			tabs.append({"label": block_data.block_label, "active": i == 0, "events": block_events})

		# Ensure all expected blocks are present (fill missing from flat events)
		scope = (getattr(args, "scope", "term") or "term").lower()
		expected = _expected_blocks_for_scope(scope, args.season)
		if expected:
			tabs = _ensure_all_block_tabs(
				tabs, extracted.events, expected, args.year, today,
			)

	normalized_title = extracted.title
	normalized_subtitle = extracted.subtitle or ""
	scope = (getattr(args, "scope", "term") or "term")
	scope_val = scope.value if hasattr(scope, "value") else str(scope)

	if scope_val == "full_year":
		normalized_title = f"{args.year} Academic Calendar"
		# Compute full-year subtitle from all tab events
		all_dates: list[date] = []
		for tab in tabs:
			for evt in tab.get("events", []):
				try:
					all_dates.append(date.fromisoformat(evt["date"]))
				except (ValueError, KeyError):
					pass
		if all_dates:
			normalized_subtitle = _format_range(min(all_dates), max(all_dates))
	elif args.query_type.value == "semester" and args.season:
		normalized_title = f"{args.season.capitalize()} {args.year}"
	elif args.query_type.value == "block" and args.block_number:
		season = _season_for_block(args.block_number) or args.season
		if season:
			normalized_title = f"{season.capitalize()} {args.year} — Block {args.block_number}"

		start_event = next(
			(evt for evt in events_source if "start" in (evt.name or "").lower()),
			None,
		)
		end_event = next(
			(evt for evt in events_source if (evt.name or "").strip().lower() == "end"),
			None,
		)
		if start_event and end_event:
			try:
				start_date = date.fromisoformat(start_event.date)
				end_date = date.fromisoformat(end_event.date)
				normalized_subtitle = _format_range(start_date, end_date)
				extracted.block_or_semester_start = start_event.date
				extracted.block_or_semester_end = end_event.date
			except ValueError:
				pass

	card = {
		"type": args.query_type.value,
		"title": normalized_title,
		"subtitle": normalized_subtitle,
		"status": card_status,
		"spotlight": spotlight,
		"events": timeline_events,
		"tabs": tabs,
		"sourceUrl": extracted.source_url or ACADEMIC_CALENDAR_SOURCE_URL,
		"suggestedQuestions": [],
		"footnote": extracted.footnote,
	}

	if not _verify_card(card):
		logger.warning(
			"Card self-verification FAILED — title=%r, subtitle=%r, events=%d, spotlight=%s",
			card.get("title"),
			card.get("subtitle"),
			len(events),
			bool(spotlight),
		)
		return None
	return card


def _verify_card(card: dict) -> bool:
	events = card.get("events", [])
	if not events and not card.get("spotlight"):
		logger.warning("Verification: no events and no spotlight")
		return False

	title = (card.get("title") or "").strip()
	if not title or title.lower() in ("academic calendar", "calendar", "null"):
		logger.warning(f"Verification: weak title '{title}'")
		return False

	subtitle = (card.get("subtitle") or "").strip()
	if subtitle.lower() == "null":
		card["subtitle"] = ""

	return True


def compute_suggestions(
	args: CalendarToolArgs,
	extracted: ExtractedCalendarData,
	user_query: Optional[str] = None,
) -> list[str]:
	def _normalize_phrase(value: str) -> str:
		text = (value or "").lower().strip()
		text = re.sub(r"[^a-z0-9\s]", " ", text)
		text = re.sub(r"\b(can|could|would|you|please|me|the|a|an)\b", " ", text)
		text = re.sub(r"\s+", " ", text).strip()
		return text

	normalized_user_query = _normalize_phrase(user_query or "")

	def _add_unique(items: list[str], value: str) -> None:
		clean = (value or "").strip()
		if not clean:
			return
		normalized_clean = _normalize_phrase(clean)
		if normalized_user_query and (
			normalized_clean == normalized_user_query
			or normalized_clean in normalized_user_query
			or normalized_user_query in normalized_clean
		):
			return
		lowered = clean.lower()
		if lowered in {i.lower() for i in items}:
			return
		items.append(clean)

	def _event_focus_question(event_name: str, event_date: str) -> str:
		event_lower = (event_name or "").lower()
		if "registration" in event_lower:
			if any(token in event_lower for token in ("open", "opens", "opening")):
				return "How do I prepare for registration?"
			if "deadline" in event_lower:
				return "How do I prepare for the registration deadline?"
			return f"What should I know about {event_name}?"
		if "payment" in event_lower or "fees" in event_lower:
			return f"What if I miss {event_name}?"
		if "drop" in event_lower or "withdraw" in event_lower:
			return f"What are my options after {event_name}?"
		if "grade" in event_lower and "available" in event_lower:
			return "When and where can I view final grades?"
		if "grade" in event_lower:
			return f"How should I prepare for {event_name}?"
		if "graduation" in event_lower or "commencement" in event_lower:
			return f"How do I get ready for {event_name}?"
		if any(token in event_lower for token in ("opens", "open", "opening", "begins", "begin", "starts", "start", "ends", "end", "closes", "close")):
			return f"What should I know before {event_name}?"
		if "available" in event_lower:
			return f"When does {event_name} happen?"
		return f"What should I know about {event_name}?"

	suggestions: list[str] = []

	# 1) Deterministic anchor suggestion (safe + predictable)
	if args.query_type.value == "block" and args.block_number:
		other = args.block_number + 1 if args.block_number % 2 == 1 else args.block_number - 1
		if 1 <= other <= 6:
			_add_unique(suggestions, f"Show Block {other} dates")
		if args.season:
			_add_unique(suggestions, f"Full {args.season.capitalize()} semester")
	elif args.query_type.value == "semester" and args.season:
		season_order = ["winter", "spring", "fall"]
		idx = season_order.index(args.season) if args.season in season_order else 0
		next_season = season_order[(idx + 1) % 3]
		_add_unique(suggestions, f"Show {next_season.capitalize()} semester")
	elif args.query_type.value == "graduation":
		_add_unique(suggestions, "What are the next graduation steps?")
	elif args.query_type.value == "deadline":
		_add_unique(suggestions, "Show all key deadlines")

	# 2) Event-aware conversational suggestions (on-topic, extracted-data grounded)
	for evt in extracted.events[:3]:
		_add_unique(suggestions, _event_focus_question(evt.name, evt.date))
		if len(suggestions) >= 2:
			break

	# 3) Deadline-specific follow-up when relevant
	if args.specific_deadline and len(suggestions) < 2:
		_add_unique(suggestions, "Is there a grace period?")

	# 4) Fallback
	if not suggestions:
		_add_unique(suggestions, "Show me the full academic calendar")

	return suggestions[:2]
