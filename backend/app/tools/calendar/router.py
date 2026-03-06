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
from app.tools.calendar.vocabulary import normalize_deadline_term, normalize_query_scope

logger = logging.getLogger("uvicorn")

# Max history messages to include for follow-up context
_MAX_HISTORY_MESSAGES = 4
_CALENDAR_CONTEXT_HINTS = re.compile(
	r"\b(academic|calendar|block|term|semester|registration|refund|withdraw|"
	r"tuition|deadline|grades|hold|graduation|commencement|pathway|byu)\b",
	re.IGNORECASE,
)


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


_ROUTER_SYSTEM_PROMPT_TEMPLATE = (
	"You are a routing assistant for a BYU-Pathway student support chatbot. "
	"Given the user's message (and conversation history if provided), decide "
	"if they are asking about the BYU-Pathway academic calendar (dates, "
	"deadlines, blocks, semesters, registration, graduation, commencement, "
	"drop/add dates, payment deadlines, etc).\n\n"
	"WARNING: STRICT ROUTING CONTRACT — VIOLATIONS ARE NOT ACCEPTABLE.\n"
	"MANDATORY RULES:\n"
	"1) IF CALENDAR INTENT IS CLEAR, CALL lookup_academic_calendar.\n"
	"2) WHEN CALLING THE TOOL, USE ONLY VALID ARG KEYS: "
	"query_type, year, season, block_number, specific_deadline, scope.\n"
	"3) DO NOT INVENT KEYS OR VALUES. USE CANONICAL VALUES ONLY.\n"
	"4) IF AMBIGUOUS, ASK A BRIEF CLARIFICATION QUESTION (NO TOOL CALL).\n"
	"5) IF CLEARLY NOT CALENDAR, RETURN EMPTY MESSAGE (NO TOOL CALL).\n\n"
	"{current_context}\n\n"
	"If YES and you are confident, call the lookup_academic_calendar function "
	"with appropriate arguments. For follow-up messages like 'show me in card "
	"view' or 'show me the card', use the conversation history to determine "
	"what calendar data they are referring to and call the function.\n\n"
	"CRITICAL: When the user's CURRENT message mentions a specific block "
	"number, season, or year that DIFFERS from the conversation history, "
	"ALWAYS use the value from the CURRENT message. For example, if the "
	"history discussed Block 2 but the user now says 'What about block 3', "
	"use block_number=3, NOT block_number=2.\n\n"
	"When the user says 'this term', 'this block', 'current block', or "
	"'current semester', use the current date context above to determine the "
	"correct block number and season. Always resolve ambiguous time references "
	"to the current or nearest upcoming block/semester.\n\n"
	"The user may write in ANY language. Always map meaning to canonical args "
	"(query_type, year, season, block_number, specific_deadline, scope). "
	"For deadlines, use canonical keys: financial_hold, registration, "
	"priority_registration, application, add_course, drop, refund, payment, "
	"late_fees, withdraw, grades, tuition_discount.\n\n"
	"When the user asks for 'this year', 'whole year', 'full year', 'all terms', "
	"or 'all blocks', set scope='full_year' and avoid narrowing to a single "
	"season/block unless the user explicitly asks for one.\n\n"
	"IMPORTANT: If the user asks for dates 'in text format' or says 'list the "
	"dates', do NOT call the function — they want a plain text response, not "
	"the calendar card.\n\n"
	"If the question is AMBIGUOUS (could be calendar or something else), respond "
	"with a brief clarification question like 'Are you asking about the academic "
	"calendar?' Do NOT call the function in this case.\n\n"
	"If the question is clearly NOT about the academic calendar, respond with an "
	"empty message. Do NOT call the function."
)


def _current_term_context(user_timezone: str) -> str:
	"""Build a context string with current date and academic term info."""
	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()

	season, block = _season_block_for_month(today.month)

	return (
		f"CURRENT DATE CONTEXT: Today is {today.isoformat()} "
		f"({today.strftime('%A, %B %d, %Y')}). "
		f"The current academic term is {season.capitalize()} {today.year}, "
		f"Block {block}. When the user says 'this term', 'this block', "
		f"'current block', or 'current semester', they mean "
		f"{season.capitalize()} {today.year} Block {block} "
		f"(season='{season}', block_number={block}, year={today.year})."
	)


def _extract_term_context(text: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
	lowered = (text or "").lower()
	season_match = re.search(r"\b(winter|spring|fall|summer)\b", lowered)
	year_match = re.search(r"\b(20\d{2})\b", lowered)
	block_match = re.search(r"\b(?:block|term)\s*([1-6])\b", lowered)

	season = season_match.group(1) if season_match else None
	year = int(year_match.group(1)) if year_match else None
	block = int(block_match.group(1)) if block_match else None
	return season, year, block


def _extract_year(text: str) -> Optional[int]:
	match = re.search(r"\b(20\d{2})\b", (text or "").lower())
	return int(match.group(1)) if match else None


def _infer_deadline_from_history(chat_history: Optional[List[ChatMessage]]) -> Optional[str]:
	if not chat_history:
		return None
	for msg in reversed(chat_history[-_MAX_HISTORY_MESSAGES:]):
		content = getattr(msg, "content", "") or ""
		deadline = normalize_deadline_term(content)
		if deadline:
			return deadline
	return None


def _infer_year_from_history(
	chat_history: Optional[List[ChatMessage]],
	default_year: int,
) -> int:
	if not chat_history:
		return default_year
	for msg in reversed(chat_history[-_MAX_HISTORY_MESSAGES:]):
		content = getattr(msg, "content", "") or ""
		year = _extract_year(content)
		if year:
			return year
	return default_year


def _history_has_calendar_context(chat_history: Optional[List[ChatMessage]]) -> bool:
	if not chat_history:
		return False
	for msg in reversed(chat_history[-_MAX_HISTORY_MESSAGES:]):
		if _CALENDAR_CONTEXT_HINTS.search(getattr(msg, "content", "") or ""):
			return True
	return False


def _build_deadline_args_from_context(
	message: str,
	user_timezone: str,
	chat_history: Optional[List[ChatMessage]],
	specific_deadline: str,
	scope: str = "term",
) -> CalendarToolArgs:
	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()

	season, block = _season_block_for_month(today.month)
	year = today.year

	if scope == "full_year":
		year = _extract_year(message) or _infer_year_from_history(chat_history, today.year)
		return CalendarToolArgs(
			query_type="deadline",
			season=None,
			year=year,
			block_number=None,
			specific_deadline=specific_deadline,
			scope="full_year",
			timezone=user_timezone,
		)

	candidates = [message]
	if chat_history:
		for msg in reversed(chat_history[-_MAX_HISTORY_MESSAGES:]):
			candidates.append(getattr(msg, "content", "") or "")

	for text in candidates:
		s_text, y_text, b_text = _extract_term_context(text)
		if s_text:
			season = "spring" if s_text == "summer" else s_text
		if y_text:
			year = y_text
		if b_text:
			block = b_text
		if s_text or y_text or b_text:
			break

	return CalendarToolArgs(
		query_type="deadline",
		season=season,
		year=year,
		block_number=block,
		specific_deadline=specific_deadline,
		scope="term",
		timezone=user_timezone,
	)


def _build_year_scope_args_from_context(
	message: str,
	user_timezone: str,
	chat_history: Optional[List[ChatMessage]],
	explicit_deadline: Optional[str],
) -> CalendarToolArgs:
	try:
		today = datetime.now(ZoneInfo(user_timezone)).date()
	except Exception:
		today = datetime.now(ZoneInfo("UTC")).date()

	year = _extract_year(message) or _infer_year_from_history(chat_history, today.year)
	deadline = explicit_deadline or _infer_deadline_from_history(chat_history)

	return CalendarToolArgs(
		query_type="deadline" if deadline else "semester",
		season=None,
		year=year,
		block_number=None,
		specific_deadline=deadline,
		scope="full_year",
		timezone=user_timezone,
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
	tool_def = get_calendar_tool_definition()
	explicit_deadline = normalize_deadline_term(message)
	explicit_scope = normalize_query_scope(message)

	current_ctx = _current_term_context(user_timezone)
	prompt = _ROUTER_SYSTEM_PROMPT_TEMPLATE.format(current_context=current_ctx)
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
			try:
				current_year = datetime.now(ZoneInfo(user_timezone)).year
			except Exception:
				current_year = datetime.now(ZoneInfo("UTC")).year

			fn = getattr(tc, "function", None) or tc.get("function", {})
			args_str = getattr(fn, "arguments", None) or fn.get("arguments", "{}")
			args_dict = json.loads(args_str)
			if args_dict.get("query_type") == "full_year":
				args_dict["query_type"] = "semester"
				args_dict["scope"] = "full_year"
			if explicit_deadline:
				args_dict["specific_deadline"] = explicit_deadline
			if explicit_scope == "full_year":
				args_dict["scope"] = "full_year"
				args_dict["season"] = None
				args_dict["block_number"] = None
				args_dict["year"] = _extract_year(message) or _infer_year_from_history(
					chat_history,
					current_year,
				)
			args_dict.setdefault("timezone", user_timezone)
			args_dict.setdefault("scope", "term")
			return CalendarToolArgs(**args_dict), None
		except Exception as e:
			logger.error(f"Failed to parse calendar tool args: {e}")
			# Fall through to deterministic normalization/fallback paths below.

	if explicit_scope == "full_year" and (
		_CALENDAR_CONTEXT_HINTS.search(message or "")
		or _history_has_calendar_context(chat_history)
	):
		return (
			_build_year_scope_args_from_context(
				message,
				user_timezone,
				chat_history,
				explicit_deadline,
			),
			None,
		)

	if explicit_deadline and (
		_CALENDAR_CONTEXT_HINTS.search(message or "")
		or _history_has_calendar_context(chat_history)
	):
		scope = "full_year" if explicit_scope == "full_year" else "term"
		return (
			_build_deadline_args_from_context(
				message,
				user_timezone,
				chat_history,
				explicit_deadline,
				scope=scope,
			),
			None,
		)

	lowered = message.lower()
	direct_current_term_patterns = [
		r"\bwhat\s+semester\b",
		r"\bwhich\s+semester\b",
		r"\bwhat\s+term\b",
		r"\bwhich\s+term\b",
		r"\bwhat\s+block\b",
		r"\bwhich\s+block\b",
		r"\bcurrent\s+(semester|term|block)\b",
		r"\bare\s+we\s+in\b",
	]
	if any(re.search(pattern, lowered) for pattern in direct_current_term_patterns):
		try:
			today = datetime.now(ZoneInfo(user_timezone)).date()
		except Exception:
			today = datetime.now(ZoneInfo("UTC")).date()

		season, block = _season_block_for_month(today.month)
		return (
			CalendarToolArgs(
				query_type="semester",
				season=season,
				year=today.year,
				block_number=block,
				scope="term",
				timezone=user_timezone,
			),
			None,
		)

	text_response = getattr(ai_message, "content", "") or ""
	if text_response.strip():
		logger.info(f"Calendar router clarification: {text_response[:100]}")
		return None, text_response.strip()

	return None, None
