import asyncio 
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from aiostream import stream
from fastapi import Request
from fastapi.responses import StreamingResponse
from llama_index.core.chat_engine.types import StreamingAgentChatResponse

from app.api.routers.events import EventCallbackHandler
from app.api.routers.message_variations import (
    get_calendar_building_message,
    get_calendar_extraction_message,
    get_calendar_retrieval_message,
    get_graduation_retrieval_message,
    get_pushback_message,
    get_retrieval_start_message,
    get_text_format_message,
)
from app.api.routers.models import ChatData, Message, SourceNodes
from app.api.services.suggestion import NextQuestionSuggestion
from app.tools.calendar.config import (
    ACADEMIC_CALENDAR_URL,
    CALENDAR_ONLY_TIMEOUT,
    CALENDAR_PIPELINE_TIMEOUT,
    MIN_TOKENS_BEFORE_CALENDAR,
    TYPEWRITER_CHUNK_DELAY,
)
from app.utils.date_spans import extract_date_spans

logger = logging.getLogger("uvicorn")


class VercelStreamResponse(StreamingResponse):
    """
    Class to convert the response from the chat engine to the streaming format expected by Vercel
    """

    TEXT_PREFIX = "0:"
    DATA_PREFIX = "8:"
    ERROR_PREFIX = "3:"

    @classmethod
    def convert_text(cls, token: str):
        # Escape newlines and double quotes to avoid breaking the stream
        token = json.dumps(token)
        return f"{cls.TEXT_PREFIX}{token}\n"

    @classmethod
    def convert_data(cls, data: dict):
        data_str = json.dumps(data)
        return f"{cls.DATA_PREFIX}[{data_str}]\n"

    @classmethod
    def convert_error(cls, message: str):
        message_str = json.dumps(message)
        return f"{cls.ERROR_PREFIX}{message_str}\n"

    @classmethod
    def _iter_text_chunks(cls, text: str):
        """Yield individual characters for letter-by-letter typewriter rendering.

        Newline sequences are yielded as a single chunk so paragraph breaks
        appear instantly rather than introducing extra delays.
        """
        if not text:
            return
        i = 0
        while i < len(text):
            if text[i] == "\n":
                # Gather consecutive newlines into one chunk
                j = i
                while j < len(text) and text[j] == "\n":
                    j += 1
                yield text[i:j]
                i = j
            else:
                yield text[i]
                i += 1

    def __init__(
        self,
        request: Request,
        event_handler: EventCallbackHandler,
        response: StreamingAgentChatResponse | Awaitable[StreamingAgentChatResponse],
        chat_data: ChatData,
        trace_id: str | None = None,
        skip_suggestions: bool = False,
        user_language: str | None = None,
        on_stream_end: Optional[Callable[[str], Awaitable[None]]] = None,
        emit_initial_status: bool = True,
        calendar_pipeline: Optional[Callable[[], Awaitable[Optional[dict]]]] = None,
        calendar_intro: Optional[str] = None,
        supplemental_text_pipeline: Optional[
            Callable[[dict], Awaitable[Optional[dict[str, Any]]]]
        ] = None,
        rag_fallback: Optional[
            Callable[[], Awaitable[StreamingAgentChatResponse]]
        ] = None,
        calendar_query_type: Optional[str] = None,
        calendar_progress_queue: Optional[asyncio.Queue] = None,
    ):
        content = VercelStreamResponse.content_generator(
            request,
            event_handler,
            response,
            chat_data,
            trace_id,
            skip_suggestions,
            user_language,
            on_stream_end,
            emit_initial_status,
            calendar_pipeline,
            calendar_intro,
            supplemental_text_pipeline,
            rag_fallback,
            calendar_query_type,
            calendar_progress_queue,
        )
        super().__init__(content=content, media_type="text/plain")
        # Prevent proxy / browser buffering so each character-level chunk
        # reaches the client immediately for a visible typewriter effect.
        self.headers["Cache-Control"] = "no-cache"
        self.headers["X-Accel-Buffering"] = "no"

    @classmethod
    async def content_generator(
        cls,
        request: Request,
        event_handler: EventCallbackHandler,
        response: StreamingAgentChatResponse | Awaitable[StreamingAgentChatResponse],
        chat_data: ChatData,
        trace_id: str | None = None,
        skip_suggestions: bool = False,
        user_language: str | None = None,
        on_stream_end: Optional[Callable[[str], Awaitable[None]]] = None,
        emit_initial_status: bool = True,
        calendar_pipeline: Optional[Callable[[], Awaitable[Optional[dict]]]] = None,
        calendar_intro: Optional[str] = None,
        supplemental_text_pipeline: Optional[
            Callable[[dict], Awaitable[Optional[dict[str, Any]]]]
        ] = None,
        rag_fallback: Optional[
            Callable[[], Awaitable[StreamingAgentChatResponse]]
        ] = None,
        calendar_query_type: Optional[str] = None,
        calendar_progress_queue: Optional[asyncio.Queue] = None,
    ):
        final_response = ""
        resolved_response: StreamingAgentChatResponse | None = None
        response_task: asyncio.Task[StreamingAgentChatResponse] | None = None
        if calendar_intro is not None:
            # Calendar mode — no RAG engine needed.  Close the unused
            # response coroutine to suppress "coroutine was never awaited".
            if inspect.isawaitable(response):
                try:
                    coro_task = asyncio.create_task(response)
                    await coro_task
                except Exception:
                    pass  # _get_response returns None in calendar mode
        elif inspect.isawaitable(response):
            response_task = asyncio.create_task(response)
        else:
            resolved_response = response

        # Start calendar pipeline concurrently (if provided)
        calendar_task: asyncio.Task | None = None
        if calendar_pipeline is not None:
            calendar_task = asyncio.create_task(calendar_pipeline())

        # Yield the text response (RAG path only — calendar path is handled
        # directly in the outer try block).
        async def _chat_response_generator():
            nonlocal final_response
            nonlocal resolved_response

            final_response = ""
            calendar_emitted = False
            token_count = 0

            try:
                # Normal RAG path
                if resolved_response is None:
                    assert response_task is not None
                    resolved_response = await response_task

                async for token in resolved_response.async_response_gen():
                    final_response += token
                    token_count += 1
                    yield cls.convert_text(token)

                    # Emit calendar patches after introductory text
                    if (
                        not calendar_emitted
                        and calendar_task is not None
                        and (
                            token_count >= MIN_TOKENS_BEFORE_CALENDAR
                            or "." in final_response
                        )
                    ):
                        calendar_emitted = True
                        for patch in await _resolve_calendar_patches(
                            calendar_task, trace_id
                        ):
                            yield patch

            except Exception as exc:
                event_handler.is_done = True
                yield cls.convert_error(str(exc))
                return

            # If calendar wasn't emitted during streaming (short response), try now
            if not calendar_emitted and calendar_task is not None:
                for patch in await _resolve_calendar_patches(
                    calendar_task, trace_id
                ):
                    yield patch

            # Generate suggested questions (skip for security-blocked responses)
            if not skip_suggestions:
                conversation = chat_data.messages + [
                    Message(role="assistant", content=final_response, trace_id=trace_id)
                ]
                questions = await NextQuestionSuggestion.suggest_next_questions(
                    conversation
                )
                if len(questions) > 0:
                    yield cls.convert_data(
                        {
                            "type": "suggested_questions",
                            "data": questions,
                            "trace_id": trace_id,
                        }
                    )

            date_spans = extract_date_spans(final_response, user_language)
            if date_spans:
                yield cls.convert_data(
                    {
                        "type": "date_spans",
                        "data": {
                            "phrases": date_spans,
                            "language": user_language,
                        },
                        "trace_id": trace_id,
                    }
                )

            # the text_generator is the leading stream, once it's finished, also finish the event stream
            event_handler.is_done = True

            # Yield user language for frontend localization
            if user_language:
                yield cls.convert_data(
                    {
                        "type": "user_language",
                        "data": {"language": user_language},
                        "trace_id": trace_id,
                    }
                )

            # Yield the source nodes
            yield cls.convert_data(
                {
                    "type": "sources",
                    "data": {
                        "nodes": [
                            SourceNodes.from_source_node(node).model_dump()
                            for node in (resolved_response.source_nodes if resolved_response else [])
                        ]
                    },
                    "trace_id": trace_id,
                }
            )

        # Yield the events from the event handler
        async def _event_generator():
            async for event in event_handler.async_event_gen():
                event_response = event.to_response()
                if event_response is not None:
                    event_response["trace_id"] = trace_id
                    yield cls.convert_data(event_response)

        try:
            # Stream a blank message early so the client creates the assistant message
            yield cls.convert_text("")

            if calendar_intro is not None:
                # ---- Calendar-only path (no RAG, no events) ----
                supplemental_source_nodes: list[Any] = []

                # Pick a status message that matches the calendar query type
                if calendar_query_type == "pushback":
                    _status_msg = get_pushback_message()
                elif calendar_query_type == "text_format":
                    _status_msg = get_text_format_message()
                elif calendar_query_type == "graduation":
                    _status_msg = get_graduation_retrieval_message()
                elif calendar_query_type is not None:
                    _status_msg = get_calendar_retrieval_message()
                else:
                    _status_msg = get_retrieval_start_message()

                yield cls.convert_data(
                    {
                        "type": "events",
                        "data": {"title": _status_msg},
                        "trace_id": trace_id,
                    }
                )

                # Resolve calendar data FIRST to avoid optimistic intro/skeleton
                # when requested data does not exist (e.g., unsupported year).
                if calendar_task is not None:
                    # Map pipeline stage names to user-facing status messages.
                    _STAGE_MSG_MAP = {
                        "retrieval": get_calendar_retrieval_message,
                        "extraction": get_calendar_extraction_message,
                        "building": get_calendar_building_message,
                    }

                    try:
                        logger.info("Calendar-only path: awaiting pipeline before emitting UI...")
                        loop = asyncio.get_running_loop()
                        started_at = loop.time()
                        while True:
                            remaining = CALENDAR_ONLY_TIMEOUT - (loop.time() - started_at)
                            if remaining <= 0:
                                raise asyncio.TimeoutError

                            try:
                                calendar_data = await asyncio.wait_for(
                                    asyncio.shield(calendar_task),
                                    timeout=min(1.0, remaining),
                                )
                                break
                            except asyncio.TimeoutError:
                                # Poll progress queue for stage updates while
                                # the pipeline is still running.
                                if calendar_progress_queue is not None:
                                    while not calendar_progress_queue.empty():
                                        try:
                                            stage = calendar_progress_queue.get_nowait()
                                            msg_fn = _STAGE_MSG_MAP.get(stage)
                                            if msg_fn is not None:
                                                yield cls.convert_data(
                                                    {
                                                        "type": "events",
                                                        "data": {"title": msg_fn()},
                                                        "trace_id": trace_id,
                                                    }
                                                )
                                        except asyncio.QueueEmpty:
                                            break
                                # Keep the stream active so frontend "thinking"
                                # state does not appear to freeze while extraction
                                # is still running.
                                yield cls.convert_text("")
                    except asyncio.TimeoutError:
                        # Calendar timed out — try RAG fallback so the
                        # student still gets a useful answer.
                        logger.warning("Calendar-only path timed out after %.0fs", CALENDAR_ONLY_TIMEOUT)
                        calendar_data = None
                        rag_used = False
                        if rag_fallback is not None:
                            try:
                                fallback_resp = await rag_fallback()
                                async for token in fallback_resp.async_response_gen():
                                    final_response += token
                                    yield cls.convert_text(token)
                                supplemental_source_nodes = list(
                                    getattr(fallback_resp, "source_nodes", []) or []
                                )
                                rag_used = True
                            except Exception as rag_err:
                                logger.error("RAG fallback also failed: %s", rag_err)
                        if not rag_used:
                            fallback_msg = "I couldn't load the academic calendar right now. Please try again."
                            final_response = fallback_msg
                            for chunk in cls._iter_text_chunks(fallback_msg):
                                yield cls.convert_text(chunk)
                                await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)
                            yield cls.convert_data(
                                {
                                    "type": "calendar_error",
                                    "data": {"reason": "timeout"},
                                    "trace_id": trace_id,
                                }
                            )
                    except Exception as exc:
                        # Calendar crashed — same fallback logic.
                        logger.error("Calendar-only path error: %s", exc, exc_info=True)
                        calendar_data = None
                        rag_used = False
                        if rag_fallback is not None:
                            try:
                                fallback_resp = await rag_fallback()
                                async for token in fallback_resp.async_response_gen():
                                    final_response += token
                                    yield cls.convert_text(token)
                                supplemental_source_nodes = list(
                                    getattr(fallback_resp, "source_nodes", []) or []
                                )
                                rag_used = True
                            except Exception as rag_err:
                                logger.error("RAG fallback also failed: %s", rag_err)
                        if not rag_used:
                            fallback_msg = "I couldn't load the academic calendar right now. Please try again."
                            final_response = fallback_msg
                            for chunk in cls._iter_text_chunks(fallback_msg):
                                yield cls.convert_text(chunk)
                                await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)
                            yield cls.convert_data(
                                {
                                    "type": "calendar_error",
                                    "data": {"reason": "error"},
                                    "trace_id": trace_id,
                                }
                            )

                    if isinstance(calendar_data, dict) and calendar_data.get("__calendar_error_reason") == "unsupported_year":
                        requested_year = calendar_data.get("requestedYear")
                        available_years = calendar_data.get("availableYears") or []
                        calendar_link = f"For more information, visit the [Academic Calendar]({ACADEMIC_CALENDAR_URL})."
                        if available_years:
                            years_text = ", ".join(str(y) for y in available_years)
                            message = (
                                f"I don't have verified academic calendar dates for {requested_year} yet. "
                                f"I currently have official dates for: {years_text}. "
                                f"{calendar_link}"
                            )
                        else:
                            message = (
                                f"I don't have verified academic calendar dates for {requested_year} yet. "
                                f"{calendar_link}"
                            )
                        final_response = message
                        for chunk in cls._iter_text_chunks(message):
                            yield cls.convert_text(chunk)
                            await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)
                        yield cls.convert_data(
                            {
                                "type": "calendar_error",
                                "data": {"reason": "unsupported_year"},
                                "trace_id": trace_id,
                            }
                        )
                    elif isinstance(calendar_data, dict):
                        if calendar_intro:
                            final_response = calendar_intro
                            for chunk in cls._iter_text_chunks(calendar_intro):
                                yield cls.convert_text(chunk)
                                await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)

                        for patch in _build_calendar_patches(calendar_data, trace_id):
                            yield patch

                        post_card_text = str(calendar_data.get("postCardText") or "").strip()
                        if post_card_text:
                            final_response = (
                                f"{final_response}\n\n{post_card_text}"
                                if final_response
                                else post_card_text
                            )
                            for chunk in cls._iter_text_chunks(f"\n\n{post_card_text}"):
                                yield cls.convert_text(chunk)
                                await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)

                        if supplemental_text_pipeline is not None:
                            try:
                                supplemental_payload = (
                                    await supplemental_text_pipeline(calendar_data) or {}
                                )
                                extra_text = str(
                                    supplemental_payload.get("text") or ""
                                ).strip()
                                supplemental_source_nodes = list(
                                    supplemental_payload.get("source_nodes") or []
                                )
                            except Exception as e:
                                logger.warning(
                                    "Secondary text pipeline failed: %s",
                                    e,
                                )
                                extra_text = ""
                                supplemental_source_nodes = []

                            if extra_text:
                                final_response = (
                                    f"{final_response}\n\n{extra_text}"
                                    if final_response
                                    else extra_text
                                )
                                for chunk in cls._iter_text_chunks(f"\n\n{extra_text}"):
                                    yield cls.convert_text(chunk)
                                    await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)
                    elif calendar_data is None and not final_response:
                        fallback = "I couldn't find calendar data for that request."
                        final_response = fallback
                        for chunk in cls._iter_text_chunks(fallback):
                            yield cls.convert_text(chunk)
                            await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)
                        yield cls.convert_data(
                            {
                                "type": "calendar_error",
                                "data": {"reason": "no_data"},
                                "trace_id": trace_id,
                            }
                        )
                else:
                    final_response = calendar_intro
                    for chunk in cls._iter_text_chunks(calendar_intro):
                        yield cls.convert_text(chunk)
                        await asyncio.sleep(TYPEWRITER_CHUNK_DELAY)

                event_handler.is_done = True

                date_spans = extract_date_spans(final_response, user_language)
                if date_spans:
                    yield cls.convert_data(
                        {
                            "type": "date_spans",
                            "data": {
                                "phrases": date_spans,
                                "language": user_language,
                            },
                            "trace_id": trace_id,
                        }
                    )

                # Yield source nodes (empty for calendar mode)
                yield cls.convert_data(
                    {
                        "type": "sources",
                        "data": {
                            "nodes": [
                                SourceNodes.from_source_node(node).model_dump()
                                for node in supplemental_source_nodes
                            ]
                        },
                        "trace_id": trace_id,
                    }
                )

            else:
                # ---- Normal RAG path ----
                if emit_initial_status:
                    yield cls.convert_data(
                        {
                            "type": "events",
                            "data": {"title": get_retrieval_start_message()},
                            "trace_id": trace_id,
                        }
                    )

                combine = stream.merge(
                    _chat_response_generator(), _event_generator()
                )
                async with combine.stream() as streamer:
                    async for output in streamer:
                        yield output

                        if await request.is_disconnected():
                            break
        finally:
            # Ensure the event stream can terminate even if the client disconnects early.
            event_handler.is_done = True
            if response_task is not None and not response_task.done():
                response_task.cancel()
            if calendar_task is not None and not calendar_task.done():
                calendar_task.cancel()
            if on_stream_end is not None:
                await on_stream_end(final_response)


async def _resolve_calendar_patches(
    calendar_task: asyncio.Task,
    trace_id: str | None,
) -> list[str]:
    """
    Await the calendar pipeline task and return progressive streaming patches.

    Returns a list of pre-formatted Vercel stream strings (each is a complete
    ``8:[...]\\n`` line) to be yielded by the content generator.
    """
    patches: list[str] = []

    try:
        logger.info("_resolve_calendar_patches: awaiting pipeline task...")
        calendar_data = await asyncio.wait_for(calendar_task, timeout=CALENDAR_PIPELINE_TIMEOUT)
        logger.info(f"_resolve_calendar_patches: pipeline returned, data is {'present' if calendar_data else 'None'}")
    except asyncio.TimeoutError:
        logger.warning("Calendar pipeline timed out")
        patches.append(
            VercelStreamResponse.convert_data(
                {"type": "calendar_error", "data": {"reason": "timeout"}, "trace_id": trace_id}
            )
        )
        return patches
    except Exception as e:
        logger.error(f"Calendar pipeline error: {e}", exc_info=True)
        patches.append(
            VercelStreamResponse.convert_data(
                {"type": "calendar_error", "data": {"reason": "error"}, "trace_id": trace_id}
            )
        )
        return patches

    if isinstance(calendar_data, dict) and calendar_data.get("__calendar_error_reason") == "unsupported_year":
        requested_year = calendar_data.get("requestedYear")
        available_years = calendar_data.get("availableYears") or []
        if available_years:
            years_text = ", ".join(str(y) for y in available_years)
            message = (
                f" I don't have verified academic calendar dates for {requested_year} yet. "
                f"I currently have official dates for: {years_text}."
            )
        else:
            message = (
                f" I don't have verified academic calendar dates for {requested_year} yet."
            )

        patches.append(VercelStreamResponse.convert_text(message))
        patches.append(
            VercelStreamResponse.convert_data(
                {
                    "type": "calendar_error",
                    "data": {"reason": "unsupported_year"},
                    "trace_id": trace_id,
                }
            )
        )
        return patches

    if calendar_data is None:
        logger.warning("Calendar pipeline returned None — no card will be rendered")
        patches.append(
            VercelStreamResponse.convert_data(
                {"type": "calendar_error", "data": {"reason": "no_data"}, "trace_id": trace_id}
            )
        )
        return patches

    patches.extend(_build_calendar_patches(calendar_data, trace_id))
    return patches


def _build_calendar_patches(
    calendar_data: dict,
    trace_id: str | None,
) -> list[str]:
    patches: list[str] = []

    # 1) Skeleton — triggers the animated card outline
    patches.append(
        VercelStreamResponse.convert_data(
            {
                "type": "calendar_skeleton",
                "data": {"cardType": calendar_data.get("type", "block")},
                "trace_id": trace_id,
            }
        )
    )

    # 2) Header — title, subtitle, status badge
    patches.append(
        VercelStreamResponse.convert_data(
            {
                "type": "calendar_header",
                "data": {
                    "title": calendar_data.get("title", ""),
                    "subtitle": calendar_data.get("subtitle", ""),
                    "status": calendar_data.get("status", "upcoming"),
                    "type": calendar_data.get("type", "block"),
                },
                "trace_id": trace_id,
            }
        )
    )

    # 3) Spotlight — most urgent/important event
    if calendar_data.get("spotlight"):
        patches.append(
            VercelStreamResponse.convert_data(
                {
                    "type": "calendar_spotlight",
                    "data": calendar_data["spotlight"],
                    "trace_id": trace_id,
                }
            )
        )

    # 4) Timeline — event rows + tabs
    patches.append(
        VercelStreamResponse.convert_data(
            {
                "type": "calendar_timeline",
                "data": {
                    "events": calendar_data.get("events", []),
                    "tabs": calendar_data.get("tabs"),
                },
                "trace_id": trace_id,
            }
        )
    )

    # 5) Footer — source link, suggested questions, footnote
    patches.append(
        VercelStreamResponse.convert_data(
            {
                "type": "calendar_footer",
                "data": {
                    "sourceUrl": calendar_data.get("sourceUrl", ""),
                    "suggestedQuestions": calendar_data.get("suggestedQuestions", []),
                    "footnote": calendar_data.get("footnote"),
                    "textFormatOffer": "Should I list these dates in text format instead?",
                },
                "trace_id": trace_id,
            }
        )
    )

    return patches
