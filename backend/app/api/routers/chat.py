import logging
from typing import Tuple, List, Dict, Any
from collections import defaultdict
import traceback
import sys

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from llama_index.core.chat_engine.types import BaseChatEngine, NodeWithScore
from llama_index.core.llms import MessageRole

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
from app.langfuse import langfuse
from app.utils.geo_ip import get_geo_data
import os

chat_router = r = APIRouter()

logger = logging.getLogger("uvicorn")


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
@observe(as_type="generation")
async def chat(
    request: Request,
    data: ChatData,
    background_tasks: BackgroundTasks,
):
    risk_level = None
    security_details = {}
    chat_engine = None

    try:
        last_message_content = data.get_last_message_content()
        
        # Get real client IP and geo data BEFORE security validation
        # This ensures we capture IP/location for both blocked and allowed requests
        client_ip = request.headers.get("X-Forwarded-For", request.client.host)
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        
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
                f"Reason: {security_details.get('reason', 'unknown')}, "
                f"IP: {client_ip}"
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
                    "client_ip": client_ip,
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
            tokens = [blocked_message]
            
            return VercelStreamResponse(
                request, EventCallbackHandler(), blocked_chat_response, data, tokens, skip_suggestions=True, user_language=user_language
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

        event_handler = EventCallbackHandler()
        chat_engine.callback_manager.handlers.append(event_handler)  # type: ignore

        response = await chat_engine.astream_chat(last_message_content, messages)

        retrieved = "\n\n".join(
            [
                f"node_id: {idx+1}\n{node.metadata['url']}\n{node.text}"
                for idx, node in enumerate(response.source_nodes)
            ]
        )

        # await response.aprint_response_stream()
        tokens = []
        async for token in response.async_response_gen():
            tokens.append(token)

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
            "client_ip": client_ip,
            "user_language": user_language,
            "role": role,
            "retrieved_docs": retrieved,
            "retrieved_docs_count": len(response.source_nodes)
        }

        # Update trace with structured fields (trace-level)
        langfuse_context.update_current_trace(
            name="chat",
            input=langfuse_input,
            output=response.response,
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
            status_message="Chat completed successfully"
        )

        trace_id = langfuse_context.get_current_trace_id()

        return VercelStreamResponse(
            request, event_handler, response, data, tokens, trace_id=trace_id, user_language=user_language, skip_suggestions=is_suspicious
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

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in chat engine: {e}",
        ) from e
    finally:
        # Ensure chat engine memory is cleaned up after each request
        if chat_engine is not None:
            try:
                chat_engine.reset()
                logger.debug("Chat engine memory buffer cleared")
            except Exception as cleanup_error:
                logger.error(f"Failed to reset chat engine: {cleanup_error}")


# non-streaming endpoint - delete if not needed
@r.post("/request")
@observe()
async def chat_request(
    request: Request,
    data: ChatData,
) -> Result:
    risk_level = None
    security_details = {}
    
    try:
        last_message_content = data.get_last_message_content()
        
        # Get real client IP and geo data BEFORE security validation
        # This ensures we capture IP/location for both blocked and allowed requests
        client_ip = request.headers.get("X-Forwarded-For", request.client.host)
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in chat engine: {e}",
        ) from e


@r.post("/thumbs_request")
async def thumbs_request(request: ThumbsRequest):
    trace_id = request.trace_id
    value = request.value
    score_id = f'{trace_id}_feedback'

    # Record the user feedback score
    langfuse.score(
        id=score_id,
        trace_id=trace_id,
        name="user_feedback",
        data_type="CATEGORICAL",
        value=value,
    )

    # If feedback is negative (thumbs down), update trace with DEBUG level
    if value == "bad":
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
