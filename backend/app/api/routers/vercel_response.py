import asyncio
import inspect
import json
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
    ):
        final_response = ""
        resolved_response: StreamingAgentChatResponse | None = None
        response_task: asyncio.Task[StreamingAgentChatResponse] | None = None
        if inspect.isawaitable(response):
            response_task = asyncio.create_task(response)
        else:
            resolved_response = response

        # Yield the text response
        async def _chat_response_generator():
            nonlocal final_response
            nonlocal resolved_response

            final_response = ""
            try:
                if resolved_response is None:
                    assert response_task is not None
                    resolved_response = await response_task

                async for token in resolved_response.async_response_gen():
                    final_response += token
                    yield cls.convert_text(token)
            except Exception as exc:
                event_handler.is_done = True
                yield cls.convert_error(str(exc))
                return

            
            # Generate questions that user might interested to (skip for security-blocked responses)
            if not skip_suggestions:
                conversation = chat_data.messages + [
                    Message(role="assistant", content=final_response, trace_id=trace_id)
                    # Message(role="assistant", content=final_response)
                ]
                questions = await NextQuestionSuggestion.suggest_next_questions(
                    conversation
                )
                if len(questions) > 0:
                    yield cls.convert_data(
                        {
                            "type": "suggested_questions",
                            "data": questions,
                            "trace_id": trace_id
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
            if emit_initial_status:
                yield cls.convert_data(
                    {
                        "type": "events",
                        "data": {"title": get_retrieval_start_message()},
                        "trace_id": trace_id,
                    }
                )

            combine = stream.merge(_chat_response_generator(), _event_generator())
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
            if on_stream_end is not None:
                await on_stream_end(final_response)
