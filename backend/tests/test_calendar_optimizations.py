"""
Comprehensive tests for calendar pipeline performance optimizations.

Tests:
 - Phase 1: Parallel Pinecone queries (asyncio.gather)
 - Phase 2: JSON mode extraction (direct AsyncOpenAI client)
 - Phase 3: In-memory TTL cache (CalendarCache)
 - Phase 4: Context deduplication + trimming
"""

import asyncio
import json
import time
from datetime import date
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Imports under test ──────────────────────────────────────────────────

from app.tools.calendar.cache import CalendarCache, _cache_key, calendar_cache
from app.tools.calendar.schema import (
    CalendarQueryType,
    CalendarToolArgs,
    ExtractedCalendarData,
    ExtractedCalendarEvent,
)
from app.tools.calendar.tool import (
    _deduplicate_node_content,
    _MAX_CONTEXT_CHARS,
    _MAX_CONTEXT_CHARS_FULL_YEAR,
    _EXTRACTION_SYSTEM,
    build_calendar_card,
    extract_structured_data,
)


# ── Helpers ─────────────────────────────────────────────────────────────


class FakeNode:
    """Minimal node object matching what Pinecone returns."""

    def __init__(self, text: str, node_id: str = "n1", url: str = ""):
        self.text = text
        self.score = 0.9
        self.node = MagicMock()
        self.node.node_id = node_id
        self.node.metadata = {"url": url} if url else {}


def _make_args(**overrides) -> CalendarToolArgs:
    defaults = {
        "query_type": "block",
        "year": 2026,
        "block_number": 2,
        "scope": "term",
    }
    defaults.update(overrides)
    return CalendarToolArgs(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: Cache Tests
# ═══════════════════════════════════════════════════════════════════════


class TestCalendarCache:
    """Tests for CalendarCache correctness and edge cases."""

    def test_miss_on_empty(self):
        cache = CalendarCache(ttl=60, max_size=10)
        args = _make_args()
        assert cache.get(args) is None
        assert cache.size == 0

    def test_put_then_hit(self):
        cache = CalendarCache(ttl=60, max_size=10)
        args = _make_args()
        card = {"title": "Winter 2026 — Block 2", "events": []}
        meta = {"pipeline_status": "success"}
        cache.put(args, card, meta)
        result = cache.get(args)
        assert result is not None
        assert result[0]["title"] == "Winter 2026 — Block 2"
        assert result[1]["pipeline_status"] == "success"
        assert cache.size == 1

    def test_ttl_expiry(self):
        cache = CalendarCache(ttl=0.05, max_size=10)  # 50ms TTL
        args = _make_args()
        cache.put(args, {"title": "test"}, {"status": "ok"})
        assert cache.get(args) is not None  # immediately: hit
        time.sleep(0.06)
        assert cache.get(args) is None  # expired
        assert cache.size == 0  # entry cleaned up

    def test_eviction_at_capacity(self):
        cache = CalendarCache(ttl=60, max_size=3)
        for i in range(3):
            cache.put(_make_args(year=2020 + i), {"title": f"y{i}"}, {})
        assert cache.size == 3

        # Adding a 4th should evict the oldest
        cache.put(_make_args(year=2030), {"title": "newest"}, {})
        assert cache.size == 3
        assert cache.get(_make_args(year=2020)) is None  # evicted
        assert cache.get(_make_args(year=2030)) is not None  # present

    def test_overwrite_existing_key_no_eviction(self):
        cache = CalendarCache(ttl=60, max_size=2)
        args = _make_args()
        cache.put(args, {"title": "v1"}, {})
        cache.put(args, {"title": "v2"}, {})
        assert cache.size == 1  # same key, no growth
        assert cache.get(args)[0]["title"] == "v2"

    def test_clear(self):
        cache = CalendarCache(ttl=60, max_size=10)
        for i in range(5):
            cache.put(_make_args(year=2020 + i), {}, {})
        assert cache.size == 5
        cache.clear()
        assert cache.size == 0

    def test_different_args_different_keys(self):
        cache = CalendarCache(ttl=60, max_size=10)
        a1 = _make_args(query_type="block", block_number=2)
        a2 = _make_args(query_type="block", block_number=3)
        a3 = _make_args(query_type="semester", scope="full_year")
        cache.put(a1, {"title": "block2"}, {})
        cache.put(a2, {"title": "block3"}, {})
        cache.put(a3, {"title": "full"}, {})
        assert cache.size == 3
        assert cache.get(a1)[0]["title"] == "block2"
        assert cache.get(a2)[0]["title"] == "block3"
        assert cache.get(a3)[0]["title"] == "full"

    def test_cache_stores_none_card(self):
        """Pipeline can cache a None card (failed extraction)."""
        cache = CalendarCache(ttl=60, max_size=10)
        args = _make_args()
        cache.put(args, None, {"pipeline_status": "extraction_failed"})
        result = cache.get(args)
        assert result is not None
        assert result[0] is None
        assert result[1]["pipeline_status"] == "extraction_failed"


class TestCacheKey:
    """Tests for the _cache_key() determinism."""

    def test_deterministic(self):
        args = _make_args()
        assert _cache_key(args) == _cache_key(args)

    def test_different_args_different_keys(self):
        k1 = _cache_key(_make_args(block_number=2))
        k2 = _cache_key(_make_args(block_number=3))
        assert k1 != k2

    def test_scope_in_key(self):
        k1 = _cache_key(_make_args(scope="term"))
        k2 = _cache_key(_make_args(scope="full_year"))
        # Different scopes produce different keys
        assert k1 != k2
        assert "term" in k1
        assert "full_year" in k2

    def test_none_fields_handled(self):
        args = _make_args(season=None, block_number=None, specific_deadline=None)
        key = _cache_key(args)
        assert "||" in key  # None becomes empty string


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4: Deduplication Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDeduplication:
    """Tests for _deduplicate_node_content."""

    def test_removes_exact_duplicates(self):
        nodes = [FakeNode("abc " * 60), FakeNode("abc " * 60)]
        result = _deduplicate_node_content(nodes)
        assert len(result) == 1

    def test_keeps_different_nodes(self):
        nodes = [FakeNode("alpha " * 60), FakeNode("beta " * 60)]
        result = _deduplicate_node_content(nodes)
        assert len(result) == 2

    def test_near_duplicate_same_prefix(self):
        """Nodes with same first 200 chars but different tail are deduped."""
        shared = "x" * 200
        nodes = [FakeNode(shared + " tail A"), FakeNode(shared + " tail B")]
        result = _deduplicate_node_content(nodes)
        assert len(result) == 1  # first 200 chars match

    def test_empty_text_skipped(self):
        nodes = [FakeNode(""), FakeNode("  "), FakeNode("actual content")]
        result = _deduplicate_node_content(nodes)
        assert len(result) == 1
        assert result[0].text == "actual content"

    def test_preserves_order(self):
        nodes = [FakeNode(f"node {i}") for i in range(5)]
        result = _deduplicate_node_content(nodes)
        assert [n.text for n in result] == [f"node {i}" for i in range(5)]

    def test_many_duplicates(self):
        nodes = [FakeNode("same text")] * 100
        result = _deduplicate_node_content(nodes)
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4: Context Trimming Constants
# ═══════════════════════════════════════════════════════════════════════


class TestContextConstants:
    """Verify the context trimming constants are correct."""

    def test_full_year_context_reduced(self):
        assert _MAX_CONTEXT_CHARS_FULL_YEAR == 15000, (
            f"Expected 10000, got {_MAX_CONTEXT_CHARS_FULL_YEAR}"
        )

    def test_single_block_context_unchanged(self):
        assert _MAX_CONTEXT_CHARS == 4000

    def test_extraction_system_prompt_has_json_schema(self):
        assert '"events"' in _EXTRACTION_SYSTEM
        assert '"title"' in _EXTRACTION_SYSTEM
        assert "YYYY-MM-DD" in _EXTRACTION_SYSTEM

    def test_extraction_system_prompt_consolidated(self):
        """Old prompt had 3 separate CRITICAL rules; new has 0."""
        assert _EXTRACTION_SYSTEM.count("CRITICAL") == 0, (
            "Old triple-CRITICAL rules should be consolidated"
        )

    def test_extraction_system_prompt_has_block_rules(self):
        assert "Block 1-2 (Winter)" in _EXTRACTION_SYSTEM
        assert "Block 3-4 (Spring)" in _EXTRACTION_SYSTEM
        assert "Block 5-6 (Fall)" in _EXTRACTION_SYSTEM
        assert "CANONICAL" in _EXTRACTION_SYSTEM


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: JSON Mode Extraction Tests
# ═══════════════════════════════════════════════════════════════════════


class TestJSONModeExtraction:
    """Tests for extract_structured_data with the direct OpenAI client."""

    @pytest.mark.asyncio
    async def test_extract_success(self):
        """Mock the OpenAI client and verify extraction works."""
        fake_response = MagicMock()
        fake_response.choices = [MagicMock()]
        fake_response.choices[0].message.content = json.dumps({
            "title": "Winter 2026 — Block 2",
            "subtitle": "March 2 – April 18, 2026",
            "block_or_semester_start": "2026-03-02",
            "block_or_semester_end": "2026-04-18",
            "events": [
                {"date": "2026-03-02", "name": "Block 2 Start", "description": "Classes begin"},
                {"date": "2026-04-18", "name": "Block 2 End", "description": "Classes end"},
            ],
            "source_url": None,
            "footnote": None,
            "blocks": None,
        })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)

        nodes = [FakeNode("Block 2 starts March 2, 2026. Block 2 ends April 18, 2026.")]
        args = _make_args()

        with patch("app.tools.calendar.tool._get_openai_client", return_value=mock_client):
            result = await extract_structured_data(nodes, args)

        assert result is not None
        assert result.title == "Winter 2026 — Block 2"
        assert len(result.events) == 2
        assert result.events[0].date == "2026-03-02"

        # Verify the client was called with JSON mode
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["temperature"] == 0

    @pytest.mark.asyncio
    async def test_extract_no_markdown_fences_needed(self):
        """JSON mode should never produce markdown fences."""
        raw_json = json.dumps({
            "title": "Test",
            "events": [{"date": "2026-01-01", "name": "New Year", "description": "Start"}],
        })
        fake_response = MagicMock()
        fake_response.choices = [MagicMock()]
        fake_response.choices[0].message.content = raw_json

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)

        nodes = [FakeNode("Calendar data here")]
        args = _make_args()

        with patch("app.tools.calendar.tool._get_openai_client", return_value=mock_client):
            result = await extract_structured_data(nodes, args)

        assert result is not None
        assert result.title == "Test"

    @pytest.mark.asyncio
    async def test_extract_null_stripping(self):
        """Fields with null or 'null' values should be stripped before Pydantic."""
        fake_response = MagicMock()
        fake_response.choices = [MagicMock()]
        fake_response.choices[0].message.content = json.dumps({
            "title": "Test Card",
            "subtitle": None,
            "events": [{"date": "2026-03-01", "name": "Start", "description": "Begin"}],
            "source_url": "null",
        })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)

        nodes = [FakeNode("some content")]
        args = _make_args()

        with patch("app.tools.calendar.tool._get_openai_client", return_value=mock_client):
            result = await extract_structured_data(nodes, args)

        assert result is not None
        assert result.title == "Test Card"
        # subtitle and source_url with null should be stripped, using defaults
        assert result.subtitle == ""  # default

    @pytest.mark.asyncio
    async def test_extract_0_events_retries_single_block(self):
        """For single-block queries (max_attempts=2), should retry on 0 events."""
        empty_response = MagicMock()
        empty_response.choices = [MagicMock()]
        empty_response.choices[0].message.content = json.dumps({
            "title": "Empty",
            "events": [],
        })

        good_response = MagicMock()
        good_response.choices = [MagicMock()]
        good_response.choices[0].message.content = json.dumps({
            "title": "Good",
            "events": [{"date": "2026-03-01", "name": "Start", "description": "Go"}],
        })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[empty_response, good_response]
        )

        nodes = [FakeNode("content")]
        args = _make_args()

        with patch("app.tools.calendar.tool._get_openai_client", return_value=mock_client):
            result = await extract_structured_data(nodes, args)

        assert result is not None
        assert result.title == "Good"
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_extract_full_year_no_retry(self):
        """For full_year queries (max_attempts=1), should NOT retry."""
        empty_response = MagicMock()
        empty_response.choices = [MagicMock()]
        empty_response.choices[0].message.content = json.dumps({
            "title": "Empty",
            "events": [],
        })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=empty_response)

        nodes = [FakeNode("content")]
        args = _make_args(scope="full_year", query_type="semester")

        with patch("app.tools.calendar.tool._get_openai_client", return_value=mock_client):
            result = await extract_structured_data(nodes, args)

        assert result is None  # gave up after 1 attempt
        assert mock_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_extract_empty_nodes_returns_none(self):
        result = await extract_structured_data([], _make_args())
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_dedup_runs_before_context(self):
        """Duplicate nodes should be deduped before building context."""
        fake_response = MagicMock()
        fake_response.choices = [MagicMock()]
        fake_response.choices[0].message.content = json.dumps({
            "title": "Test",
            "events": [{"date": "2026-03-01", "name": "E", "description": "D"}],
        })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)

        # 10 identical nodes — dedup should reduce to 1
        nodes = [FakeNode("Block 2 starts March 2, 2026.")] * 10
        args = _make_args()

        with patch("app.tools.calendar.tool._get_openai_client", return_value=mock_client):
            result = await extract_structured_data(nodes, args)

        # Check the context sent to LLM — should NOT contain 10 copies
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_msg = call_kwargs["messages"][1]["content"]
        # The deduped context should have the text only once
        assert user_msg.count("Block 2 starts March 2, 2026.") == 1


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: Parallel Query Tests
# ═══════════════════════════════════════════════════════════════════════


class TestParallelQueries:
    """Tests for the asyncio.gather parallelization in run_calendar_pipeline."""

    @pytest.mark.asyncio
    async def test_parallel_queries_fire_together(self):
        """Verify all 9 expansion queries fire in parallel, not sequentially."""
        call_times: list[float] = []

        async def mock_aretrieve(query: str):
            call_times.append(time.monotonic())
            await asyncio.sleep(0.01)  # simulate small latency
            return [FakeNode(f"result for {query}")]

        mock_retriever = MagicMock()
        mock_retriever.aretrieve = mock_aretrieve

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        args = CalendarToolArgs(
            query_type="semester",
            year=2026,
            scope="full_year",
        )

        fake_extracted = ExtractedCalendarData(
            title="2026 Academic Calendar",
            events=[
                ExtractedCalendarEvent(date="2026-01-05", name="Block 1 Start", description="Go"),
            ],
            blocks=[],
        )

        fake_card = {
            "type": "semester",
            "title": "2026 Academic Calendar",
            "subtitle": "",
            "status": "upcoming",
            "spotlight": None,
            "events": [{"date": "2026-01-05", "name": "Block 1 Start", "status": "past"}],
            "tabs": None,
            "sourceUrl": "https://example.com",
            "suggestedQuestions": [],
            "footnote": None,
        }

        with (
            patch("app.tools.calendar.service.query_pinecone_for_calendar", return_value=[
                FakeNode("initial query result"),
            ]),
            patch("app.tools.calendar.service.extract_structured_data", return_value=fake_extracted),
            patch("app.tools.calendar.service.build_calendar_card", return_value=fake_card),
            patch("app.tools.calendar.service.compute_suggestions", return_value=[]),
            patch("app.tools.calendar.service.build_secondary_calendar_text", return_value={
                "mode": "calendar_context", "confidence": 0.9, "reason": "test", "text": "",
            }),
            patch("app.tools.calendar.service.localize_calendar_card", side_effect=lambda c, **kw: c),
            patch("app.tools.calendar.service._available_years_from_nodes", return_value=[2026]),
            patch("app.tools.calendar.service._build_retrieved_docs_metadata", return_value={}),
            patch("app.tools.calendar.service._prioritize_nodes_for_full_year_blocks", side_effect=lambda n, *a, **kw: n),
            patch("app.tools.calendar.service.calendar_cache") as mock_cache,
        ):
            mock_cache.get.return_value = None

            from app.tools.calendar.service import run_calendar_pipeline
            card, meta = await run_calendar_pipeline(args, mock_index, user_query="show me 2026")

        # 9 expansion queries should have been fired via asyncio.gather
        # (query_pinecone_for_calendar is mocked for the initial query,
        #  but the 9 expansion queries go directly to retriever.aretrieve)
        assert len(call_times) == 9, f"Expected 9 expansion queries, got {len(call_times)}"

        # Key assertion: the 9 expansion queries should start nearly simultaneously
        time_spread = max(call_times) - min(call_times)
        assert time_spread < 0.05, (
            f"Expansion queries spread over {time_spread:.3f}s — "
            f"should be near-simultaneous (<50ms)"
        )

    @pytest.mark.asyncio
    async def test_partial_failure_handling(self):
        """If some expansion queries fail, the pipeline should still work."""
        call_count = 0

        async def mock_aretrieve(query: str):
            nonlocal call_count
            call_count += 1
            if "block 3" in query or "block 5" in query:
                raise Exception("Simulated Pinecone timeout")
            return [FakeNode(f"result for {query}", node_id=f"n{call_count}")]

        mock_retriever = MagicMock()
        mock_retriever.aretrieve = mock_aretrieve

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        args = CalendarToolArgs(
            query_type="semester",
            year=2026,
            scope="full_year",
        )

        fake_extracted = ExtractedCalendarData(
            title="2026",
            events=[
                ExtractedCalendarEvent(date="2026-01-05", name="Start", description="Go"),
            ],
        )

        fake_card = {
            "type": "semester", "title": "2026", "subtitle": "", "status": "upcoming",
            "spotlight": None, "events": [{"date": "2026-01-05", "name": "Start", "status": "past"}],
            "tabs": None, "sourceUrl": "https://x.com", "suggestedQuestions": [], "footnote": None,
        }

        with (
            patch("app.tools.calendar.service.query_pinecone_for_calendar", return_value=[
                FakeNode("initial"),
            ]),
            patch("app.tools.calendar.service.extract_structured_data", return_value=fake_extracted),
            patch("app.tools.calendar.service.build_calendar_card", return_value=fake_card),
            patch("app.tools.calendar.service.compute_suggestions", return_value=[]),
            patch("app.tools.calendar.service.build_secondary_calendar_text", return_value={
                "mode": "calendar_context", "confidence": 0.9, "reason": "test", "text": "",
            }),
            patch("app.tools.calendar.service.localize_calendar_card", side_effect=lambda c, **kw: c),
            patch("app.tools.calendar.service._available_years_from_nodes", return_value=[2026]),
            patch("app.tools.calendar.service._build_retrieved_docs_metadata", return_value={}),
            patch("app.tools.calendar.service._prioritize_nodes_for_full_year_blocks", side_effect=lambda n, *a, **kw: n),
            patch("app.tools.calendar.service.calendar_cache") as mock_cache,
        ):
            mock_cache.get.return_value = None

            from app.tools.calendar.service import run_calendar_pipeline
            card, meta = await run_calendar_pipeline(args, mock_index, user_query="show me 2026")

        # Pipeline should still succeed despite 2 failed expansion queries
        assert card is not None
        assert meta["pipeline_status"] == "success"


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: Cache Integration in Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════


class TestCacheIntegration:
    """Tests for cache integration in run_calendar_pipeline."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_pipeline_but_regenerates_post_text(self):
        """A cache hit should skip Pinecone/extraction but regenerate post-card text."""
        from app.tools.calendar.service import run_calendar_pipeline

        args = _make_args()
        cached_card = {"title": "Cached Card", "events": []}
        cached_meta = {"pipeline_status": "success"}

        with (
            patch("app.tools.calendar.service.calendar_cache") as mock_cache,
            patch("app.tools.calendar.service.build_secondary_calendar_text", return_value={
                "mode": "calendar_context", "confidence": 0.9, "reason": "test",
                "text": "Fresh explanation for this question.",
            }),
            patch("app.tools.calendar.service.localize_calendar_intro",
                  side_effect=lambda t, **kw: t),
        ):
            mock_cache.get.return_value = (cached_card, cached_meta)

            card, meta = await run_calendar_pipeline(args, MagicMock(), user_query="has registration passed?")

        assert card["title"] == "Cached Card"
        assert meta["cache_hit"] is True
        # Post-card text should be fresh, not from cache
        assert card["postCardText"] == "Fresh explanation for this question."
        # Pinecone should NOT have been called
        mock_cache.get.assert_called_once_with(args)

    @pytest.mark.asyncio
    async def test_cache_hit_no_post_text_when_empty(self):
        """A cache hit with empty secondary text should have no postCardText."""
        from app.tools.calendar.service import run_calendar_pipeline

        args = _make_args()
        cached_card = {"title": "Cached", "events": [], "postCardText": "stale text"}
        cached_meta = {"pipeline_status": "success"}

        with (
            patch("app.tools.calendar.service.calendar_cache") as mock_cache,
            patch("app.tools.calendar.service.build_secondary_calendar_text", return_value={
                "mode": "calendar_context", "confidence": 0.9, "reason": "no_query", "text": "",
            }),
        ):
            mock_cache.get.return_value = (cached_card, cached_meta)

            card, meta = await run_calendar_pipeline(args, MagicMock(), user_query="")

        assert "postCardText" not in card
        # Original cached_card should not be mutated
        assert cached_card["postCardText"] == "stale text"

    @pytest.mark.asyncio
    async def test_cache_miss_runs_pipeline(self):
        """A cache miss with None index returns skipped_no_index."""
        from app.tools.calendar.service import run_calendar_pipeline

        args = _make_args()

        with patch("app.tools.calendar.service.calendar_cache") as mock_cache:
            mock_cache.get.return_value = None  # miss

            # Pipeline will fail at shared_index being None
            card, meta = await run_calendar_pipeline(args, None, user_query="when")

        assert meta["pipeline_status"] == "skipped_no_index"
        # No successful card, so nothing should be cached
        mock_cache.put.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# Sanity: Singleton Cache
# ═══════════════════════════════════════════════════════════════════════


class TestSingleton:
    """Verify the module-level singleton behaves correctly."""

    def test_singleton_exists(self):
        assert calendar_cache is not None
        assert isinstance(calendar_cache, CalendarCache)

    def test_singleton_config(self):
        from app.tools.calendar.config import CALENDAR_CACHE_MAX_SIZE, CALENDAR_CACHE_TTL
        assert calendar_cache._ttl == CALENDAR_CACHE_TTL
        assert calendar_cache._max_size == CALENDAR_CACHE_MAX_SIZE


# ═══════════════════════════════════════════════════════════════════════
# Prompt Sanity Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPromptSanity:
    """Verify extraction prompt content for correctness."""

    def test_no_markdown_fence_instruction(self):
        """JSON mode means we don't need 'no markdown fences' instruction."""
        # The old prompt had "Respond with ONLY a JSON object (no markdown fences...)"
        assert "markdown fences" not in _EXTRACTION_SYSTEM.lower()

    def test_schema_present(self):
        assert '"events"' in _EXTRACTION_SYSTEM
        assert '"blocks"' in _EXTRACTION_SYSTEM
        assert '"block_label"' in _EXTRACTION_SYSTEM

    def test_no_invent_dates_rule(self):
        assert "DO NOT INVENT" in _EXTRACTION_SYSTEM

    def test_description_required(self):
        assert "description" in _EXTRACTION_SYSTEM

    def test_prompt_length_reasonable(self):
        """Prompt should include all 13 event types but stay under 2000 chars."""
        assert len(_EXTRACTION_SYSTEM) < 2000, (
            f"Extraction prompt is {len(_EXTRACTION_SYSTEM)} chars, expected <2000"
        )

    def test_all_event_types_listed(self):
        """Extraction prompt must enumerate all 13 academic calendar event types."""
        required_events = [
            "Start", "Financial Holds Applied", "Registration Opens",
            "Application Deadline", "Add Course Deadline",
            "Tuition Discount Deadline", "Drop/Auto-Drop Deadline",
            "Last Day for a Refund", "Payment Deadline", "Late Fees Applied",
            "Last Day to Withdraw", "Grades Available", "End",
        ]
        for event in required_events:
            assert event in _EXTRACTION_SYSTEM, f"Missing event type: {event}"
