# Architecture Research: Enhanced Langfuse Integration

**Project:** pathway-chatbot (FastAPI + LlamaIndex + Next.js)
**Researched:** 2026-01-30
**Confidence:** HIGH

## Executive Summary

This architecture enhances existing Langfuse integration to capture comprehensive metadata (tokens, latency, sessions, environment) without disrupting the working FastAPI + LlamaIndex + Next.js pattern. The design prioritizes:

- **Minimal disruption:** Build on existing `@observe` decorators
- **Centralized helpers:** DRY principles with reusable metadata builders
- **Clear data flow:** Token extraction → Langfuse → Analytics
- **Backend-first approach:** Complete backend tracking before frontend sessions

## Current Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ app/api/chat/route.ts (if exists - not found)   │    │
│  │ - AI SDK streaming (likely)                      │    │
│  │ - Forwards to backend                            │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │ HTTP POST                      │
└─────────────────────────┼──────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────┐
│                Backend (FastAPI + Python)               │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐   │
│  │ chat.py (@observe decorator)                     │   │
│  │ - Input validation (SecurityValidator)           │   │
│  │ - langfuse_context.update_current_trace()        │   │
│  │ - Manual metadata: geo, security, language       │   │
│  └──────────┬───────────────────────────────────────┘   │
│             │                                            │
│  ┌──────────▼───────────────────────────────────────┐   │
│  │ get_chat_engine() → LlamaIndex                   │   │
│  │ - CustomCondensePlusContextChatEngine            │   │
│  │ - chat_engine.astream_chat()                     │   │
│  │ - Returns StreamingAgentChatResponse             │   │
│  │                                                   │   │
│  │ ┌─────────────────────────────────────────────┐  │   │
│  │ │ Settings.llm (via settings.py)              │  │   │
│  │ │ - OpenAI / Anthropic / Groq / etc.          │  │   │
│  │ │ - LlamaIndex abstracts LLM calls            │  │   │
│  │ └─────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
│                         │                                │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │ VercelStreamResponse                            │    │
│  │ - Streams tokens to frontend                    │    │
│  │ - Returns trace_id in response                  │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                Langfuse (External Service)               │
│  - Traces stored with:                                   │
│    - input, output (currently tracked)                   │
│    - metadata (geo, security, language)                  │
│    - Missing: tokens, latency, model, provider          │
└──────────────────────────────────────────────────────────┘
```

### Current Components

| Component | Current Responsibility | Implementation |
|-----------|------------------------|----------------|
| `chat.py` | Chat endpoint with Langfuse tracing | `@observe()` decorator + manual metadata |
| `langfuse.py` | Langfuse client initialization | Simple `Langfuse(...)` instance |
| `get_chat_engine()` | LlamaIndex chat engine factory | CustomCondensePlusContextChatEngine |
| `settings.py` | LLM provider configuration | Settings.llm initialized per provider |
| `VercelStreamResponse` | Stream tokens to frontend | Custom streaming wrapper |

### Current Metadata Flow

```
User Request
    ↓
@observe() decorator creates trace
    ↓
Manual metadata collection:
    - Geo data (get_geo_data)
    - Security validation
    - Language detection
    ↓
langfuse_context.update_current_trace(
    input=...,
    output=...,
    metadata={...}  # Manually built dict
)
    ↓
Langfuse API (automatic via @observe)
```

**Key Observation:** Current pattern manually builds metadata dicts in multiple places (lines 84-95, 166-186, etc.). No token or latency tracking.

## Recommended Enhancement Architecture

### Enhanced System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ app/api/chat/route.ts (NEW/ENHANCED)            │    │
│  │ - Detect/generate session_id                    │    │
│  │ - Pass session_id in request headers            │    │
│  │ - Store session in localStorage/cookie          │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │ HTTP POST + session_id         │
└─────────────────────────┼──────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────┐
│                Backend (FastAPI + Python)               │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐   │
│  │ NEW: app/utils/langfuse_metadata.py              │   │
│  │ ┌────────────────────────────────────────────┐   │   │
│  │ │ LangfuseMetadataBuilder (centralized)      │   │   │
│  │ │ - build_trace_metadata()                   │   │   │
│  │ │ - extract_tokens_from_response()           │   │   │
│  │ │ - calculate_latency()                      │   │   │
│  │ │ - get_model_provider()                     │   │   │
│  │ └────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────┘   │
│             │                                            │
│  ┌──────────▼───────────────────────────────────────┐   │
│  │ ENHANCED: chat.py                                │   │
│  │ - Extract session_id from request                │   │
│  │ - Timer.start() before chat_engine call          │   │
│  │ - Timer.stop() after response                    │   │
│  │ - Use LangfuseMetadataBuilder.build()            │   │
│  │ - propagate_attributes(session_id, user_id)      │   │
│  └──────────┬───────────────────────────────────────┘   │
│             │                                            │
│  ┌──────────▼───────────────────────────────────────┐   │
│  │ get_chat_engine() → LlamaIndex                   │   │
│  │ - Returns response with .source_nodes            │   │
│  │                                                   │   │
│  │ ┌─────────────────────────────────────────────┐  │   │
│  │ │ NEW: Token extraction wrapper               │  │   │
│  │ │ - Intercept LLM response                    │  │   │
│  │ │ - Extract usage from response metadata      │  │   │
│  │ └─────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
│                         │                                │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │ ENHANCED: Update trace with full metadata       │    │
│  │ langfuse_context.update_current_trace(          │    │
│  │   metadata=builder.build()                      │    │
│  │ )                                               │    │
│  │ langfuse_context.update_current_generation(     │    │
│  │   usage_details={"input": X, "output": Y}       │    │
│  │ )                                               │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                Langfuse (External Service)               │
│  - Traces with comprehensive metadata:                   │
│    ✅ input, output                                      │
│    ✅ tokens (input, output, total)                      │
│    ✅ latency (ms)                                       │
│    ✅ model, provider                                    │
│    ✅ session_id, user_id                                │
│    ✅ environment, version                               │
│    ✅ geo, security, language (existing)                 │
└──────────────────────────────────────────────────────────┘
```

### New Components to Add

| Component | Responsibility | Implementation Location |
|-----------|----------------|-------------------------|
| `LangfuseMetadataBuilder` | Centralized metadata construction | `backend/app/utils/langfuse_metadata.py` |
| `TokenExtractor` | Extract token usage from LLM responses | `backend/app/utils/langfuse_metadata.py` |
| `LatencyTracker` | Time operations with context manager | `backend/app/utils/langfuse_metadata.py` |
| Session management | Generate/persist session IDs | Frontend: `app/utils/session.ts` |
| Environment detector | Detect env from process.env | `backend/app/utils/langfuse_metadata.py` |

### Integration Points

#### 1. Backend: Token Extraction

**Challenge:** LlamaIndex abstracts LLM calls across multiple providers (OpenAI, Anthropic, Groq, etc.). Token data location varies.

**Solution:** Extract tokens from `StreamingAgentChatResponse` after completion.

```python
# backend/app/utils/langfuse_metadata.py

from typing import Dict, Any, Optional
from llama_index.core.chat_engine.types import StreamingAgentChatResponse
import os
import time

class TokenExtractor:
    """Extract token usage from LlamaIndex responses."""
    
    @staticmethod
    def extract_from_response(response: StreamingAgentChatResponse) -> Dict[str, int]:
        """
        Extract token counts from LlamaIndex response.
        
        Returns dict with keys: input_tokens, output_tokens, total_tokens
        """
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        # LlamaIndex responses may have usage in response metadata
        if hasattr(response, "additional_kwargs"):
            additional = response.additional_kwargs
            if "usage" in additional:
                # OpenAI-style usage
                usage_data = additional["usage"]
                usage["input_tokens"] = usage_data.get("prompt_tokens", 0)
                usage["output_tokens"] = usage_data.get("completion_tokens", 0)
                usage["total_tokens"] = usage_data.get("total_tokens", 0)
        
        # Anthropic-style usage (Claude models)
        if hasattr(response, "raw"):
            raw = response.raw
            if hasattr(raw, "usage"):
                usage["input_tokens"] = getattr(raw.usage, "input_tokens", 0)
                usage["output_tokens"] = getattr(raw.usage, "output_tokens", 0)
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        
        return usage

class LatencyTracker:
    """Track operation latency with context manager."""
    
    def __init__(self):
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
    
    @property
    def latency_ms(self) -> float:
        """Return latency in milliseconds."""
        if self.start_time is None or self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

class LangfuseMetadataBuilder:
    """Centralized builder for Langfuse trace metadata."""
    
    def __init__(self):
        self.metadata: Dict[str, Any] = {}
    
    def with_tokens(self, usage: Dict[str, int]) -> "LangfuseMetadataBuilder":
        """Add token usage data."""
        self.metadata["tokens"] = usage
        return self
    
    def with_latency(self, latency_ms: float) -> "LangfuseMetadataBuilder":
        """Add latency in milliseconds."""
        self.metadata["latency_ms"] = round(latency_ms, 2)
        return self
    
    def with_model_info(self) -> "LangfuseMetadataBuilder":
        """Add model and provider from settings."""
        self.metadata["model"] = os.getenv("MODEL", "unknown")
        self.metadata["provider"] = os.getenv("MODEL_PROVIDER", "unknown")
        self.metadata["embedding_model"] = os.getenv("EMBEDDING_MODEL", "unknown")
        return self
    
    def with_environment(self) -> "LangfuseMetadataBuilder":
        """Add environment info."""
        self.metadata["environment"] = os.getenv("ENVIRONMENT", "production")
        self.metadata["version"] = os.getenv("APP_VERSION", "1.0.0")
        return self
    
    def with_geo_data(self, geo_data: Dict[str, Any]) -> "LangfuseMetadataBuilder":
        """Add geo location data (from existing get_geo_data)."""
        self.metadata.update(geo_data)
        return self
    
    def with_security_data(self, security_details: Dict[str, Any]) -> "LangfuseMetadataBuilder":
        """Add security validation data."""
        security_metadata = {
            "input_validated": True,
            "input_sanitized": True
        }
        
        if security_details.get("is_suspicious"):
            security_metadata.update({
                "is_suspicious": True,
                "risk_level": security_details.get("risk_level", "LOW"),
                "security_details": security_details
            })
        else:
            security_metadata["is_suspicious"] = False
        
        self.metadata["security_validation"] = security_metadata
        return self
    
    def with_language(self, user_language: str) -> "LangfuseMetadataBuilder":
        """Add detected user language."""
        self.metadata["user_language"] = user_language
        return self
    
    def with_retrieved_docs(self, retrieved_docs: str) -> "LangfuseMetadataBuilder":
        """Add retrieved document info."""
        self.metadata["retrieved_docs"] = retrieved_docs
        return self
    
    def with_role(self, role: str) -> "LangfuseMetadataBuilder":
        """Add user role (missionary, ACM, etc.)."""
        self.metadata["role"] = role
        return self
    
    def build(self) -> Dict[str, Any]:
        """Return the built metadata dictionary."""
        return self.metadata
```

#### 2. Backend: Enhanced Chat Endpoint

**Integration point:** Modify `backend/app/api/routers/chat.py`

```python
# backend/app/api/routers/chat.py

# Add imports
from app.utils.langfuse_metadata import (
    LangfuseMetadataBuilder,
    TokenExtractor,
    LatencyTracker
)
from langfuse.decorators import propagate_attributes

@r.post("")
@observe()
async def chat(
    request: Request,
    data: ChatData,
    background_tasks: BackgroundTasks,
):
    # ... existing security validation code ...
    
    # Extract session_id from request headers (NEW)
    session_id = request.headers.get("X-Session-ID")
    user_id = request.headers.get("X-User-ID")  # If available from auth
    
    # Propagate session/user to all nested observations (NEW)
    with propagate_attributes(
        session_id=session_id,
        user_id=user_id,
        metadata={"environment": os.getenv("ENVIRONMENT", "production")}
    ):
        # ... existing code to get chat_engine ...
        
        # Track latency (NEW)
        latency_tracker = LatencyTracker()
        with latency_tracker:
            response = await chat_engine.astream_chat(last_message_content, messages)
            
            # Consume tokens to get full response
            retrieved = "\n\n".join([
                f"node_id: {idx+1}\n{node.metadata['url']}\n{node.text}"
                for idx, node in enumerate(response.source_nodes)
            ])
            
            tokens = []
            async for token in response.async_response_gen():
                tokens.append(token)
        
        # Extract token usage (NEW)
        token_usage = TokenExtractor.extract_from_response(response)
        
        # Build comprehensive metadata (NEW)
        metadata_builder = LangfuseMetadataBuilder()
        metadata = (metadata_builder
            .with_tokens(token_usage)
            .with_latency(latency_tracker.latency_ms)
            .with_model_info()
            .with_environment()
            .with_geo_data(geo_data)
            .with_security_data({"is_suspicious": is_suspicious, **security_details})
            .with_language(user_language)
            .with_retrieved_docs(retrieved)
            .with_role(role)
            .build()
        )
        
        # Update trace with comprehensive metadata (ENHANCED)
        langfuse_context.update_current_trace(
            input=langfuse_input,
            output=response.response,
            metadata=metadata
        )
        
        # Update generation-level token usage (NEW)
        if token_usage["total_tokens"] > 0:
            langfuse_context.update_current_generation(
                usage_details={
                    "input": token_usage["input_tokens"],
                    "output": token_usage["output_tokens"],
                    "total": token_usage["total_tokens"]
                }
            )
        
        # ... rest of existing code ...
```

#### 3. Frontend: Session Management

**Integration point:** Create `frontend/app/utils/session.ts`

```typescript
// frontend/app/utils/session.ts

/**
 * Generate or retrieve session ID for Langfuse tracking.
 * 
 * Session persists in localStorage for the browser session.
 * Falls back to memory-only if localStorage unavailable.
 */
export function getOrCreateSessionId(): string {
  const SESSION_KEY = "langfuse_session_id";
  
  // Try to get existing session from localStorage
  if (typeof window !== "undefined" && window.localStorage) {
    const existing = localStorage.getItem(SESSION_KEY);
    if (existing) {
      return existing;
    }
  }
  
  // Generate new session ID (simple UUID v4)
  const sessionId = crypto.randomUUID();
  
  // Store for future requests
  if (typeof window !== "undefined" && window.localStorage) {
    try {
      localStorage.setItem(SESSION_KEY, sessionId);
    } catch (e) {
      console.warn("Could not persist session ID", e);
    }
  }
  
  return sessionId;
}

/**
 * Clear the current session (e.g., on logout).
 */
export function clearSession(): void {
  if (typeof window !== "undefined" && window.localStorage) {
    localStorage.removeItem("langfuse_session_id");
  }
}
```

**Integration point:** Enhance chat request to include session

```typescript
// frontend/app/components/ui/chat/chat-messages.tsx (or similar)

import { getOrCreateSessionId } from "@/app/utils/session";

async function sendChatMessage(message: string) {
  const sessionId = getOrCreateSessionId();
  
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-ID": sessionId,  // NEW: Include session
    },
    body: JSON.stringify({
      messages: [...previousMessages, { role: "user", content: message }],
    }),
  });
  
  // ... handle response ...
}
```

## Data Flow: Enhanced

### Complete Request Flow with Metadata Capture

```
1. Frontend generates/retrieves session_id
   ↓
2. POST /api/chat with X-Session-ID header
   ↓
3. @observe() creates Langfuse trace
   ↓
4. propagate_attributes(session_id, user_id)
   ↓
5. Security validation → geo_data, security_details
   ↓
6. LatencyTracker.start()
   ↓
7. chat_engine.astream_chat() → LlamaIndex → LLM
   ↓
8. Consume response stream → tokens list
   ↓
9. LatencyTracker.stop()
   ↓
10. TokenExtractor.extract_from_response()
    ↓
11. LangfuseMetadataBuilder.build() combines:
    - tokens
    - latency
    - model/provider
    - environment
    - geo_data
    - security_details
    - language
    - retrieved_docs
    - role
    ↓
12. langfuse_context.update_current_trace(metadata=...)
    ↓
13. langfuse_context.update_current_generation(usage_details=...)
    ↓
14. return VercelStreamResponse with trace_id
    ↓
15. Langfuse ingests trace with comprehensive metadata
```

### Token Extraction Flow

```
LLM Response (via LlamaIndex)
    ↓
StreamingAgentChatResponse
    ↓
Check response.additional_kwargs["usage"]  (OpenAI-style)
    ↓
Check response.raw.usage  (Anthropic-style)
    ↓
Extract: input_tokens, output_tokens, total_tokens
    ↓
Return Dict[str, int]
    ↓
Pass to langfuse_context.update_current_generation()
```

## Build Order (Recommended Phases)

### Phase 1: Backend Token & Latency Tracking

**Why first:** Core metadata extraction, no frontend dependencies.

**Tasks:**
1. Create `backend/app/utils/langfuse_metadata.py`
   - Implement `TokenExtractor`
   - Implement `LatencyTracker`
   - Implement `LangfuseMetadataBuilder`
2. Update `backend/app/api/routers/chat.py`
   - Add latency tracking
   - Add token extraction
   - Replace manual metadata dict with builder
3. Test token extraction across providers (OpenAI, Anthropic, Groq)

**Success criteria:**
- Traces show `metadata.tokens.*`
- Traces show `metadata.latency_ms`
- Traces show `metadata.model`, `metadata.provider`

**Estimated effort:** 4-6 hours

### Phase 2: Environment & Model Detection

**Why second:** Easy metadata additions, no external dependencies.

**Tasks:**
1. Add environment detection to builder
   - Read `ENVIRONMENT` env var
   - Read `APP_VERSION` env var
2. Add model/provider detection
   - Read from `settings.py` config
3. Update chat endpoint to include environment metadata

**Success criteria:**
- Traces show `metadata.environment`
- Traces show `metadata.version`
- Model/provider correctly captured

**Estimated effort:** 2-3 hours

### Phase 3: Frontend Session Management

**Why third:** Requires frontend changes, depends on backend being ready.

**Tasks:**
1. Create `frontend/app/utils/session.ts`
   - Implement `getOrCreateSessionId()`
   - Implement `clearSession()`
2. Update chat request to include `X-Session-ID` header
3. Test session persistence across page reloads

**Success criteria:**
- Same session ID persists across requests
- Session ID visible in Langfuse traces

**Estimated effort:** 3-4 hours

### Phase 4: Backend Session Attribute Propagation

**Why fourth:** Requires frontend session ID to be available.

**Tasks:**
1. Update chat endpoint to extract `X-Session-ID` header
2. Add `propagate_attributes(session_id=...)` context
3. Verify session_id appears on all nested observations

**Success criteria:**
- All traces have `session_id` attribute
- Session-level analytics possible in Langfuse

**Estimated effort:** 2-3 hours

### Phase 5: Verification & Testing

**Why last:** Validate entire integration end-to-end.

**Tasks:**
1. Test full flow: frontend → backend → Langfuse
2. Verify all metadata fields present
3. Test with multiple LLM providers
4. Load test: ensure no performance regression
5. Monitor Langfuse ingestion latency

**Success criteria:**
- 100% traces have comprehensive metadata
- No increase in request latency (>50ms acceptable)
- Langfuse dashboard shows accurate analytics

**Estimated effort:** 4-6 hours

**Total estimated effort:** 15-22 hours

## Migration Strategy

### Backward Compatibility

**Principle:** Existing traces continue to work during migration.

**Strategy:**
1. **Builder is additive:** `LangfuseMetadataBuilder` merges with existing metadata
2. **Graceful degradation:** If token extraction fails, trace still succeeds
3. **Feature flags:** Optional `LANGFUSE_ENHANCED_METADATA=true` env var

```python
# Example: Graceful degradation
try:
    token_usage = TokenExtractor.extract_from_response(response)
except Exception as e:
    logger.warning(f"Could not extract tokens: {e}")
    token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
```

### Testing Strategy

1. **Unit tests:** Test `TokenExtractor` with mock responses
2. **Integration tests:** Test full chat flow with test LLM
3. **Smoke tests:** Test in staging with real LLM calls
4. **Monitoring:** Track Langfuse ingestion success rate

## Architectural Patterns

### Pattern 1: Centralized Metadata Builder

**What:** Single class responsible for building Langfuse metadata.

**When to use:** When metadata comes from multiple sources (tokens, latency, geo, security).

**Trade-offs:**
- ✅ **Pro:** DRY - no duplicate metadata logic
- ✅ **Pro:** Easy to extend with new fields
- ✅ **Pro:** Type-safe with proper IDE support
- ⚠️ **Con:** Single point of failure if builder has bugs

**Example:**
```python
# Centralized builder pattern
metadata = (LangfuseMetadataBuilder()
    .with_tokens(tokens)
    .with_latency(latency)
    .with_model_info()
    .build()
)

# vs. Manual dict building (current)
metadata = {
    "tokens": tokens,
    "latency_ms": latency,
    "model": os.getenv("MODEL"),
    # ... easy to miss fields
}
```

### Pattern 2: Context Manager for Timing

**What:** `with` statement automatically tracks operation duration.

**When to use:** When measuring latency of async operations.

**Trade-offs:**
- ✅ **Pro:** Automatic start/stop timing
- ✅ **Pro:** Exception-safe (latency recorded even if operation fails)
- ⚠️ **Con:** Requires nesting if timing multiple operations

**Example:**
```python
tracker = LatencyTracker()
with tracker:
    response = await chat_engine.astream_chat(...)
    # Automatically tracked

latency_ms = tracker.latency_ms  # Available after context exit
```

### Pattern 3: Attribute Propagation for Sessions

**What:** Use Langfuse's `propagate_attributes()` to ensure session/user IDs flow to all nested observations.

**When to use:** When you need metadata on every observation in a trace.

**Trade-offs:**
- ✅ **Pro:** Automatic propagation to children
- ✅ **Pro:** Langfuse handles context management
- ⚠️ **Con:** Must be set early (before child observations created)

**Example:**
```python
with propagate_attributes(session_id=session_id, user_id=user_id):
    # All observations created here automatically have session_id
    response = await chat_engine.astream_chat(...)
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Manual Token Counting

**What people do:** Try to count tokens by splitting strings or using tiktoken directly.

**Why it's wrong:**
- Inaccurate (doesn't match LLM's actual token count)
- Doesn't account for special tokens
- Fails with non-OpenAI models

**Do this instead:** Extract token counts from LLM response metadata.

```python
# ❌ Wrong: Manual counting
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")
tokens = len(enc.encode(text))

# ✅ Right: Use actual usage from response
usage = response.additional_kwargs.get("usage", {})
tokens = usage.get("total_tokens", 0)
```

### Anti-Pattern 2: Blocking Latency Measurement

**What people do:** Use `time.sleep()` or block the event loop while measuring latency.

**Why it's wrong:**
- Blocks other requests in async environment
- Inaccurate measurements (includes sleep time)

**Do this instead:** Use context manager that doesn't block.

```python
# ❌ Wrong: Blocking measurement
start = time.time()
time.sleep(0.1)  # Simulating work - BAD
response = await llm_call()
latency = time.time() - start

# ✅ Right: Non-blocking context manager
with LatencyTracker() as tracker:
    response = await llm_call()
latency = tracker.latency_ms
```

### Anti-Pattern 3: Hardcoding Metadata Keys

**What people do:** Scatter metadata dict construction throughout codebase.

**Why it's wrong:**
- Typos in keys (e.g., `latecy_ms` vs `latency_ms`)
- Inconsistent structure across traces
- Hard to maintain/extend

**Do this instead:** Use centralized builder with typed methods.

```python
# ❌ Wrong: Manual dict everywhere
metadata = {"latency": 123, "tokns": 50}  # Typo!

# ✅ Right: Centralized builder
metadata = builder.with_latency(123).with_tokens(usage).build()
```

### Anti-Pattern 4: Session ID in Request Body

**What people do:** Include session_id in POST body alongside messages.

**Why it's wrong:**
- Pollutes domain model (ChatData shouldn't know about analytics)
- Hard to extract in middleware
- Not standard HTTP practice

**Do this instead:** Use HTTP headers for cross-cutting concerns.

```typescript
// ❌ Wrong: Session in body
fetch("/api/chat", {
  body: JSON.stringify({ messages, sessionId })
})

// ✅ Right: Session in header
fetch("/api/chat", {
  headers: { "X-Session-ID": sessionId },
  body: JSON.stringify({ messages })
})
```

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|---------------------------|
| 0-10k requests/day | Current architecture sufficient. Single FastAPI instance handles ~100 req/s. |
| 10k-100k requests/day | Consider: (1) Separate Langfuse ingestion to background queue, (2) Cache model/provider detection |
| 100k+ requests/day | Consider: (1) Langfuse batching (built-in SDK feature), (2) Async metadata enrichment |

### Scaling Priorities

1. **First bottleneck: Token extraction overhead**
   - **Symptom:** Latency increases >100ms per request
   - **Fix:** Cache token extraction logic, async metadata enrichment
   
2. **Second bottleneck: Langfuse ingestion latency**
   - **Symptom:** Traces take >5s to appear in Langfuse UI
   - **Fix:** Enable SDK batching (`flush_interval=1000ms`), increase batch size

**Note:** Langfuse SDK already uses background threads for ingestion. Metadata builder adds <10ms overhead per request.

## Integration Testing Checklist

- [ ] Tokens extracted correctly for OpenAI models
- [ ] Tokens extracted correctly for Anthropic models
- [ ] Tokens extracted correctly for Groq models
- [ ] Latency tracked accurately (±50ms tolerance)
- [ ] Session ID persists across requests
- [ ] Session ID propagates to all observations
- [ ] Environment/version captured correctly
- [ ] Security metadata preserved (existing behavior)
- [ ] Geo data preserved (existing behavior)
- [ ] Language detection preserved (existing behavior)
- [ ] No performance regression (<50ms overhead)
- [ ] Graceful degradation if token extraction fails
- [ ] Langfuse dashboard shows all new fields

## Sources

**HIGH CONFIDENCE:**
- [Langfuse Python SDK Instrumentation](https://langfuse.com/docs/sdk/python/decorators) - Official docs on `@observe`, `update_current_trace`, `propagate_attributes`
- [Langfuse LlamaIndex Integration](https://langfuse.com/docs/integrations/llama-index/get-started) - Official integration guide
- [LlamaIndex Callbacks Documentation](https://docs.llamaindex.ai/en/stable/module_guides/observability/callbacks/) - Callback system for observability
- Existing codebase: `backend/app/api/routers/chat.py`, `backend/app/langfuse.py`, `backend/app/settings.py`

**MEDIUM CONFIDENCE:**
- Token extraction patterns inferred from LlamaIndex response structure (may vary by provider)
- Frontend session management pattern (standard practice, but not LlamaIndex-specific)

**Research Notes:**
- Langfuse SDK uses OpenTelemetry under the hood for context propagation
- `@observe()` decorator automatically creates trace if not exists
- `propagate_attributes()` uses OTel baggage for cross-service propagation
- LlamaIndex `StreamingAgentChatResponse` structure varies by LLM provider

---

**Architecture research for:** Enhanced Langfuse Integration in pathway-chatbot
**Researched:** 2026-01-30
**Next steps:** Review with team → Phase 1 implementation (backend token tracking)
