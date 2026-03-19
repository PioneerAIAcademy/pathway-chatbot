from types import SimpleNamespace

from app.tools.calendar.router import (
    _apply_conversational_scope,
    _apply_missing_year_default,
    _apply_next_block_default,
    _build_default_overview_args,
    _extract_any_term_number,
    _extract_block_context,
    _invalid_term_number_response,
    _normalize_clarification_text,
    _FULL_YEAR_REQUEST_PATTERN,
)
from app.tools.calendar.service import _build_card_explanation_payload


class TestConversationalScope:
    def test_semester_followup_inherits_prior_semester(self):
        args = {
            "query_type": "deadline",
            "specific_deadline": "payment",
        }

        _apply_conversational_scope(
            args,
            "Show me all key deadlines",
            "Here are the key dates for Winter 2025:",
        )

        assert args["query_type"] == "semester"
        assert args["scope"] == "term"
        assert args["season"] == "winter"
        assert args["year"] == 2025
        assert "block_number" not in args
        assert "specific_deadline" not in args

    def test_block_followup_inherits_prior_block(self):
        args = {
            "query_type": "deadline",
            "specific_deadline": "application",
        }

        _apply_conversational_scope(
            args,
            "show me all dates",
            "Here's the application deadline for Winter 2026 — Block 2:",
        )

        assert args["query_type"] == "block"
        assert args["scope"] == "term"
        assert args["season"] == "winter"
        assert args["year"] == 2026
        assert args["block_number"] == 2
        assert "specific_deadline" not in args

    def test_full_year_followup_inherits_full_year_scope(self):
        args = {
            "query_type": "deadline",
            "specific_deadline": "payment",
        }

        _apply_conversational_scope(
            args,
            "display all key deadlines",
            "Here's the full 2025 academic calendar:",
        )

        assert args["query_type"] == "semester"
        assert args["scope"] == "full_year"
        assert args["year"] == 2025
        assert args["season"] is None
        assert "block_number" not in args
        assert "specific_deadline" not in args

    def test_explicit_current_message_wins(self):
        args = {
            "query_type": "deadline",
            "season": "fall",
            "year": 2026,
        }

        _apply_conversational_scope(
            args,
            "Show me Fall 2026 deadlines",
            "Here are the key dates for Winter 2025:",
        )

        assert args["query_type"] == "deadline"
        assert args["season"] == "fall"
        assert args["year"] == 2026

    def test_next_block_default_respects_scoped_args(self):
        args = {
            "query_type": "semester",
            "scope": "term",
            "season": "winter",
            "year": 2025,
        }

        _apply_next_block_default(args, "Show me all key deadlines", "UTC")

        assert args["season"] == "winter"
        assert args["year"] == 2025
        assert "block_number" not in args


class TestDeterministicDefaults:
    def test_missing_year_defaults_to_current_year_for_explicit_block(self):
        args = {
            "query_type": "block",
            "block_number": 2,
        }

        _apply_missing_year_default(args, "When does term 2 start?", "UTC")

        assert args["year"] == 2026

    def test_broad_calendar_overview_defaults_to_current_full_year(self):
        args = _build_default_overview_args("Show me the academic calendar", "UTC")

        assert args is not None
        assert args.query_type.value == "semester"
        assert args.scope == "full_year"
        assert args.year == 2026

    def test_clarification_text_is_neutralized(self):
        text = _normalize_clarification_text(
            "Could you please clarify which year you are referring to for Term 2?"
        )

        assert text == "Which year should be checked?"
        assert "you" not in text.lower()


class TestInvalidTermHandling:
    def test_extract_any_term_number_supports_invalid_terms(self):
        assert _extract_any_term_number("When does term 9 start?") == 9
        assert _extract_any_term_number("When is Block 10 tuition due?") == 10
        assert _extract_any_term_number("When does term 6 start?") == 6

    def test_invalid_term_number_response_mentions_valid_range(self):
        text = _invalid_term_number_response(9)
        assert "Blocks 1 through 6" in text
        assert "There is no Term 9" in text


class TestCardExplanationPayload:
    def test_multi_block_payload_uses_all_tabs(self):
        card = {
            "title": "Winter 2025",
            "subtitle": "November 24, 2024 – April 24, 2025",
            "events": [
                {
                    "name": "Start",
                    "date": "2025-01-06",
                    "status": "past",
                }
            ],
            "tabs": [
                {
                    "label": "Block 1",
                    "events": [
                        {"name": "Start", "date": "2025-01-06", "status": "past"},
                        {
                            "name": "Add Course Deadline",
                            "date": "2025-01-10",
                            "status": "past",
                        },
                        {"name": "End", "date": "2025-02-22", "status": "past"},
                    ],
                },
                {
                    "label": "Block 2",
                    "events": [
                        {"name": "Start", "date": "2025-03-03", "status": "past"},
                        {
                            "name": "Payment Deadline",
                            "date": "2025-03-23",
                            "status": "past",
                        },
                        {"name": "End", "date": "2025-04-19", "status": "past"},
                    ],
                },
            ],
        }
        history = [
            SimpleNamespace(role="user", content="Show me Winter 2025"),
            SimpleNamespace(role="assistant", content="Here are the key dates for Winter 2025:"),
        ]

        payload = _build_card_explanation_payload(
            card,
            "Show me Winter 2025",
            source_context="Winter source context",
            chat_history=history,
        )

        assert payload["card_scope"] == "semester"
        assert len(payload["blocks_shown"]) == 2
        assert payload["blocks_shown"][0]["block_start"] == "2025-01-06"
        assert payload["blocks_shown"][0]["block_end"] == "2025-02-22"
        assert payload["blocks_shown"][1]["block_start"] == "2025-03-03"
        assert payload["blocks_shown"][1]["block_end"] == "2025-04-19"
        assert any(
            event.startswith("Block 1 — Start: 2025-01-06")
            for event in payload["key_events"]
        )
        assert any(
            event.startswith("Block 2 — Start: 2025-03-03")
            for event in payload["key_events"]
        )
        assert payload["source_documents"] == "Winter source context"
        assert len(payload["conversation_history"]) == 2


class TestSeasonScopeOverride:
    """When the user names a season (e.g., 'Winter 2025') but the LLM returns
    scope=full_year, the deterministic override should force scope=term."""

    def test_winter_2025_forces_term_scope(self):
        args = {"query_type": "semester", "scope": "full_year", "season": "winter", "year": 2025}
        message = "Show me Winter 2025"
        explicit_season, _, _ = _extract_block_context(message)
        if (
            explicit_season
            and (args.get("scope") or "term").lower() == "full_year"
            and not _FULL_YEAR_REQUEST_PATTERN.search(message or "")
        ):
            args["scope"] = "term"
            args.setdefault("season", explicit_season)
            args["query_type"] = "semester"
        assert args["scope"] == "term"
        assert args["season"] == "winter"
        assert args["query_type"] == "semester"

    def test_full_year_request_not_overridden(self):
        args = {"query_type": "semester", "scope": "full_year", "season": "winter", "year": 2025}
        message = "Show me the full year 2025 calendar"
        explicit_season, _, _ = _extract_block_context(message)
        should_override = (
            explicit_season
            and (args.get("scope") or "term").lower() == "full_year"
            and not _FULL_YEAR_REQUEST_PATTERN.search(message or "")
        )
        assert not should_override  # "full year" in message, do NOT override

    def test_spring_2026_term_scope_untouched(self):
        args = {"query_type": "semester", "scope": "term", "season": "spring", "year": 2026}
        message = "Show me Spring 2026"
        explicit_season, _, _ = _extract_block_context(message)
        if (
            explicit_season
            and (args.get("scope") or "term").lower() == "full_year"
            and not _FULL_YEAR_REQUEST_PATTERN.search(message or "")
        ):
            args["scope"] = "term"
        # Already term scope — no change needed
        assert args["scope"] == "term"

    def test_fall_semester_forces_term_scope(self):
        args = {"query_type": "full_year", "scope": "full_year", "year": 2026}
        message = "Show me Fall semester"
        explicit_season, _, _ = _extract_block_context(message)
        if (
            explicit_season
            and (args.get("scope") or "term").lower() == "full_year"
            and not _FULL_YEAR_REQUEST_PATTERN.search(message or "")
        ):
            args["scope"] = "term"
            args.setdefault("season", explicit_season)
            args["query_type"] = "semester"
        assert args["scope"] == "term"
        assert args["season"] == "fall"
        assert args["query_type"] == "semester"
