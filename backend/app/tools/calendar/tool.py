"""
Calendar tool: LLM-invoked tool for academic calendar queries.

Flow:
1. LLM decides to call `lookup_academic_calendar` with typed args
2. Tool queries Pinecone with calendar-specific metadata filters
3. LLM extracts structured data from chunks (strict JSON schema)
4. Deterministic Python computes date classifications, countdowns, urgency
5. Returns CalendarCardData dict ready for frontend
"""

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime
from typing import Optional

from openai import AsyncOpenAI
from zoneinfo import ZoneInfo

from app.tools.calendar.schema import (
	CalendarToolArgs,
	ExtractedBlockData,
	ExtractedCalendarData,
	ExtractedCalendarEvent,
)
from app.tools.calendar.vocabulary import event_matches_deadline

logger = logging.getLogger("uvicorn")

from app.tools.calendar.config import ACADEMIC_CALENDAR_URL


def _get_openai_client() -> AsyncOpenAI:
	"""Lazy singleton for direct OpenAI calls (JSON mode)."""
	if not hasattr(_get_openai_client, "_client"):
		_get_openai_client._client = AsyncOpenAI()
	return _get_openai_client._client

ACADEMIC_CALENDAR_SOURCE_URL = ACADEMIC_CALENDAR_URL


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
	"""Loose month-based window used by _ensure_all_block_tabs to fill missing blocks.

	Includes adjacent-month overlap so registration/prep dates that precede a
	block's actual start are captured.  NOT used for filtering LLM-returned
	block events (those are trusted).
	"""
	if block_number == 1:
		return (event_date.year == year - 1 and event_date.month in (11, 12)) or (
			event_date.year == year and event_date.month in (1, 2)
		)
	if block_number == 2:
		return event_date.year == year and event_date.month in (2, 3, 4)
	if block_number == 3:
		return event_date.year == year and event_date.month in (4, 5, 6)
	if block_number == 4:
		return event_date.year == year and event_date.month in (6, 7, 8)
	if block_number == 5:
		return event_date.year == year and event_date.month in (8, 9, 10)
	if block_number == 6:
		return event_date.year == year and event_date.month in (10, 11, 12)
	return event_date.year == year


# Maximum events per tab before we consider the LLM duplicated events
_MAX_EVENTS_PER_TAB = 20


def _strict_block_from_date(event_date: date, year: int) -> int:
	"""Non-overlapping block assignment by 2-month buckets.

	Used as a deterministic fallback when LLM block grouping is unreliable.
	Jan-Feb → 1, Mar-Apr → 2, May-Jun → 3, Jul-Aug → 4, Sep-Oct → 5, Nov-Dec → 6.
	"""
	if event_date.year != year:
		return 1
	return min(max(1, (event_date.month + 1) // 2), 6)


def _build_block_events_from_flat(
	flat_events: list[ExtractedCalendarEvent],
	block_num: int,
	year: int,
	today: date,
) -> list[dict]:
	"""Build a single block's event list from flat events using _in_block_window."""
	events = []
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
		events.append({
			"date": evt.date,
			"name": evt.name,
			"status": status,
			"countdown": countdown,
			"description": evt.description or "",
			"section": section,
		})
	events.sort(key=lambda e: e["date"])
	return events


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
_MAX_CONTEXT_CHARS_FULL_YEAR = 15000
_MAX_CONTEXT_NODES_FULL_YEAR = 16
_MAX_EXTRACTION_ATTEMPTS = 2
_MAX_EXTRACTION_ATTEMPTS_FULL_YEAR = 2

_EXTRACTION_SYSTEM = (
	"You extract structured academic calendar data from documents. "
	"Return a JSON object matching this schema:\n"
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
	"- DO NOT INVENT OR EXTRAPOLATE DATES. Use only dates explicitly in the documents.\n"
	"- Each block has up to 13 event types. Extract ALL of them when present:\n"
	"  Start, Financial Holds Applied, Registration Opens, Application Deadline, "
	"Add Course Deadline, Tuition Discount Deadline, Drop/Auto-Drop Deadline, "
	"Last Day for a Refund, Payment Deadline, Late Fees Applied, "
	"Last Day to Withdraw with a W Grade, Grades Available, End.\n"
	"- For block/semester queries, include ALL events for the block — not just a subset.\n"
	"- For deadline queries, include the specific deadline + all related events for context.\n"
	"- If scope is full_year, include all events across Winter, Spring, and Fall, grouped by block.\n"
	"- Dates MUST be ISO YYYY-MM-DD. Omit events with ambiguous dates.\n"
	"- For semester queries, group events by block in the 'blocks' field.\n"
	"- Each block must only contain dates belonging to THAT block. "
	"A full year has exactly 6 blocks: Block 1-2 (Winter), Block 3-4 (Spring), Block 5-6 (Fall). "
	"A semester has exactly 2 blocks. Include ALL blocks — never skip any. "
	"block_label MUST use CANONICAL numbers (Spring Block 3, not Block 1).\n"
	"- For single-block queries, leave 'blocks' as null.\n"
	"- Every event MUST have a short 'description' (1 sentence, max 15 words).\n"
)


def _deduplicate_node_content(nodes: list) -> list:
	"""Remove nodes whose text content is a duplicate of an earlier node."""
	seen_texts: set[str] = set()
	unique: list = []
	for node in nodes:
		text = (getattr(node, "text", "") or "").strip()
		if not text:
			continue
		# Use first 200 chars as fingerprint to catch near-duplicates
		fingerprint = text[:200]
		if fingerprint in seen_texts:
			continue
		seen_texts.add(fingerprint)
		unique.append(node)
	return unique


_SEMESTER_BLOCKS: dict[str, tuple[int, int]] = {
	"winter": (1, 2),
	"spring": (3, 4),
	"fall": (5, 6),
}


async def extract_structured_data(
	nodes: list,
	args: CalendarToolArgs,
	semester_focus: Optional[str] = None,
) -> Optional[ExtractedCalendarData]:
	if not nodes:
		return None

	# Phase 4: deduplicate before building context
	nodes = _deduplicate_node_content(nodes)

	scope = (getattr(args, "scope", "term") or "term").lower()
	resolved_season = args.season or _season_for_block(args.block_number)

	if semester_focus:
		# Per-semester extraction within full-year pipeline: use full context, 2 attempts
		max_chars = _MAX_CONTEXT_CHARS_FULL_YEAR
		max_nodes = _MAX_CONTEXT_NODES_FULL_YEAR
		max_attempts = _MAX_EXTRACTION_ATTEMPTS
		# Filter context to only the 2 relevant per-block chunks.
		# The full Pinecone context has Block/Term 1-6 + Semester chunks.
		# Giving all 12 confuses the LLM (picks wrong blocks for Spring).
		# Giving only the 2 target blocks eliminates cross-block contamination.
		block_lo, block_hi = _SEMESTER_BLOCKS.get(semester_focus, (0, 0))
		target_labels = (
			f"Block/Term {block_lo}",
			f"Block {block_lo}",
			f"Block/Term {block_hi}",
			f"Block {block_hi}",
		)
		targeted_nodes = [
			n for n in nodes
			if any(label in (getattr(n, "text", "") or "")[:80] for label in target_labels)
		]
		if len(targeted_nodes) >= 2:
			nodes = targeted_nodes
		else:
			# Fallback: remove semester-level chunks at minimum
			filtered_nodes = [
				n for n in nodes
				if "Semester" not in (getattr(n, "text", "") or "")[:100]
			]
			if filtered_nodes:
				nodes = filtered_nodes
	else:
		max_chars = _MAX_CONTEXT_CHARS_FULL_YEAR if scope == "full_year" else _MAX_CONTEXT_CHARS
		max_nodes = _MAX_CONTEXT_NODES_FULL_YEAR if scope == "full_year" else 10
		max_attempts = (
			_MAX_EXTRACTION_ATTEMPTS_FULL_YEAR
			if scope == "full_year"
			else _MAX_EXTRACTION_ATTEMPTS
		)
		# For single-block queries, filter to the specific block chunk
		# to prevent cross-block confusion (e.g., picking Block 1's
		# Application Deadline instead of Block 2's).
		if args.block_number and scope != "full_year":
			bn = args.block_number
			target_labels = (
				f"Block/Term {bn}",
				f"Block {bn}",
			)
			targeted = [
				n for n in nodes
				if any(label in (getattr(n, "text", "") or "")[:80] for label in target_labels)
			]
			if targeted:
				nodes = targeted

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

	if semester_focus:
		blocks = _SEMESTER_BLOCKS.get(semester_focus, (0, 0))
		query_desc = (
			f"semester for {semester_focus} {args.year} "
			f"(Block {blocks[0]} and Block {blocks[1]} only)"
		)
	else:
		query_desc = args.query_type.value
		if resolved_season:
			query_desc += f" for {resolved_season} {args.year}"
		elif scope == "full_year":
			query_desc += f" for full year {args.year}"
		if args.block_number:
			query_desc += f" block {args.block_number}"
		if args.specific_deadline:
			query_desc += f", specifically the {args.specific_deadline} deadline"

	system_content = _EXTRACTION_SYSTEM
	if semester_focus:
		blocks = _SEMESTER_BLOCKS.get(semester_focus, (0, 0))
		system_content += (
			f"\nFocus on the {semester_focus.upper()} semester — "
			f"Block {blocks[0]} and Block {blocks[1]}. "
			f"The source data has SEPARATE dates for Block {blocks[0]} and Block {blocks[1]}. "
			f"Do NOT use 'Semester' column dates — use the per-block column dates instead. "
			f"Populate the 'blocks' field with exactly 2 blocks. "
			f"Each block MUST have its own 13 events with DIFFERENT dates. "
			f"Block {blocks[0]} events occur BEFORE Block {blocks[1]} events."
		)
	elif args.block_number and scope != "full_year":
		system_content += (
			f"\nIMPORTANT: Extract dates ONLY for Block {args.block_number}. "
			f"The documents may contain data for multiple blocks — "
			f"use ONLY the row/section labeled 'Block/Term {args.block_number}'. "
			f"Do NOT return dates from any other block."
		)

	user_content = f"Extract calendar data for: {query_desc}\n\nDocuments:\n{context}"
	last_error: Optional[str] = None

	logger.info(
		"Extraction context (%d chars, %d nodes)",
		len(context), len(nodes),
	)

	model = os.environ.get("MODEL", "gpt-4o-mini")
	client = _get_openai_client()

	for attempt in range(1, max_attempts + 1):
		try:
			logger.info(f"Extraction attempt {attempt}/{max_attempts} (JSON mode)")
			response = await client.chat.completions.create(
				model=model,
				temperature=0,
				response_format={"type": "json_object"},
				messages=[
					{"role": "system", "content": system_content},
					{"role": "user", "content": user_content},
				],
			)
			raw = (response.choices[0].message.content or "").strip()

			data = json.loads(raw)
			for key in {"title", "subtitle", "events", "source_url"}:
				if key in data and (data[key] is None or data[key] == "null"):
					del data[key]

			extracted = ExtractedCalendarData(**data)

			# Count events: top-level + inside blocks
			total_events = len(extracted.events)
			block_events = 0
			if extracted.blocks:
				block_events = sum(len(b.events) for b in extracted.blocks)
			if total_events == 0 and block_events == 0:
				last_error = "extraction returned 0 events"
				logger.warning(
					f"Attempt {attempt}: {last_error} — "
					f"{'retrying' if attempt < max_attempts else 'giving up'}"
				)
				continue

			logger.info(
				f"Extraction succeeded on attempt {attempt}: "
				f"{total_events} top-level events, {block_events} block events, "
				f"title={extracted.title!r}"
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


async def extract_full_year_by_semester(
	nodes: list,
	args: CalendarToolArgs,
) -> Optional[ExtractedCalendarData]:
	"""Extract full-year data via 3 parallel per-semester extractions.

	Each call focuses on one semester (2 blocks, ~26 events), which is far
	more reliable than asking one LLM call to extract all 78 events.
	Deterministic block rebuild ensures correct assignment regardless of
	LLM block grouping quality.
	"""
	from collections import defaultdict

	seasons = ("winter", "spring", "fall")
	tasks = [
		extract_structured_data(nodes, args, semester_focus=season)
		for season in seasons
	]
	results = await asyncio.gather(*tasks, return_exceptions=True)

	# Collect per-block events, keyed by block number (1-6)
	final_blocks: dict[int, list[ExtractedCalendarEvent]] = {b: [] for b in range(1, 7)}
	earliest_start: Optional[date] = None
	latest_end: Optional[date] = None

	failed_seasons: list[str] = []
	for i, result in enumerate(results):
		season = seasons[i]
		if isinstance(result, BaseException):
			logger.warning("Per-semester extraction for %s failed: %s", season, result)
			failed_seasons.append(season)
			continue
		if result is None:
			logger.warning("Per-semester extraction for %s returned None", season)
			failed_seasons.append(season)
			continue

		block_lo, block_hi = _SEMESTER_BLOCKS[season]

		# Strategy: if LLM provided well-populated blocks, use them.
		# Otherwise, collect all events and split by date midpoint.
		has_good_blocks = (
			result.blocks
			and len(result.blocks) >= 2
			and all(len(b.events) >= 5 for b in result.blocks)
		)

		if has_good_blocks:
			# Trust LLM block assignment — map by index
			lo_events = list(result.blocks[0].events)
			hi_events = list(result.blocks[1].events) if len(result.blocks) > 1 else []

			# Cross-validate: for events with the same name in both blocks,
			# the earlier date belongs to block_lo, later to block_hi.
			# The LLM sometimes puts semester-column dates (= block_hi)
			# into block_lo for Withdraw/Grades/End.
			lo_by_name = {e.name: e for e in lo_events}
			hi_by_name = {e.name: e for e in hi_events}
			swapped = 0
			for name in lo_by_name:
				if name in hi_by_name:
					lo_evt = lo_by_name[name]
					hi_evt = hi_by_name[name]
					if lo_evt.date > hi_evt.date:
						# Swap: lo_evt has the later date
						lo_idx = next(i for i, e in enumerate(lo_events) if e.name == name)
						hi_idx = next(i for i, e in enumerate(hi_events) if e.name == name)
						lo_events[lo_idx] = hi_evt
						hi_events[hi_idx] = lo_evt
						swapped += 1
			if swapped:
				logger.info(
					"Per-semester %s: cross-block swap fixed %d event(s)",
					season, swapped,
				)

			# Sanity check: verify lo_events actually belong to block_lo.
			# If the LLM returned a different semester's data, most dates
			# will fall outside the expected window.
			in_window = 0
			for evt in lo_events:
				try:
					evt_date = date.fromisoformat(evt.date)
					if _in_block_window(evt_date, block_lo, args.year):
						in_window += 1
				except ValueError:
					pass
			blocks_valid = in_window >= len(lo_events) // 2

			if blocks_valid:
				final_blocks[block_lo].extend(lo_events)
				final_blocks[block_hi].extend(hi_events)
				logger.info(
					"Per-semester %s: used LLM blocks (%d + %d events)",
					season,
					len(lo_events),
					len(hi_events),
				)
			else:
				logger.warning(
					"Per-semester %s: LLM blocks failed window check "
					"(%d/%d in-window), falling back to name-based split",
					season, in_window, len(lo_events),
				)
				has_good_blocks = False  # fall through to else
		if not has_good_blocks:
			# Collect all events from both flat and blocks, deduplicate,
			# then assign to correct block using date windows.
			semester_events: list[ExtractedCalendarEvent] = []
			if result.events:
				semester_events.extend(result.events)
			if result.blocks:
				for block in result.blocks:
					semester_events.extend(block.events)
			# Dedup within this semester
			seen: set[tuple[str, str]] = set()
			deduped: list[ExtractedCalendarEvent] = []
			for evt in semester_events:
				key = (evt.date, evt.name)
				if key not in seen:
					seen.add(key)
					deduped.append(evt)

			# Assign each event to block_lo or block_hi using date windows.
			# This correctly handles the case where the LLM returned data
			# from the wrong blocks — we just ignore events outside our window.
			for evt in deduped:
				try:
					evt_date = date.fromisoformat(evt.date)
				except ValueError:
					continue
				if _in_block_window(evt_date, block_lo, args.year):
					final_blocks[block_lo].append(evt)
				elif _in_block_window(evt_date, block_hi, args.year):
					final_blocks[block_hi].append(evt)
				# else: event from wrong semester, discard

			logger.info(
				"Per-semester %s: window-split %d deduped events → Block %d=%d, Block %d=%d",
				season, len(deduped),
				block_lo, len(final_blocks[block_lo]),
				block_hi, len(final_blocks[block_hi]),
			)

		# Track date range
		if result.block_or_semester_start:
			try:
				start = date.fromisoformat(result.block_or_semester_start)
				if earliest_start is None or start < earliest_start:
					earliest_start = start
			except ValueError:
				pass
		if result.block_or_semester_end:
			try:
				end = date.fromisoformat(result.block_or_semester_end)
				if latest_end is None or end > latest_end:
					latest_end = end
			except ValueError:
				pass

	# Fallback: if any semesters failed, run a single unfocused extraction
	if failed_seasons:
		logger.info(
			"Retrying failed semesters %s with fallback full-year extraction",
			failed_seasons,
		)
		fallback = await extract_structured_data(nodes, args)
		if fallback:
			# Distribute fallback events to blocks by date
			fallback_events: list[ExtractedCalendarEvent] = []
			if fallback.events:
				fallback_events.extend(fallback.events)
			if fallback.blocks:
				for block in fallback.blocks:
					fallback_events.extend(block.events)
			for evt in fallback_events:
				try:
					evt_date = date.fromisoformat(evt.date)
				except ValueError:
					continue
				block_num = _strict_block_from_date(evt_date, args.year)
				# Only add to blocks that belong to failed semesters
				season_for_block = _season_for_block(block_num)
				if season_for_block in failed_seasons:
					final_blocks[block_num].append(evt)
			if fallback.block_or_semester_start:
				try:
					start = date.fromisoformat(fallback.block_or_semester_start)
					if earliest_start is None or start < earliest_start:
						earliest_start = start
				except ValueError:
					pass
			if fallback.block_or_semester_end:
				try:
					end = date.fromisoformat(fallback.block_or_semester_end)
					if latest_end is None or end > latest_end:
						latest_end = end
				except ValueError:
					pass

	# Build final result
	all_flat: list[ExtractedCalendarEvent] = []
	rebuilt_blocks: list[ExtractedBlockData] = []
	for b in range(1, 7):
		evts = sorted(final_blocks[b], key=lambda e: e.date)
		rebuilt_blocks.append(ExtractedBlockData(block_label=f"Block {b}", events=evts))
		all_flat.extend(evts)

	if not all_flat:
		logger.warning("All per-semester extractions failed or returned no data")
		return None

	logger.info(
		"Full-year per-semester extraction complete: "
		"%d flat events, 6 rebuilt blocks: [%s]",
		len(all_flat),
		", ".join(f"B{b.block_label[-1]}={len(b.events)}" for b in rebuilt_blocks),
	)

	return ExtractedCalendarData(
		title=f"{args.year} Academic Calendar",
		subtitle="",
		block_or_semester_start=earliest_start.isoformat() if earliest_start else None,
		block_or_semester_end=latest_end.isoformat() if latest_end else None,
		events=all_flat,
		blocks=rebuilt_blocks,
		source_url=None,
		footnote=None,
	)


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
			block_events = []
			for evt in block_data.events:
				try:
					evt_date = date.fromisoformat(evt.date)
				except ValueError:
					continue
				# Trust LLM block assignment — no _in_block_window filter.
				# The LLM knows "Block 2 Registration Opens" is a Block 2 event
				# even if its date (Jan 28) falls in Block 1's month range.
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
			block_events.sort(key=lambda e: e["date"])
			tabs.append({"label": block_data.block_label, "active": i == 0, "events": block_events})

		# Normalize tab labels to "Block N" (strip season prefixes like "Winter Block 1")
		for tab in tabs:
			m = re.search(r"\d+", tab.get("label") or "")
			if m:
				tab["label"] = f"Block {m.group()}"

		# Post-build validation: detect LLM duplication or empty tabs
		has_overflow = any(len(t["events"]) > _MAX_EVENTS_PER_TAB for t in tabs)
		has_empty = any(len(t["events"]) == 0 for t in tabs) and any(len(t["events"]) > 0 for t in tabs)
		if has_overflow:
			logger.warning(
				"Tab overflow detected (LLM likely duplicated events) — "
				"rebuilding all tabs from flat events"
			)
			# Rebuild ALL tabs from flat events using strict date assignment
			seen_events: dict[int, list[dict]] = {b: [] for b in range(1, 7)}
			for evt in extracted.events:
				try:
					evt_date = date.fromisoformat(evt.date)
				except ValueError:
					continue
				block_num = _strict_block_from_date(evt_date, args.year)
				status = _classify_date(evt_date, today)
				countdown = _countdown_str(evt_date, today)
				section = "Past" if status == "past" else "Today" if status == "today" else "Coming Up"
				seen_events[block_num].append({
					"date": evt.date,
					"name": evt.name,
					"status": status,
					"countdown": countdown,
					"description": evt.description or "",
					"section": section,
				})
			tabs = []
			for b in range(1, 7):
				evts = sorted(seen_events[b], key=lambda e: e["date"])
				tabs.append({"label": f"Block {b}", "active": b == 1, "events": evts})
		elif has_empty:
			# Fill only the empty tabs from flat events
			for tab in tabs:
				if len(tab["events"]) > 0:
					continue
				m = re.search(r"\d+", tab.get("label") or "")
				block_num = int(m.group()) if m else None
				if block_num:
					tab["events"] = _build_block_events_from_flat(
						extracted.events, block_num, args.year, today,
					)

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
		for tab in (tabs or []):
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
