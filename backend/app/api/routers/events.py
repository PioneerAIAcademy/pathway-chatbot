import json
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
from llama_index.core.callbacks.base import BaseCallbackHandler
from llama_index.core.callbacks.schema import CBEventType
from llama_index.core.tools.types import ToolOutput
from pydantic import BaseModel
from app.api.routers.message_variations import (
    get_retrieval_start_message,
    get_query_message,
    get_synthesize_message,
    get_reranking_message,
    get_llm_message,
)


logger = logging.getLogger(__name__)


class CallbackEvent(BaseModel):
    event_type: CBEventType
    payload: Optional[Dict[str, Any]] = None
    event_id: str = ""
    phase: str = "start"  # start | end

    def get_retrieval_message(self) -> dict | None:
        if self.phase != "start":
            return None
        # Always show a non-numeric, user-friendly "in progress" message.
        # Do not surface counts to the user.
        msg = get_retrieval_start_message()
        return {
            "type": "events",
            "data": {"title": msg},
        }

    def get_query_message(self) -> dict | None:
        if self.phase != "start":
            return None
        msg = get_query_message()
        return {
            "type": "events",
            "data": {"title": msg},
        }

    def get_synthesize_message(self) -> dict | None:
        if self.phase != "start":
            return None
        msg = get_synthesize_message()
        return {
            "type": "events",
            "data": {"title": msg},
        }

    def get_llm_message(self) -> dict | None:
        if self.phase != "start":
            return None
        msg = get_llm_message()
        return {
            "type": "events",
            "data": {"title": msg},
        }

    def get_reranking_message(self) -> dict | None:
        if self.phase != "start":
            return None
        msg = get_reranking_message()
        return {
            "type": "events",
            "data": {"title": msg},
        }

    def get_tool_message(self) -> dict | None:
        func_call_args = self.payload.get("function_call")
        if func_call_args is not None and "tool" in self.payload:
            tool = self.payload.get("tool")
            return {
                "type": "events",
                "data": {
                    "title": f"Calling tool: {tool.name} with inputs: {func_call_args}",
                },
            }

    def _is_output_serializable(self, output: Any) -> bool:
        try:
            json.dumps(output)
            return True
        except TypeError:
            return False

    def get_agent_tool_response(self) -> dict | None:
        response = self.payload.get("response")
        if response is not None:
            sources = response.sources
            for source in sources:
                # Return the tool response here to include the toolCall information
                if isinstance(source, ToolOutput):
                    if self._is_output_serializable(source.raw_output):
                        output = source.raw_output
                    else:
                        output = source.content

                    return {
                        "type": "tools",
                        "data": {
                            "toolOutput": {
                                "output": output,
                                "isError": source.is_error,
                            },
                            "toolCall": {
                                "id": None,  # There is no tool id in the ToolOutput
                                "name": source.tool_name,
                                "input": source.raw_input,
                            },
                        },
                    }

    def to_response(self):
        try:
            match self.event_type:
                case "query":
                    return self.get_query_message()
                case "retrieve":
                    return self.get_retrieval_message()
                case "reranking":
                    return self.get_reranking_message()
                case "synthesize":
                    return self.get_synthesize_message()
                case "llm":
                    return self.get_llm_message()
                case "function_call":
                    return self.get_tool_message()
                case "agent_step":
                    return self.get_agent_tool_response()
                case _:
                    return None
        except Exception as e:
            logger.error(f"Error in converting event to response: {e}")
            return None


class EventCallbackHandler(BaseCallbackHandler):
    _aqueue: asyncio.Queue
    is_done: bool = False

    def __init__(
        self,
    ):
        """Initialize the base callback handler."""
        ignored_events = [
            CBEventType.CHUNKING,
            CBEventType.NODE_PARSING,
            CBEventType.EMBEDDING,
            CBEventType.TEMPLATING,
        ]
        super().__init__(ignored_events, ignored_events)
        self._aqueue = asyncio.Queue()

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> str:
        event = CallbackEvent(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            phase="start",
        )
        if event.to_response() is not None:
            self._aqueue.put_nowait(event)

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        event = CallbackEvent(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            phase="end",
        )
        if event.to_response() is not None:
            self._aqueue.put_nowait(event)

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        """No-op."""

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """No-op."""

    async def async_event_gen(self) -> AsyncGenerator[CallbackEvent, None]:
        while not self._aqueue.empty() or not self.is_done:
            try:
                yield await asyncio.wait_for(self._aqueue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                pass
