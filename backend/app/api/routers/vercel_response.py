import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

from aiostream import stream
from fastapi import Request
from fastapi.responses import StreamingResponse
from llama_index.core.chat_engine.types import StreamingAgentChatResponse

from app.api.routers.events import EventCallbackHandler
from app.api.routers.message_variations import get_retrieval_start_message
from app.api.routers.models import ChatData, Message, SourceNodes
from app.api.services.suggestion import NextQuestionSuggestion
from app.utils.date_spans import extract_date_spans

logger = logging.getLogger("uvicorn")

# Timeout for the calendar pipeline (seconds).
# Pipeline involves: LLM tool-choice call + Pinecone retrieval + LLM extraction.
_CALENDAR_TIMEOUT = 45.0

# Calendar-only requests can legitimately take longer because the entire answer
# depends on retrieval + extraction. Keep this separate from mixed RAG path.
_CALENDAR_ONLY_TIMEOUT = 120.0

# Emit calendar patches after this many text tokens have streamed
_MIN_TOKENS_BEFORE_CALENDAR = 15


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
        )
        super().__init__(content=content, media_type="text/plain")

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
                            token_count >= _MIN_TOKENS_BEFORE_CALENDAR
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
                yield cls.convert_data(
                    {
                        "type": "events",
                        "data": {"title": get_retrieval_start_message()},
                        "trace_id": trace_id,
                    }
                )

                # Resolve calendar data FIRST to avoid optimistic intro/skeleton
                # when requested data does not exist (e.g., unsupported year).
                if calendar_task is not None:
                    try:
                        logger.info("Calendar-only path: awaiting pipeline before emitting UI...")
                        loop = asyncio.get_running_loop()
                        started_at = loop.time()
                        while True:
                            remaining = _CALENDAR_ONLY_TIMEOUT - (loop.time() - started_at)
                            if remaining <= 0:
                                raise asyncio.TimeoutError

                            try:
                                calendar_data = await asyncio.wait_for(
                                    asyncio.shield(calendar_task),
                                    timeout=min(1.0, remaining),
                                )
                                break
                            except asyncio.TimeoutError:
                                # Keep the stream active so frontend "thinking"
                                # state does not appear to freeze while extraction
                                # is still running.
                                yield cls.convert_text("")
                    except asyncio.TimeoutError:
                        fallback = "I couldn’t load the academic calendar right now. Please try again."
                        final_response = fallback
                        yield cls.convert_text(fallback)
                        yield cls.convert_data(
                            {
                                "type": "calendar_error",
                                "data": {"reason": "timeout"},
                                "trace_id": trace_id,
                            }
                        )
                        calendar_data = None
                    except Exception:
                        fallback = "I couldn’t load the academic calendar right now. Please try again."
                        final_response = fallback
                        yield cls.convert_text(fallback)
                        yield cls.convert_data(
                            {
                                "type": "calendar_error",
                                "data": {"reason": "error"},
                                "trace_id": trace_id,
                            }
                        )
                        calendar_data = None

                    if isinstance(calendar_data, dict) and calendar_data.get("__calendar_error_reason") == "unsupported_year":
                        requested_year = calendar_data.get("requestedYear")
                        available_years = calendar_data.get("availableYears") or []
                        if available_years:
                            years_text = ", ".join(str(y) for y in available_years)
                            message = (
                                f"I don’t have verified academic calendar dates for {requested_year} yet. "
                                f"I currently have official dates for: {years_text}."
                            )
                        else:
                            message = (
                                f"I don’t have verified academic calendar dates for {requested_year} yet."
                            )
                        final_response = message
                        yield cls.convert_text(message)
                        yield cls.convert_data(
                            {
                                "type": "calendar_error",
                                "data": {"reason": "unsupported_year"},
                                "trace_id": trace_id,
                            }
                        )
                    elif isinstance(calendar_data, dict):
                        final_response = calendar_intro
                        yield cls.convert_text(calendar_intro)
                        for patch in _build_calendar_patches(calendar_data, trace_id):
                            yield patch
                    elif calendar_data is None and not final_response:
                        fallback = "I couldn’t find calendar data for that request."
                        final_response = fallback
                        yield cls.convert_text(fallback)
                        yield cls.convert_data(
                            {
                                "type": "calendar_error",
                                "data": {"reason": "no_data"},
                                "trace_id": trace_id,
                            }
                        )
                else:
                    final_response = calendar_intro
                    yield cls.convert_text(calendar_intro)

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
                        "data": {"nodes": []},
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
        calendar_data = await asyncio.wait_for(calendar_task, timeout=_CALENDAR_TIMEOUT)
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
                f" I don’t have verified academic calendar dates for {requested_year} yet. "
                f"I currently have official dates for: {years_text}."
            )
        else:
            message = (
                f" I don’t have verified academic calendar dates for {requested_year} yet."
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
                    "textFormatOffer": "Would you like me to list these dates in text format instead?",
                },
                "trace_id": trace_id,
            }
        )
    )

    return patches
