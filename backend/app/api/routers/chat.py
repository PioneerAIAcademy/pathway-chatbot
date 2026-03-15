import logging
import hashlib
import time
import re
from typing import Tuple, List, Dict, Any, Optional
from collections import defaultdict
import traceback
import sys
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Security, UploadFile, status
from llama_index.core.chat_engine.types import BaseChatEngine, NodeWithScore
from llama_index.core.llms import MessageRole
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.auth import verify_api_key

from app.api.routers.events import EventCallbackHandler
from app.api.routers.models import (
    ChatData,
    Message,
    Result,
    SourceNodes,
    ThumbsRequest,
)
from app.api.routers.vercel_response import VercelStreamResponse
from app.engine import get_chat_engine
from app.engine.query_filter import generate_filters
from app.security import InputValidator, SecurityValidationError, RiskLevel
from app.utils.localization import LocalizationManager
from langfuse.decorators import langfuse_context, observe
from app.http_client import get_http_client
from app.langfuse import langfuse
from app.utils.geo_ip import get_geo_data
from app.tools.calendar import (
    build_calendar_intro,
    build_calendar_text_response,
    build_initial_calendar_metadata,
    detect_calendar_intent_via_llm,
    localize_calendar_intro,
    run_calendar_pipeline,
)
from app.tools.calendar.router import (
    _find_original_calendar_question,
    _has_recent_calendar_response,
    _is_calendar_retry,
    _parse_prior_calendar_context,
)
from app.tools.calendar.schema import CalendarToolArgs
import os

chat_router = r = APIRouter()

logger = logging.getLogger("uvicorn")

# Text-format detection is now LLM-based (see _is_text_format_request).
# The old regex pattern has been removed to support 100+ languages.


def _is_calendar_secondary_text_enabled() -> bool:
    value = os.getenv("CALENDAR_SECONDARY_TEXT_ENABLED", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


class _StaticResponse:
    def __init__(self, message: str):
        self.response = message
        self.source_nodes: list[Any] = []

    async def async_response_gen(self):
        yield self.response


async def _is_text_format_request(message: str) -> bool:
    """Detect if the user is asking for calendar dates in plain text format.

    Uses an LLM call to support any language (100+), not regex.
    Examples: "text format", "list the dates as text", "formato de texto",
    "テキスト形式で表示して", "I don't want the card, just text".
    """
    if not message or len(message.strip()) < 3:
        return False

    prompt = (
        "Does this user message request calendar dates in plain text format "
        "(as opposed to a visual card/widget)? This includes requests like "
        "'text format', 'list the dates', 'show as text', 'just text please', "
        "'I don't want the card', 'list these dates in text format', "
        "'summarize in text'. The message may be in ANY language.\n\n"
        f"Message: \"{message}\"\n\n"
        "Reply with exactly one word: YES or NO."
    )

    try:
        from llama_index.core.settings import Settings as LISettings
        response = await LISettings.llm.acomplete(prompt)
        answer = (response.text or "").strip().upper()
        is_text = answer.startswith("YES")
        logger.info(
            "Text-format detection: message=%r → %s",
            message[:80], "TEXT_FORMAT" if is_text else "not text format",
        )
        return is_text
    except Exception as e:
        logger.error("Text-format detection LLM call failed: %s", e)
        return False


async def _resolve_text_format_followup_args(
    message: str,
    chat_history: List[Any],
) -> Optional[CalendarToolArgs]:
    if not await _is_text_format_request(message):
        return None

    prior_intro = _has_recent_calendar_response(chat_history)
    if not prior_intro:
        return None

    scoped = _parse_prior_calendar_context(prior_intro)
    if not scoped.get("query_type"):
        return None

    args_payload = {
        "query_type": scoped.get("query_type"),
        "scope": scoped.get("scope") or "term",
        "season": scoped.get("season"),
        "year": scoped.get("year"),
        "block_number": scoped.get("block_number"),
    }
    return CalendarToolArgs(**args_payload)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


def _log_exception_trace():
    """
    Log the full exception traceback when an exception occurs.
    Should be called within an except block.
    """
    exc_info = sys.exc_info()
    if exc_info[0] is not None:  # If there's an active exception
        exc_trace = "".join(traceback.format_exception(*exc_info))
        logger.error(f"Exception traceback:\n{exc_trace}")


# streaming endpoint - delete if not needed
@r.post("")
@limiter.limit("300/minute")
@observe(as_type="generation")
async def chat(
    request: Request,
    data: ChatData,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key),
):
    risk_level = None
    security_details = {}
    chat_engine = None
    streaming_response_returned = False

    try:
        last_message_content = data.get_last_message_content()
        
        # Get real client IP and geo data BEFORE security validation
        # This ensures we capture IP/location for both blocked and allowed requests
        client_ip = _get_client_ip(request)
        
        geo_data = await get_geo_data(client_ip)
        
        # Security validation - primary defense with contextual responses
        is_suspicious, blocked_message, security_details = await InputValidator.validate_input_security_async(last_message_content)
        
        # If input is blocked, return the security message as a normal response
        if blocked_message:
            # Detect user's language for consistent blocked response localization
            user_language = LocalizationManager.detect_language(last_message_content)
            role = data.data.get("role", "missionary") if data.data else "missionary"

            # Get session ID and device ID from headers
            session_id = request.headers.get("X-Session-ID", request.headers.get("X-Session-Id"))
            device_id = request.headers.get("X-Device-ID")

            # Create tags for blocked request
            blocked_tags = [
                f"language:{user_language}",
                f"role:{role}",
                "feature:chat",
                f"security:risk_{security_details.get('risk_level', 'UNKNOWN').lower()}"
            ]

            # Log security event for monitoring
            logger.warning(
                f"Security validation blocked suspicious input - "
                f"Risk: {security_details.get('risk_level', 'UNKNOWN')}, "
                f"Reason: {security_details.get('reason', 'unknown')}"
            )

            # Update trace with structured fields (trace-level)
            langfuse_context.update_current_trace(
                name="chat",
                input=last_message_content,
                output=blocked_message,
                session_id=session_id,
                user_id=device_id,  # Use device fingerprint as user_id for tracking
                tags=blocked_tags,
                release=os.getenv("ENVIRONMENT", "development"),
                metadata={
                    "security_validation": {
                        "blocked": True,
                        "risk_level": security_details.get("risk_level", "UNKNOWN"),
                        "reason": security_details.get("reason", "security_validation_failed"),
                        "details": security_details
                    },
                    "geo_data": geo_data,
                    "user_language": user_language,
                    "role": role
                }
            )

            # Update observation with WARNING level
            langfuse_context.update_current_observation(
                level="WARNING",
                status_message=f"Blocked: {security_details.get('reason', 'security_validation_failed')}"
            )

            # Flush Langfuse trace before streaming response to ensure data is captured
            langfuse.flush()
            
            # Return blocked message as normal response (not HTTP error)
            from llama_index.core.llms import MessageRole
            blocked_response = Message(
                role=MessageRole.ASSISTANT, 
                content=blocked_message
            )
            
            # Create a simple response structure for blocked content
            class BlockedResponse:
                def __init__(self, message):
                    self.response = message
                    self.source_nodes = []
                
                async def async_response_gen(self):
                    yield self.response
            
            blocked_chat_response = BlockedResponse(blocked_message)

            return VercelStreamResponse(
                request,
                EventCallbackHandler(),
                blocked_chat_response,
                data,
                skip_suggestions=True,
                user_language=user_language,
                emit_initial_status=False,
            )
        
        # Sanitize allowed input as additional protection
        if is_suspicious and security_details.get("risk_level") == "LOW":
            last_message_content = InputValidator.sanitize_input(last_message_content)
        
        # Get the conversation history from incoming messages
        messages = data.get_history_messages()

        doc_ids = data.get_chat_document_ids()
        params = data.data or {}
        role = params.get("role", "missionary")
        filters = generate_filters(doc_ids, role)

        langfuse_input = (
            f"(ACMs Question): {last_message_content}"
            if role == "ACM"
            else last_message_content
        )

        # Detect user's language for consistent frontend localization
        user_language = LocalizationManager.detect_language(last_message_content)

        # Get session ID and device ID from headers
        session_id = request.headers.get("X-Session-ID", request.headers.get("X-Session-Id"))
        device_id = request.headers.get("X-Device-ID")

        # Create tags for successful request
        success_tags = [
            f"language:{user_language}",
            f"role:{role}",
            "feature:chat",
            "source:rag"
        ]

        # Add security tag based on validation
        if is_suspicious:
            success_tags.append(f"security:risk_{security_details.get('risk_level', 'LOW').lower()}")
        else:
            success_tags.append("security:clean")

        # Build security metadata
        security_metadata = {
            "input_validated": True,
            "is_suspicious": is_suspicious,
            "risk_level": security_details.get("risk_level", "NONE") if is_suspicious else "NONE"
        }
        if is_suspicious:
            security_metadata["details"] = security_details

        # Build clean metadata with only custom business data
        clean_metadata = {
            "security_validation": security_metadata,
            "geo_data": geo_data,
            "user_language": user_language,
            "role": role,
        }

        trace_id = langfuse_context.get_current_trace_id()

        # Update trace with structured fields (trace-level)
        langfuse_context.update_current_trace(
            name="chat",
            input=langfuse_input,
            session_id=session_id,
            user_id=device_id,  # Use device fingerprint as user_id for tracking
            tags=success_tags,
            release=os.getenv("ENVIRONMENT", "development"),
            metadata=clean_metadata
        )

        # Get model name from params or environment
        model_name = params.get("model", os.getenv("MODEL", "gpt-4o-mini"))

        # Update observation - tokens/costs are captured by Langfuse callback handler
        langfuse_context.update_current_observation(
            model=model_name,
            level="DEFAULT",
            status_message="Chat started"
        )

        event_handler = EventCallbackHandler()
        retrieval_metadata: dict[str, Any] = {}
        calendar_metadata: dict[str, Any] = {}

        # Pre-build the Pinecone index once so both the chat engine and
        # calendar pipeline share the same connection (avoids duplicate connect).
        from app.engine.index import get_index
        shared_index = get_index(params)

        # Calendar tool: LLM-based intent detection + Pinecone retrieval pipeline
        # Intent detection runs FIRST so the chat engine can be told to keep its
        # text response brief when a visual calendar card will be rendered.
        user_timezone = request.headers.get("X-Timezone", "UTC")
        calendar_args = None
        calendar_clarification = None
        calendar_text_followup = False
        calendar_skip_cache = False

        # If the user clicked "Try again" on a failed calendar card, the
        # frontend sends a canned retry message.  Resolve the original
        # question so every downstream consumer uses real calendar context.
        if _is_calendar_retry(last_message_content):
            original_q = _find_original_calendar_question(
                last_message_content, messages,
            )
            if original_q:
                logger.info(
                    "Calendar retry detected — using original question: %s",
                    original_q[:80],
                )
                last_message_content = original_q

        try:
            calendar_args, calendar_clarification, calendar_skip_cache = (
                await detect_calendar_intent_via_llm(
                    last_message_content,
                    user_timezone,
                    chat_history=messages,
                )
            )
        except Exception as e:
            logger.error(f"Calendar intent detection failed: {e}")

        if calendar_args is None and calendar_clarification is None:
            text_format_args = await _resolve_text_format_followup_args(
                last_message_content,
                messages,
            )
            if text_format_args is not None:
                calendar_args = text_format_args
                calendar_text_followup = True
                logger.info(
                    "Calendar text-format follow-up resolved from prior card: "
                    "query_type=%s block=%s season=%s year=%s",
                    calendar_args.query_type.value,
                    calendar_args.block_number,
                    calendar_args.season,
                    calendar_args.year,
                )

        if calendar_args is not None:
            logger.info(
                f"Calendar intent detected: {calendar_args.query_type.value}, "
                f"block={calendar_args.block_number}, season={calendar_args.season}"
            )
            calendar_metadata.update(build_initial_calendar_metadata(calendar_args))
            if calendar_text_followup:
                calendar_metadata["response_mode"] = "text_format"

        # Build the calendar pipeline that runs concurrently with the chat stream.
        # Intent detection is already done; this only does retrieval + extraction.
        async def _calendar_pipeline():
            """Runs concurrently with the main RAG stream."""
            nonlocal calendar_metadata
            card, pipeline_metadata = await run_calendar_pipeline(
                calendar_args,
                shared_index,
                user_query=last_message_content,
                user_language=user_language,
                chat_history=messages,
                skip_cache=calendar_skip_cache,
            )
            if pipeline_metadata:
                calendar_metadata.update(pipeline_metadata)
            if card is None and pipeline_metadata.get("pipeline_status") == "unsupported_year":
                return {
                    "__calendar_error_reason": "unsupported_year",
                    "requestedYear": pipeline_metadata.get("requested_year"),
                    "availableYears": pipeline_metadata.get("available_years_from_nodes", []),
                }
            return card

        async def _calendar_secondary_text_pipeline(calendar_data: dict) -> Optional[dict[str, Any]]:
            """Optional phase-2 mixed-intent follow-up using normal RAG.

            Runs only when calendar pipeline marks rag_context with sufficient confidence
            and feature flag is enabled.
            """
            if not _is_calendar_secondary_text_enabled():
                return None

            mode = str(calendar_data.get("secondaryTextMode") or "").strip().lower()
            confidence = float(calendar_data.get("secondaryTextConfidence") or 0.0)
            if mode != "rag_context" or confidence < 0.75:
                return None

            rag_engine = None
            try:
                rag_engine = get_chat_engine(filters=filters, params=params)
                followup_prompt = (
                    "A calendar card is already displayed showing relevant dates and deadlines. "
                    "Now provide a helpful text answer to the user's question in 2-4 concise sentences. "
                    "If the question is about a calendar item (e.g. a deadline), explain what it means, "
                    "what happens if it's missed, and any steps the student should take. "
                    "If the question has a non-calendar component, answer that part instead. "
                    "Do NOT repeat the dates already shown in the card. "
                    "Avoid second-person pronouns such as 'you' and 'your'. "
                    "Refer to students or missionaries in the third person instead.\n\n"
                    f"User message: {last_message_content}"
                )
                response = await rag_engine.achat(followup_prompt, messages)
                text = str(getattr(response, "response", "") or "").strip()
                if not text:
                    return None

                followup_nodes = list(getattr(response, "source_nodes", []) or [])
                if followup_nodes:
                    try:
                        retrieval_metadata["secondary_retrieved_docs"] = "\n\n".join(
                            [
                                f"node_id: {idx+1}\n{node.metadata.get('url', '')}\n{node.text}"
                                for idx, node in enumerate(followup_nodes)
                            ]
                        )
                        retrieval_metadata["secondary_retrieved_docs_count"] = len(
                            followup_nodes
                        )
                    except Exception as retrieval_error:
                        logger.warning(
                            "Failed to build secondary retrieved docs metadata: %s",
                            retrieval_error,
                        )

                calendar_metadata["secondary_text_followup"] = {
                    "mode": mode,
                    "confidence": confidence,
                    "status": "generated",
                }
                return {"text": text, "source_nodes": followup_nodes}
            except Exception as e:
                logger.warning("Secondary RAG follow-up failed: %s", e)
                calendar_metadata["secondary_text_followup"] = {
                    "mode": mode,
                    "confidence": confidence,
                    "status": "error",
                    "error": str(e),
                }
                return None
            finally:
                if rag_engine is not None:
                    try:
                        rag_engine.reset()
                    except Exception:
                        pass

        async def _on_stream_end(final_response: str) -> None:
            # Update trace output after streaming finishes (or client disconnects).
            try:
                final_tags = [
                    tag
                    for tag in success_tags
                    if not tag.startswith("source:") and not tag.startswith("calendar:")
                ]

                if retrieval_metadata:
                    clean_metadata.update(retrieval_metadata)

                if calendar_metadata:
                    clean_metadata["calendar_pipeline"] = calendar_metadata
                    final_tags.append("source:calendar")
                    final_tags.append("calendar:detected")
                    if calendar_metadata.get("pipeline_status") == "success":
                        final_tags.append("calendar:success")
                    else:
                        final_tags.append("calendar:error")
                else:
                    final_tags.append("source:rag")

                langfuse.trace(id=trace_id).update(
                    output=final_response,
                    metadata=clean_metadata,
                    tags=final_tags,
                )
                langfuse.flush()
            except Exception as langfuse_error:
                logger.error(f"Failed to update Langfuse trace output: {langfuse_error}")

            # Ensure chat engine memory is cleaned up after the request completes.
            if chat_engine is not None:
                try:
                    chat_engine.reset()
                    logger.debug("Chat engine memory buffer cleared")
                except Exception as cleanup_error:
                    logger.error(f"Failed to reset chat engine: {cleanup_error}")

        # When calendar intent is detected, skip the RAG engine entirely.
        # The card shows the data; we just need a short intro sentence.
        if calendar_clarification and calendar_args is None:
            streaming_response_returned = True
            return VercelStreamResponse(
                request,
                event_handler,
                _StaticResponse(calendar_clarification),
                data,
                trace_id=trace_id,
                user_language=user_language,
                skip_suggestions=True,
                on_stream_end=_on_stream_end,
                emit_initial_status=False,
            )

        if calendar_text_followup and calendar_args is not None:
            card, pipeline_metadata = await run_calendar_pipeline(
                calendar_args,
                shared_index,
                user_query=last_message_content,
                user_language=user_language,
                chat_history=messages,
            )
            if pipeline_metadata:
                calendar_metadata.update(pipeline_metadata)

            if card is not None:
                text_only_response = build_calendar_text_response(card)
            elif pipeline_metadata.get("pipeline_status") == "unsupported_year":
                requested_year = pipeline_metadata.get("requested_year")
                text_only_response = (
                    f"I don't have verified academic calendar dates for {requested_year} yet. "
                    "Please refer to the Academic Calendar source for confirmed dates."
                )
            else:
                text_only_response = (
                    "I couldn't find the calendar dates to list in text format right now."
                )

            streaming_response_returned = True
            return VercelStreamResponse(
                request,
                event_handler,
                _StaticResponse(text_only_response),
                data,
                trace_id=trace_id,
                user_language=user_language,
                skip_suggestions=True,
                on_stream_end=_on_stream_end,
                emit_initial_status=False,
            )

        calendar_intro: Optional[str] = None
        if calendar_args is not None:
            calendar_intro = build_calendar_intro(calendar_args)
            calendar_intro = await localize_calendar_intro(
                calendar_intro,
                user_language,
                last_message_content,
            )

        async def _get_response() -> Any:
            nonlocal chat_engine
            # Skip RAG when a calendar card will be rendered — the card
            # already shows all dates/deadlines from Pinecone.
            if calendar_intro is not None:
                return None

            logger.info(
                f"Creating chat engine with filters: {str(filters)}",
            )
            chat_engine = get_chat_engine(filters=filters, params=params)
            chat_engine.callback_manager.handlers.append(event_handler)  # type: ignore

            response = await chat_engine.astream_chat(last_message_content, messages)

            try:
                retrieved = "\n\n".join(
                    [
                        f"node_id: {idx+1}\n{node.metadata.get('url', '')}\n{node.text}"
                        for idx, node in enumerate(response.source_nodes)
                    ]
                )
                retrieval_metadata.update(
                    {
                        "retrieved_docs": retrieved,
                        "retrieved_docs_count": len(response.source_nodes),
                    }
                )
            except Exception as retrieval_error:
                logger.error(f"Failed to build retrieved docs metadata: {retrieval_error}")

            return response

        async def _rag_fallback_for_calendar():
            """If calendar pipeline times out, answer via normal RAG."""
            engine = get_chat_engine(filters=filters, params=params)
            engine.callback_manager.handlers.append(event_handler)
            return await engine.astream_chat(last_message_content, messages)

        streaming_response_returned = True

        # Determine the calendar query type for status message selection
        _cal_query_type: Optional[str] = None
        if calendar_args is not None:
            if calendar_skip_cache:
                _cal_query_type = "pushback"
            else:
                _cal_query_type = calendar_args.query_type.value

        return VercelStreamResponse(
            request,
            event_handler,
            _get_response(),
            data,
            trace_id=trace_id,
            user_language=user_language,
            skip_suggestions=is_suspicious or (calendar_args is not None),
            on_stream_end=_on_stream_end,
            emit_initial_status=False,
            calendar_pipeline=_calendar_pipeline,
            calendar_intro=calendar_intro,
            supplemental_text_pipeline=_calendar_secondary_text_pipeline,
            rag_fallback=_rag_fallback_for_calendar,
            calendar_query_type=_cal_query_type,
        )
        # return VercelStreamResponse(request, event_handler, response, data, tokens)
    except Exception as e:
        logger.exception("Error in chat engine", exc_info=True)
        _log_exception_trace()

        # Track exception in Langfuse with ERROR level
        try:
            langfuse_context.update_current_observation(
                level="ERROR",
                status_message=f"Exception: {type(e).__name__} - {str(e)}"
            )
        except Exception as langfuse_error:
            logger.error(f"Failed to update Langfuse with error: {langfuse_error}")

        is_dev = os.getenv("ENVIRONMENT", "dev") == "dev"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in chat engine: {e}" if is_dev else "An error occurred. Please try again.",
        ) from e
    finally:
        # If we failed before returning a streaming response, clean up immediately.
        if not streaming_response_returned and chat_engine is not None:
            try:
                chat_engine.reset()
                logger.debug("Chat engine memory buffer cleared")
            except Exception as cleanup_error:
                logger.error(f"Failed to reset chat engine: {cleanup_error}")


# non-streaming endpoint - delete if not needed
@r.post("/request")
@limiter.limit("10/minute")
@observe()
async def chat_request(
    request: Request,
    data: ChatData,
    api_key: str = Depends(verify_api_key),
) -> Result:
    risk_level = None
    security_details = {}
    
    try:
        last_message_content = data.get_last_message_content()
        
        # Get real client IP and geo data BEFORE security validation
        # This ensures we capture IP/location for both blocked and allowed requests
        client_ip = _get_client_ip(request)
        
        geo_data = await get_geo_data(client_ip)
        
        # Security validation - primary defense with contextual responses
        is_suspicious, blocked_message, security_details = await InputValidator.validate_input_security_async(last_message_content)
        
        # If input is blocked, return the security message as a normal response
        if blocked_message:
            # Log security event for monitoring
            logger.warning(
                f"Security validation blocked suspicious input - "
                f"Risk: {security_details.get('risk_level', 'UNKNOWN')}, "
                f"Reason: {security_details.get('reason', 'unknown')}"
            )
            
            # Detect user's language for consistent blocked response localization
            user_language = LocalizationManager.detect_language(last_message_content)
            
            # Send blocked request to Langfuse with security metadata and geo_data
            langfuse_context.update_current_trace(
                input=last_message_content,
                output=blocked_message,
                metadata={
                    "security_blocked": True,
                    "risk_level": security_details.get("risk_level", "UNKNOWN"),
                    "security_details": security_details,
                    "blocked_reason": security_details.get("reason", "security_validation_failed"),
                    "user_language": user_language,
                    **geo_data
                }
            )
            
            # Flush Langfuse trace before returning to ensure data is captured
            langfuse.flush()
            
            # Return blocked message as normal response
            return Result(
                result=Message(
                    role=MessageRole.ASSISTANT, 
                    content=blocked_message
                ),
                nodes=SourceNodes.from_source_nodes([])  # No source nodes for blocked content
            )
        
        # Sanitize allowed input as additional protection
        if is_suspicious and security_details.get("risk_level") == "LOW":
            last_message_content = InputValidator.sanitize_input(last_message_content)
        
        # Get the conversation history from incoming messages
        messages = data.get_history_messages()

        doc_ids = data.get_chat_document_ids()
        params = data.data or {}
        role = params.get("role", "missionary")
        filters = generate_filters(doc_ids, role)
        logger.info(
            f"Creating chat engine with filters: {str(filters)}",
        )
        chat_engine = get_chat_engine(filters=filters, params=params)

        response = await chat_engine.achat(last_message_content, messages)

        retrieved = "\n\n".join(
            [
                f"node_id: {idx+1}\n{node.metadata['url']}\n{node.text}"
                for idx, node in enumerate(response.source_nodes)
            ]
        )

        langfuse_input = (
            f"(ACMs Question): {last_message_content}"
            if role == "ACM"
            else last_message_content
        )
        
        # Enhanced metadata with security information
        security_metadata = {
            "input_validated": True,
            "input_sanitized": True
        }
        
        # Only add risk classification for suspicious inputs
        if is_suspicious:
            security_metadata.update({
                "is_suspicious": True,
                "risk_level": security_details.get("risk_level", "LOW"),
                "security_details": security_details
            })
        else:
            security_metadata["is_suspicious"] = False
        
        # Detect user's language for consistent frontend localization
        user_language = LocalizationManager.detect_language(last_message_content)
        
        enhanced_metadata = {
            "nodes": retrieved,
            "security_validation": security_metadata,
            "user_language": user_language,
            **geo_data
        }
        
        # Set the input, output and metadata of Langfuse
        langfuse_context.update_current_trace(
            input=langfuse_input,
            output=response.response,
            metadata=enhanced_metadata,
        )

        # Get the trace_id of Langfuse
        trace_id = langfuse_context.get_current_trace_id()
        logger.info(f"We got the trace id to be : {trace_id}")

        # Delete the chat_history from the chat_engine
        chat_engine.reset()

        return Result(
            result=Message(
                role=MessageRole.ASSISTANT, content=response.response, trace_id=trace_id
            ),
            nodes=SourceNodes.from_source_nodes(response.source_nodes),
        )
    except Exception as e:
        logger.exception("Error in chat_request", exc_info=True)
        _log_exception_trace()
        is_dev = os.getenv("ENVIRONMENT", "dev") == "dev"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in chat engine: {e}" if is_dev else "An error occurred. Please try again.",
        ) from e


@r.post("/thumbs_request")
@limiter.limit("30/minute")
async def thumbs_request(
    request: Request,
    thumbs_data: ThumbsRequest,
    api_key: str = Depends(verify_api_key),
):
    trace_id = thumbs_data.trace_id
    # Normalize values for comparison, but keep a canonical "Good"/"Bad" for display consistency.
    value_raw = (thumbs_data.value or "").strip()
    value_norm = value_raw.lower()
    if value_norm == "good":
        value = "Good"
    elif value_norm == "bad":
        value = "Bad"
    elif value_norm == "":
        value = ""
    else:
        value = value_raw

    # IMPORTANT:
    # Langfuse "score" updates are upserts by `id`. If we don't explicitly send a new `comment`,
    # the previous comment can remain attached to the score. When users switch from BAD -> GOOD
    # (or clear their rating), we should clear any previously submitted comment.
    comment = thumbs_data.comment or ""
    if value_norm != "bad":
        comment = ""
    score_id = f'{trace_id}_feedback'

    # Record the user feedback score
    langfuse.score(
        id=score_id,
        trace_id=trace_id,
        name="user_feedback",
        data_type="CATEGORICAL",
        value=value,
        comment=comment,
    )

    # If feedback is negative (thumbs down), update trace with DEBUG level
    if value_norm == "bad":
        try:
            # Fetch the trace and update its level to DEBUG for negative feedback
            trace = langfuse.get_trace(trace_id)
            if trace:
                # Note: We can't update past observations directly via API
                # The DEBUG level should be set at observation creation time
                # This score will be visible in Langfuse UI for filtering
                logger.info(f"Negative feedback received for trace {trace_id}")
        except Exception as e:
            logger.error(f"Failed to process negative feedback for trace {trace_id}: {e}")

    return {"feedback": value}


def _get_cloudinary_config() -> Tuple[str, str, str]:
    """
    Read Cloudinary config from either explicit vars or CLOUDINARY_URL.
    Supports:
      - CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET
      - CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>
    """
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()

    cloudinary_url = os.getenv("CLOUDINARY_URL", "").strip()
    if cloudinary_url and (not cloud_name or not api_key or not api_secret):
        parsed = urlparse(cloudinary_url)
        if parsed.scheme == "cloudinary":
            cloud_name = cloud_name or (parsed.hostname or "")
            api_key = api_key or (parsed.username or "")
            api_secret = api_secret or (parsed.password or "")

    return cloud_name, api_key, api_secret


async def _upload_screenshot_to_cloudinary(file: UploadFile) -> str:
    cloud_name, api_key, api_secret = _get_cloudinary_config()
    if not cloud_name or not api_key or not api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Screenshot uploads are not configured",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Screenshot must be an image file",
        )

    # Read bytes once (we need them both for size validation and upload).
    content = await file.read()
    max_bytes = 10 * 1024 * 1024  # 10MB
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Screenshot too large (max 10MB)",
        )

    folder = "missionary-assistant/feedback"
    timestamp = int(time.time())

    # Cloudinary signature: sha1(sorted_params + api_secret)
    params = {"folder": folder, "timestamp": timestamp}
    signature_base = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hashlib.sha1((signature_base + api_secret).encode("utf-8")).hexdigest()

    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    data = {
        "api_key": api_key,
        "timestamp": str(timestamp),
        "signature": signature,
        "folder": folder,
    }
    files = {
        "file": (
            file.filename or "screenshot",
            content,
            file.content_type or "application/octet-stream",
        )
    }

    client = get_http_client()
    resp = await client.post(url, data=data, files=files)
    if resp.status_code >= 400:
        logger.error(
            "Cloudinary upload failed (%s): %s",
            resp.status_code,
            resp.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Screenshot upload failed",
        )

    payload = resp.json()
    screenshot_url = payload.get("secure_url") or payload.get("url") or ""
    if not screenshot_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Screenshot upload failed",
        )
    return screenshot_url


@r.post("/feedback/general")
@limiter.limit("5/minute")
async def general_feedback(
    request: Request,
    feedback: str = Form(...),
    screenshot: Optional[UploadFile] = File(None),
    api_key: str = Depends(verify_api_key),
):
    """
    General user feedback not tied to a specific chat message.
    Optionally accepts a screenshot image which is stored in Cloudinary.
    """
    feedback_text = (feedback or "").strip()
    if not feedback_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="feedback is required",
        )

    session_id = request.headers.get("X-Session-ID", request.headers.get("X-Session-Id"))
    device_id = request.headers.get("X-Device-ID")

    client_ip = _get_client_ip(request)

    geo_data = await get_geo_data(client_ip)

    screenshot_url = None
    if screenshot is not None:
        screenshot_url = await _upload_screenshot_to_cloudinary(screenshot)

    # Log to Langfuse as a standalone trace for later filtering and review.
    langfuse.trace(
        name="general_feedback",
        session_id=session_id,
        user_id=device_id,
        input=feedback_text,
        tags=["feedback", "general"],
        metadata={
            "geo_data": geo_data,
            "screenshot_url": screenshot_url,
        },
    )

    return {"status": "success", "message": "Thank you for your feedback!"}


def split_header_content(text: str) -> Tuple[str, str]:
    lines = text.split("\n", 1)
    if len(lines) > 1:
        return lines[0] + "\n", lines[1]
    return "", text


def organize_nodes(nodes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    # Step 1: Group nodes by page (URL)
    pages = defaultdict(list)
    for node in nodes:
        url = node.metadata["url"]
        pages[url].append(node)

    # Step 2: Order nodes on each page by sequence number
    for url, page_nodes in pages.items():
        pages[url] = sorted(page_nodes, key=lambda x: x.metadata["sequence"])

    # Step 3: Merge overlapping nodes
    organized_pages = {}
    for url, page_nodes in pages.items():
        merged_nodes = merge_nodes_with_headers(page_nodes)
        organized_pages[url] = merged_nodes

    return organized_pages


def merge_nodes_with_headers(nodes: List[Dict[str, Any]]) -> List[str]:
    merged_results = []
    current_merged = ""
    current_header = ""

    for node in nodes:
        node_text = node.text
        header, content = split_header_content(node_text)

        if header != current_header:
            if current_merged:
                merged_results.append(current_header + current_merged)
            current_header = header
            current_merged = content
        else:
            current_merged = merge_content(current_merged, content)

    if current_merged:
        merged_results.append(current_header + current_merged)

    return merged_results


def split_header_content(text: str) -> Tuple[str, str]:
    lines = text.split("\n", 1)
    if len(lines) > 1:
        return lines[0] + "\n", lines[1]
    return "", text


def merge_content(existing: str, new: str) -> str:
    # This is a simple merge function. You might need to implement
    # a more sophisticated merging logic based on your specific requirements.
    combined = existing + " " + new
    words = combined.split()
    return " ".join(sorted(set(words), key=words.index))


def process_response_nodes(
    nodes: List[NodeWithScore],
    background_tasks: BackgroundTasks,
):
    # organize_nodes(nodes)

    try:
        # Start background tasks to download documents from LlamaCloud if needed
        from app.engine.service import LLamaCloudFileService

        LLamaCloudFileService.download_files_from_nodes(nodes, background_tasks)
    except ImportError:
        logger.debug("LlamaCloud is not configured. Skipping post processing of nodes")
        pass
