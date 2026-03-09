"""Schemas for calendar tool arguments and structured extraction output."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CalendarQueryType(str, Enum):
	BLOCK = "block"
	SEMESTER = "semester"
	DEADLINE = "deadline"
	GRADUATION = "graduation"


class CalendarQueryScope(str, Enum):
	TERM = "term"
	FULL_YEAR = "full_year"


class CalendarToolArgs(BaseModel):
	"""Arguments the LLM provides when calling the calendar tool."""

	query_type: CalendarQueryType = Field(
		description="Type of calendar query: block, semester, deadline, or graduation"
	)
	season: Optional[str] = Field(
		None, description="Academic season: winter, spring, or fall"
	)
	year: int = Field(2026, description="Academic year (e.g. 2026)")
	block_number: Optional[int] = Field(
		None, description="Block number 1-6 within the academic year"
	)
	specific_deadline: Optional[str] = Field(
		None,
		description=(
			"Specific deadline type: financial_hold, registration, priority_registration, "
			"add_course, drop, refund, payment, late_fees, withdraw, "
			"tuition_discount, application, grades"
		),
	)
	scope: CalendarQueryScope = Field(
		default=CalendarQueryScope.TERM,
		description=(
			"Scope of the query: 'term' for a specific block, "
			"'full_year' for an entire academic year overview"
		),
	)
	timezone: str = Field("UTC", description="IANA timezone from user")


class ExtractedCalendarEvent(BaseModel):
	"""A single event extracted from Pinecone chunks."""

	date: str = Field(description="Event date in ISO format YYYY-MM-DD")
	name: str = Field(description="Event name, e.g. 'Add Course Deadline'")
	description: Optional[str] = Field(
		None, description="Brief description of the event"
	)


class ExtractedBlockData(BaseModel):
	"""Events for a single block within a semester."""

	block_label: str = Field(description="e.g. 'Block 1', 'Block 2'")
	events: list[ExtractedCalendarEvent] = []


_DEFAULT_SOURCE_URL = (
	"https://studentservices.byupathway.edu/studentservices/academic-calendar"
)


class ExtractedCalendarData(BaseModel):
	"""Structured data extracted from Pinecone calendar chunks by the LLM."""

	title: str = Field(default="Academic Calendar", description="e.g. 'Winter 2026 — Block 2'")
	subtitle: str = Field(default="", description="Date range, e.g. 'March 2 – April 18, 2026'")
	block_or_semester_start: Optional[str] = Field(
		None, description="Start date in ISO format"
	)
	block_or_semester_end: Optional[str] = Field(
		None, description="End date in ISO format"
	)
	events: list[ExtractedCalendarEvent] = Field(
		default_factory=list, description="List of calendar events"
	)
	source_url: Optional[str] = Field(
		default=_DEFAULT_SOURCE_URL,
		description="Official source URL",
	)
	footnote: Optional[str] = None
	blocks: Optional[list[ExtractedBlockData]] = Field(
		None,
		description=(
			"For full-year or multi-block overview queries: events grouped "
			"by block within the selected scope"
		),
	)
