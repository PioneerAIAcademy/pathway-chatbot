"""
Pre-flight tool router: asks the LLM whether the user's message
is a calendar question, using function calling with tool_choice=auto.

This runs as a single lightweight LLM call before the main RAG pipeline.
If the LLM invokes the calendar tool, the calendar pipeline runs concurrently
with the main chat response. If not, only the normal RAG response streams.
"""

import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.settings import Settings
from zoneinfo import ZoneInfo

from app.tools.calendar.schema import CalendarToolArgs
from app.tools.calendar.tool import get_calendar_tool_definition
from app.tools.calendar.vocabulary import normalize_deadline_term

logger = logging.getLogger("uvicorn")

_MAX_HISTORY_MESSAGES = 4

# Retry detection: the frontend sends this canned message on "Try again".
_CALENDAR_RETRY_PATTERN = re.compile(
	r"\b(?:please\s+)?retry\s+(?:the\s+)?(?:academic\s+)?calendar\b",
	re.IGNORECASE,
)


def _is_calendar_retry(message: str) -> bool:
	"""Return True when the message is a frontend-initiated calendar retry."""
	return bool(_CALENDAR_RETRY_PATTERN.search(message))


def _find_original_calendar_question(
	retry_message: str,
	chat_history: Optional[List[ChatMessage]],
) -> Optional[str]:
	"""Walk history backwards and return the first real user question (skip retry messages)."""
	if not chat_history:
		return None
	for msg in reversed(chat_history[-_MAX_HISTORY_MESSAGES * 2:]):
		content = getattr(msg, "content", "") or ""
		role = str(getattr(msg, "role", ""))
		if (
			"user" in role.lower()
			and not _CALENDAR_RETRY_PATTERN.search(content)
			and content.strip()
		):
			return content.strip()
	return None


def _season_block_for_month(month: int) -> tuple[str, int]:
	"""Map month to BYU-Pathway season and current block."""
	if month <= 2:
		return "winter", 1
	if month <= 4:
		return "winter", 2
	if month <= 6:
		return "spring", 3
	if month <= 8:
		return "spring", 4
	if month <= 10:
		return "fall", 5
	return "fall", 6


_CALENDAR_INTRO_PATTERN = re.compile(
	r"^Here(?:'s| are) the\s+(?:key\s+)?(?:dates?|deadlines?|registration|application|"
	r"payment|drop|withdraw|tuition|grades?|refund|"
	r"graduation|full|academic|calendar|block|semester|winter|spring|fall)",
	re.IGNORECASE,
)

_BROAD_CALENDAR_FOLLOWUP_PATTERN = re.compile(
	r"\b(?:show|display|pull up)\b.*\b(?:all\s+)?(?:key\s+)?(?:dates?|deadlines?|calendar)\b"
	r"|\b(?:all\s+)?(?:key\s+)?(?:dates?|deadlines?)\b",
	re.IGNORECASE,
)

_FULL_YEAR_REQUEST_PATTERN = re.compile(
	r"\b(?:full|whole|entire)\s+year\b|\ball\s+blocks\b",
	re.IGNORECASE,
)

_ANY_TERM_NUMBER_PATTERN = re.compile(
	r"\b(?:block|blok|blck|term|semester|b)\s*(\d{1,2})\b",
	re.IGNORECASE,
)

_GENERAL_OVERVIEW_PATTERN = re.compile(
	r"\b(?:academic\s+calendar|important\s+dates|key\s+dates|start\s+dates|"
	r"show\s+me\s+an?\s+academic\s+calendar|show\s+the\s+academic\s+calendar)\b",
	re.IGNORECASE,
)

_POLICY_ONLY_PATTERN = re.compile(
	r"\b(?:what\s+does|difference\s+between|what\s+happens|consequences?|"
	r"exceptions?|appeal|how\s+to|how\s+do|how\s+can|how\s+long|"
	r"help\s+me\s+find|find\s+information|provide\s+a\s+link|give\s+me\s+a\s+link|"
	r"where\s+can|where\s+is|what\s+should\s+(?:a\s+student|students)\s+do)\b",
	re.IGNORECASE,
)


def _has_recent_calendar_response(
	chat_history: Optional[List[ChatMessage]],
) -> Optional[str]:
	"""Return the calendar intro text if a recent assistant message looks like one, else None."""
	if not chat_history:
		return None
	for msg in chat_history[-_MAX_HISTORY_MESSAGES:]:
		role = str(getattr(msg, "role", ""))
		content = (getattr(msg, "content", "") or "").strip()
		if "assistant" in role.lower() and _CALENDAR_INTRO_PATTERN.search(content):
			return content
	return None


_DEADLINE_KEYWORDS = {
	"registration": "registration",
	"application": "application",
	"payment": "payment",
	"tuition": "payment",
	"drop": "drop",
	"withdraw": "withdraw",
	"grades": "grades",
	"refund": "refund",
	"late fee": "late_fees",
}


def _prior_card_matches_new_args(prior_intro: str, args_dict: dict) -> bool:
	"""Return True if the new tool call would produce the same card already shown."""
	intro_lower = prior_intro.lower()

	block_match = re.search(r"block\s*(\d)", intro_lower)
	prior_block = int(block_match.group(1)) if block_match else None

	prior_deadline = None
	for keyword, canonical in _DEADLINE_KEYWORDS.items():
		if keyword in intro_lower:
			prior_deadline = canonical
			break

	scope_match = re.search(r"\bfull.year\b", intro_lower)
	prior_full_year = bool(scope_match)

	new_block = args_dict.get("block_number")
	new_deadline = args_dict.get("specific_deadline")
	new_full_year = (args_dict.get("scope") or "").lower() == "full_year"

	# Full-year repeat
	if prior_full_year and new_full_year:
		return True

	# Same block: check deadline type too
	if prior_block and new_block and prior_block == new_block:
		if new_deadline and prior_deadline:
			return new_deadline == prior_deadline
		# Both are general block views (no specific deadline)
		if not new_deadline and not prior_deadline:
			return True

	return False


_ROUTER_SYSTEM_PROMPT_TEMPLATE = (
	"You are a routing assistant for a BYU-Pathway missionary support chatbot. "
	"The users are SERVICE MISSIONARIES who advise students — not students "
	"themselves. When a missionary asks about a deadline or policy, they often "
	"need the policy context (consequences, what to tell students, processes) "
	"more than just a calendar date.\n\n"
	"Given the user's message (and conversation history if provided), decide "
	"if they are asking about the BYU-Pathway academic calendar.\n\n"
	"{current_context}\n\n"
	"{prior_card_context}"
	"ROUTING RULES:\n"
	"1. CALL lookup_academic_calendar when the user asks for a SPECIFIC date "
	"or schedule — meaning they mention a particular block, term, semester, "
	"season, or year, OR they ask 'when is X for block N / this term / next term'. "
	"Examples: 'When is the payment deadline for block 5', 'Show me the Fall 2026 "
	"calendar', 'What are the deadlines for next term', 'When does registration open "
	"for Spring'. Also call when they ask about registration status "
	"('is registration open', 'can I still register').\n"
	"   REGISTRATION STATUS: If the user asks 'is registration open', "
	"'can I still register', 'has registration closed', or any question about "
	"whether registration is currently available, ALWAYS call the tool with "
	"specific_deadline='registration'. The tool will retrieve the actual "
	"Registration Opens and Add Course Deadline dates so the system can "
	"determine if registration is open or closed.\n"
	"2. DO NOT call the tool for:\n"
	"   - GENERAL / POLICY questions with no specific block, term, or year "
	"('When is the deadline to make payment', 'What happens if a student "
	"doesn't pay on time', 'What is the drop policy'). These need policy "
	"context (consequences, late fees, registration holds) that only the "
	"knowledge base provides — let them go to RAG.\n"
	"   - Simple date/time questions ('What is today?', 'What is today's date?', 'What day is it?', 'What time is it?')\n"
	"   - How-to/process questions ('How do I register?', 'What steps to prepare?')\n"
	"   - General knowledge questions unrelated to the academic calendar\n"
	"   - Requests for 'text format' or 'list the dates' (they want plain text)\n"
	"3. MIXED-INTENT: If the message combines a calendar request with a non-calendar "
	"question (e.g. 'Show me the 2026 calendar and what is BYU-Pathway'), "
	"ALWAYS call the tool for the calendar part. The non-calendar part will be "
	"handled separately — your only job is to detect and route the calendar intent.\n"
	"4. If AMBIGUOUS with NO clear calendar intent, ask a brief clarification "
	"question — do NOT call the tool. Clarification questions must avoid "
	"second-person pronouns; use neutral phrasing such as 'Which year should "
	"be checked for Term 2?' or 'Should the answer use this term or the next term?'\n"
	"5. If clearly NOT calendar, return an empty message — do NOT call the tool.\n\n"
	"KEY DISTINCTION: 'When is the payment deadline FOR BLOCK 5' → specific → "
	"CALL tool. 'When is the deadline to make payment' → general policy → "
	"DO NOT call tool (RAG will provide policy details like late fees, holds, "
	"consequences).\n\n"
	"TERMINOLOGY: BYU-Pathway uses 'block' (6 per year). Students may say "
	"'term', 'block', or 'semester' interchangeably — treat all as synonyms.\n\n"
	"ARGUMENT RULES:\n"
	"- Use ONLY valid arg keys: query_type, year, season, block_number, "
	"specific_deadline, scope.\n"
	"- When the user asks for multiple deadlines or a general overview "
	"('all deadlines', 'all key deadlines', 'show all dates', 'important dates', "
	"'upcoming deadlines'), do NOT set specific_deadline — leave it empty "
	"so ALL deadlines are returned.\n"
	"- Only set specific_deadline when the user asks about ONE specific type. "
	"Canonical keys and example phrasings:\n"
	"  financial_hold — 'When are holds applied?'\n"
	"  registration — 'When does registration open?'\n"
	"  priority_registration — 'priority registration deadline'\n"
	"  application — 'application deadline'\n"
	"  add_course — 'When can I add a course?'\n"
	"  drop — 'drop deadline', 'auto-drop', 'autodrop', 'When will I be auto-dropped?'\n"
	"  refund — 'last day for a refund', 'refund deadline'\n"
	"  payment — 'When is tuition due?', 'payment deadline'\n"
	"  late_fees — 'When are late fees applied?'\n"
	"  withdraw — 'last day to withdraw', 'withdraw with a W'\n"
	"  tuition_discount — 'tuition discount deadline'\n"
	"  grades — 'When are grades available?'\n"
	"- When the user says 'this year', 'whole year', 'full year', 'all terms', "
	"or 'all blocks', set scope='full_year'.\n"
	"- For follow-up messages like 'show me the card', use conversation history "
	"to determine what calendar data they mean.\n"
	"- If the user names a block/term/semester but omits the year, assume the "
	"CURRENT academic year unless conversation history clearly points to a different year.\n"
	"- If the user asks broadly for the academic calendar or important dates with no "
	"specific year, default to the CURRENT academic year and use scope='full_year'.\n"
	"- CONVERSATIONAL SCOPING: If the user says something broad like "
	"'show me all key deadlines' or 'show me all dates', check conversation "
	"history. If the conversation was about a specific block/semester (e.g. "
	"Block 2 or Winter 2026), scope the request to that context — "
	"set the block_number/season/year from the conversation subject. "
	"Only use full_year scope if the user EXPLICITLY asks for 'full year', "
	"'all blocks', 'whole year', or there is no conversation context to infer from.\n"
	"- USER EMPHASIS: When the user writes words in ALL CAPS (e.g. 'FALL', "
	"'BLOCK 3', 'WINTER'), treat that as strong emphasis — they are stressing "
	"exactly what they want. Prioritize those terms in your argument selection.\n"
	"- When the CURRENT message differs from history (e.g. history said Block 2, "
	"now user says 'What about block 3'), use the CURRENT message values.\n"
	"- For deadlines, use canonical keys: financial_hold, registration, "
	"priority_registration, application, add_course, drop, refund, payment, "
	"late_fees, withdraw, grades, tuition_discount.\n\n"
	"The user may write in ANY language. Always map meaning to canonical args."
)


def _current_block_context(user_timezone: str) -> str:
	"""Build a context string with the current date and academic block info."""
	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()

	season, block = _season_block_for_month(today.month)

	# Compute the next block/season so the LLM doesn't have to guess
	next_block = block + 1 if block < 6 else 1
	next_year = today.year if block < 6 else today.year + 1
	next_season_map = {1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "fall", 6: "fall"}
	next_season = next_season_map[next_block]

	return (
		f"CURRENT DATE CONTEXT: Today is {today.isoformat()} "
		f"({today.strftime('%A, %B %d, %Y')}). "
		f"The current academic block is {season.capitalize()} {today.year}, "
		f"Block {block}. BYU-Pathway has exactly 3 semesters per year (NO 'Summer'): "
		f"Winter (Blocks 1-2, Jan-Apr), Spring (Blocks 3-4, May-Aug), "
		f"Fall (Blocks 5-6, Sep-Dec). "
		f"Season order: Winter → Spring → Fall → Winter (next year). "
		f"When the user says 'this term/block/semester', they mean "
		f"{season.capitalize()} {today.year} Block {block} "
		f"(season='{season}', block_number={block}, year={today.year}). "
		f"When they say 'next term/block/semester' or 'next registration/deadline', "
		f"they mean {next_season.capitalize()} {next_year} Block {next_block} "
		f"(season='{next_season}', block_number={next_block}, year={next_year}). "
		f"NEVER skip a season — 'next' after Winter is SPRING, not Fall.\n\n"
		f"REGISTRATION LIFECYCLE: Each block has a registration WINDOW. "
		f"Registration OPENS several weeks before the block starts "
		f"(labeled 'Registration Opens' or 'Priority Registration Deadline'). "
		f"Registration CLOSES on the Add Course Deadline, which is Day 1 of the block. "
		f"After the Add Course Deadline, registration is CLOSED — students can NO "
		f"LONGER register. Always route registration questions to the calendar tool "
		f"so the actual dates can be checked."
	)


def _extract_block_context(text: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
	"""Extract season, year, and block number from text.

	Recognises 'block', 'term', and 'semester' + digit as synonyms so
	that students who interchange the words are handled correctly.
	"""
	lowered = (text or "").lower()
	season_match = re.search(r"\b(winter|spring|fall|summer)\b", lowered)
	year_match = re.search(r"\b(20\d{2})\b", lowered)
	block_match = re.search(r"\b(?:block|blok|blck|term|semester|b)\s*([1-6])\b", lowered)

	season = season_match.group(1) if season_match else None
	year = int(year_match.group(1)) if year_match else None
	block = int(block_match.group(1)) if block_match else None
	return season, year, block


def _extract_year(text: str) -> Optional[int]:
	match = re.search(r"\b(20\d{2})\b", (text or "").lower())
	return int(match.group(1)) if match else None


def _is_general_overview_request(text: str) -> bool:
	return bool(_GENERAL_OVERVIEW_PATTERN.search(text or ""))


def _is_policy_only_question(text: str) -> bool:
	return bool(_POLICY_ONLY_PATTERN.search(text or ""))


def _extract_any_term_number(text: str) -> Optional[int]:
	match = _ANY_TERM_NUMBER_PATTERN.search(text or "")
	if not match:
		return None
	try:
		return int(match.group(1))
	except Exception:
		return None


def _invalid_term_number_response(term_number: int) -> str:
	return (
		f"The current academic calendar lists only Blocks 1 through 6 each year: "
		f"Winter (Blocks 1-2), Spring (Blocks 3-4), and Fall (Blocks 5-6). "
		f"There is no Term {term_number} in the source calendar. "
		"If helpful, I can pull up a valid block or the full academic calendar."
	)


def _parse_prior_calendar_context(prior_intro: str) -> dict[str, Optional[int | str]]:
	"""Extract scope cues from the intro line of the previously shown calendar card."""
	intro = ((prior_intro or "").splitlines() or [""])[0].strip()
	lowered = intro.lower()
	season, year, block = _extract_block_context(intro)
	full_year = bool(
		re.search(r"\bfull\s+\d{4}\s+academic\s+calendar\b", lowered)
		or (
			"academic calendar" in lowered
			and "block" not in lowered
			and not season
		)
	)

	if full_year:
		return {
			"query_type": "semester",
			"scope": "full_year",
			"season": None,
			"year": year,
			"block_number": None,
		}

	if block is not None:
		return {
			"query_type": "block",
			"scope": "term",
			"season": season,
			"year": year,
			"block_number": block,
		}

	if season or year:
		return {
			"query_type": "semester",
			"scope": "term",
			"season": season,
			"year": year,
			"block_number": None,
		}

	return {
		"query_type": None,
		"scope": None,
		"season": None,
		"year": None,
		"block_number": None,
	}


def _normalize_clarification_text(text: str) -> str:
	clean = (text or "").strip()
	if not clean:
		return clean

	replacements: list[tuple[str, str]] = [
		(
			r"^Could you please clarify if you are asking about (.+)\?$",
			r"Which option should be checked: \1?",
		),
		(
			r"^Could you please clarify which (.+?) you are referring to(?: for .+)?\?$",
			r"Which \1 should be checked?",
		),
		(
			r"^Could you please specify which (.+?) you are referring to(?: for .+)?\?$",
			r"Which \1 should be checked?",
		),
		(
			r"^Could you please specify if you are asking about (.+)\?$",
			r"Which option should be checked: \1?",
		),
		(
			r"^I can help with that!\s*Could you please specify if you'?re asking about (.+)\?$",
			r"Which option should be checked: \1?",
		),
	]

	for pattern, replacement in replacements:
		if re.match(pattern, clean, re.IGNORECASE):
			return re.sub(pattern, replacement, clean, flags=re.IGNORECASE)

	return clean


def _default_year_for_message(user_timezone: str) -> int:
	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()
	return today.year


def _build_default_overview_args(
	message: str,
	user_timezone: str,
) -> Optional[CalendarToolArgs]:
	explicit_season, explicit_year, explicit_block = _extract_block_context(message)
	if explicit_year or explicit_season or explicit_block:
		return None
	if not _is_general_overview_request(message):
		return None

	return CalendarToolArgs(
		query_type="semester",
		year=_default_year_for_message(user_timezone),
		scope="full_year",
		timezone=user_timezone,
	)


def _apply_missing_year_default(
	args_dict: dict,
	message: str,
	user_timezone: str,
) -> None:
	if args_dict.get("year"):
		return
	explicit_season, explicit_year, explicit_block = _extract_block_context(message)
	if explicit_year:
		return
	if explicit_block or explicit_season:
		args_dict["year"] = _default_year_for_message(user_timezone)


def _apply_conversational_scope(
	args_dict: dict,
	message: str,
	prior_card_intro: Optional[str],
) -> None:
	"""Scope broad follow-up requests to the subject of the previously shown card."""
	if not prior_card_intro:
		return
	if not _BROAD_CALENDAR_FOLLOWUP_PATTERN.search(message or ""):
		return
	if _FULL_YEAR_REQUEST_PATTERN.search(message or ""):
		return

	explicit_season, explicit_year, explicit_block = _extract_block_context(message)
	if explicit_season or explicit_year or explicit_block:
		return

	scope = (args_dict.get("scope") or "term").lower()
	if scope == "full_year":
		return

	prior = _parse_prior_calendar_context(prior_card_intro)
	if not prior.get("query_type"):
		return

	args_dict["query_type"] = prior["query_type"]
	args_dict["scope"] = prior["scope"]
	args_dict["year"] = prior["year"]
	args_dict["season"] = prior["season"]

	if prior["block_number"] is None:
		args_dict.pop("block_number", None)
	else:
		args_dict["block_number"] = prior["block_number"]

	args_dict.pop("specific_deadline", None)

	logger.info(
		"Conversational scope applied from prior card: query_type=%s scope=%s season=%s year=%s block=%s",
		args_dict.get("query_type"),
		args_dict.get("scope"),
		args_dict.get("season"),
		args_dict.get("year"),
		args_dict.get("block_number"),
	)


def _relative_month_context(user_timezone: str, month_offset: int) -> tuple[int, str, int]:
	"""Return (year, season, block) for a relative month offset."""
	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()

	total_month_index = (today.year * 12 + (today.month - 1)) + month_offset
	target_year = total_month_index // 12
	target_month = (total_month_index % 12) + 1
	season, block = _season_block_for_month(target_month)
	return target_year, season, block


def _apply_relative_time_overrides(
	args_dict: dict,
	message: str,
	user_timezone: str,
) -> None:
	"""Apply deterministic relative-time overrides (e.g., 'next month')."""
	lowered = (message or "").lower()
	explicit_season, explicit_year, explicit_block = _extract_block_context(message)

	# Respect explicit user values when present.
	if explicit_season or explicit_year or explicit_block:
		return

	if "next month" in lowered:
		target_year, target_season, target_block = _relative_month_context(
			user_timezone,
			1,
		)
		args_dict["year"] = target_year
		args_dict["season"] = target_season
		# Keep block-level precision for month-relative asks.
		args_dict["block_number"] = target_block


def _apply_next_block_default(
	args_dict: dict,
	message: str,
	user_timezone: str,
) -> None:
	"""When the user didn't mention a specific season/block/year, ensure we
	default to the NEXT block — i.e. the nearest future block whose
	registration hasn't opened yet, or the current block if in progress.

	This prevents the LLM from jumping to a far-future season (e.g. Fall)
	when the user just asks 'when is registration'.
	"""
	explicit_season, explicit_year, explicit_block = _extract_block_context(message)
	# If the user explicitly said a season, year, or block, respect it.
	if explicit_season or explicit_year or explicit_block:
		return
	# If the args were already resolved deterministically (e.g. conversational
	# scoping or relative-time override), do not clobber them with "next block".
	if args_dict.get("season") or args_dict.get("year") or args_dict.get("block_number"):
		return
	# If scope is full_year, don't override — they want everything.
	scope = (args_dict.get("scope") or "term").lower()
	if scope == "full_year":
		return

	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()

	_, cur_block = _season_block_for_month(today.month)
	next_block = cur_block + 1 if cur_block < 6 else 1
	next_year = today.year if cur_block < 6 else today.year + 1
	next_season_map = {1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "fall", 6: "fall"}
	next_season = next_season_map[next_block]

	# Override season/block/year to the next block
	args_dict["season"] = next_season
	args_dict["block_number"] = next_block
	args_dict["year"] = next_year
	logger.info(
		"Next-block default applied: season=%s, block=%d, year=%d",
		next_season, next_block, next_year,
	)


async def detect_calendar_intent_via_llm(
	message: str,
	user_timezone: str = "UTC",
	chat_history: Optional[List[ChatMessage]] = None,
) -> tuple[Optional[CalendarToolArgs], Optional[str]]:
	"""
	Ask the LLM if this message is a calendar question.

	Returns:
		(args, clarification_text):
		- args is set if the LLM called the calendar tool
		- clarification_text is set if the LLM wants to ask a follow-up
		- both None if the message is clearly not calendar-related
	"""
	# Retry detection: frontend sends a canned retry message.
	# Find the original question from history and re-route against that.
	if _is_calendar_retry(message) and chat_history:
		original = _find_original_calendar_question(message, chat_history)
		if original:
			logger.info(
				"Calendar router: retry detected, re-routing original question: %s",
				original[:80],
			)
			return await detect_calendar_intent_via_llm(
				original, user_timezone, chat_history,
			)
		logger.info("Calendar router: retry detected but no original question found in history")

	invalid_term_number = _extract_any_term_number(message)
	if invalid_term_number is not None and invalid_term_number > 6:
		logger.info(
			"Calendar router: invalid term/block requested (%s) — returning plain-text clarification",
			invalid_term_number,
		)
		return None, _invalid_term_number_response(invalid_term_number)

	default_overview_args = _build_default_overview_args(message, user_timezone)
	if default_overview_args is not None:
		logger.info(
			"Calendar router: defaulting broad overview request to full current-year calendar"
		)
		return default_overview_args, None

	tool_def = get_calendar_tool_definition()

	current_ctx = _current_block_context(user_timezone)

	prior_card_ctx = ""
	prior_card_intro = _has_recent_calendar_response(chat_history)
	if prior_card_intro:
		intro_summary = prior_card_intro.split("\n")[0][:200]
		prior_card_ctx = (
			"IMPORTANT: A calendar card was ALREADY shown in this conversation. "
			f"The card showed: \"{intro_summary}\"\n"
			"CALL the tool if the user asks for DIFFERENT calendar data:\n"
			"  - A different block/term (e.g. card showed Block 2, user asks Block 3)\n"
			"  - A different deadline type (e.g. card showed registration, user asks drop)\n"
			"  - A different scope (e.g. card showed one block, user asks full year)\n"
			"  - A different season or year\n"
			"DO NOT call the tool for:\n"
			"  - Follow-up questions about what was already shown "
			"('So it has passed?', 'What does this mean?', 'Can I still register?')\n"
			"  - Reactions or acknowledgements ('ok thanks', 'got it')\n"
			"  - Questions about the same data already displayed\n"
			"When in doubt about whether it's the SAME or DIFFERENT data, "
			"call the tool — it's better to show a new card than to miss a request.\n\n"
		)

	prompt = _ROUTER_SYSTEM_PROMPT_TEMPLATE.format(
		current_context=current_ctx,
		prior_card_context=prior_card_ctx,
	)
	system_msg = ChatMessage(role=MessageRole.SYSTEM, content=prompt)

	history_msgs: list[ChatMessage] = []
	if chat_history:
		for msg in chat_history[-_MAX_HISTORY_MESSAGES:]:
			history_msgs.append(msg)

	user_msg = ChatMessage(role=MessageRole.USER, content=message)

	try:
		response = await Settings.llm.achat(
			messages=[system_msg, *history_msgs, user_msg],
			tools=[tool_def],
			tool_choice="auto",
		)
	except Exception as e:
		logger.error(f"Calendar router LLM call failed: {e}")
		return None, None

	ai_message = response.message
	tool_calls = getattr(ai_message, "additional_kwargs", {}).get("tool_calls", [])

	if tool_calls:
		tc = tool_calls[0]
		try:
			fn = getattr(tc, "function", None) or tc.get("function", {})
			args_str = getattr(fn, "arguments", None) or fn.get("arguments", "{}")
			args_dict = json.loads(args_str)

			# Normalize LLM output quirks
			if args_dict.get("query_type") == "full_year":
				args_dict["query_type"] = "semester"
				args_dict["scope"] = "full_year"

			# If the LLM returned a deadline name as the query_type, fix it
			raw_qt = args_dict.get("query_type", "")
			valid_types = {"block", "semester", "deadline", "graduation"}
			if raw_qt and raw_qt not in valid_types:
				canonical_qt = normalize_deadline_term(raw_qt)
				if canonical_qt:
					args_dict["query_type"] = "deadline"
					args_dict.setdefault("specific_deadline", canonical_qt)

			# Normalize the deadline term if the LLM used a fuzzy alias
			llm_deadline = args_dict.get("specific_deadline")
			if llm_deadline:
				canonical = normalize_deadline_term(llm_deadline)
				if canonical:
					args_dict["specific_deadline"] = canonical

			# Deterministic override: resolve relative time expressions
			_apply_relative_time_overrides(args_dict, message, user_timezone)

			# Deterministic override: broad follow-ups inherit the subject of the
			# prior card before any next-block default is applied.
			_apply_conversational_scope(args_dict, message, prior_card_intro)

			# Deterministic override: if the user named a block/season but omitted
			# the year, default to the current academic year.
			_apply_missing_year_default(args_dict, message, user_timezone)

			# Deterministic override: if the user didn't specify a season/block
			# explicitly, force the NEXT block so the nearest future dates appear.
			_apply_next_block_default(args_dict, message, user_timezone)

			# Deterministic override: if the user explicitly named a season
			# (e.g., "Winter 2025") but the LLM returned scope=full_year,
			# force scope=term so it routes to semester extraction (2-block card).
			# Only keep full_year if the user actually asked for "full year" /
			# "all blocks".
			explicit_season, explicit_year, explicit_block = _extract_block_context(message)
			if (
				explicit_season
				and (args_dict.get("scope") or "term").lower() == "full_year"
				and not _FULL_YEAR_REQUEST_PATTERN.search(message or "")
			):
				logger.info(
					"Calendar router: user named season '%s' but LLM returned "
					"scope=full_year — forcing scope=term for semester extraction",
					explicit_season,
				)
				args_dict["scope"] = "term"
				args_dict.setdefault("season", explicit_season)
				args_dict["query_type"] = "semester"

			# Re-extract for the policy check below (already computed above).
			if (
				_is_policy_only_question(message)
				and not explicit_season
				and not explicit_year
				and not explicit_block
				and not _FULL_YEAR_REQUEST_PATTERN.search(message or "")
			):
				logger.info(
					"Calendar router: policy/explanation question without explicit scope — deferring to RAG"
				)
				return None, None

			# Follow-up suppression: if a calendar card was already shown
			# and the new args match it, skip the calendar pipeline so RAG
			# can answer the follow-up conversationally.
			if prior_card_intro and _prior_card_matches_new_args(
				prior_card_intro, args_dict
			):
				logger.info(
					"Calendar router: suppressing duplicate card — "
					"same data already shown, deferring to RAG"
				)
				return None, None

			args_dict.setdefault("timezone", user_timezone)
			args_dict.setdefault("scope", "term")
			return CalendarToolArgs(**args_dict), None
		except Exception as e:
			logger.error(f"Failed to parse calendar tool args: {e}")
			return None, None

	# LLM did not call the tool: either not calendar or wants clarification
	text_response = getattr(ai_message, "content", "") or ""
	if text_response.strip():
		normalized = _normalize_clarification_text(text_response.strip())
		logger.info(f"Calendar router clarification: {normalized[:100]}")
		return None, normalized

	return None, None
