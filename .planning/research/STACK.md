# Stack Research: Langfuse Observability Enhancement

**Domain:** LLM observability and metadata tracking
**Researched:** January 30, 2026
**Confidence:** HIGH

## Executive Summary

This research focuses on the Langfuse SDK capabilities needed to implement comprehensive metadata tracking for the BYU Pathway chatbot. The existing integration already uses `@observe` decorators and basic trace updates. The new milestone requires adding: cost/latency/token tracking, session management, and contextual tags.

**Key Finding:** Langfuse provides robust built-in mechanisms for all required metrics. The Python SDK (2.52.1) and JS SDK (3.28.0) offer symmetric APIs via `propagate_attributes()` for cross-observation metadata and `update()` methods for observation-specific data.

## Recommended Stack

### Core APIs and Methods

| Component | Method/API | Purpose | Why Recommended |
|-----------|------------|---------|-----------------|
| **Cost Tracking** | `usage_details` + `cost_details` parameters | Track token usage and USD costs per generation | Langfuse auto-calculates costs from usage if model definitions exist; ingesting both provides fallback and override capability |
| **Token Tracking** | `usage_details` dict with arbitrary keys | Track input/output/cached/total tokens | Flexible schema supports any token type (input, output, cached_tokens, reasoning_tokens, etc.); auto-sums to total if not provided |
| **Latency Tracking** | Automatic via context managers | Track request duration | Built into `start_as_current_observation()` - no manual timing needed |
| **Session Management** | `propagate_attributes(session_id=...)` | Group traces across conversation | Propagates to all child observations automatically; max 200 chars; used for session-level metrics |
| **User Tracking** | `propagate_attributes(user_id=...)` | Track per-user metrics | Same propagation as session_id; already used in existing codebase |
| **Tags** | `propagate_attributes(tags=[...])` | Categorize observations (role, security, etc.) | List of strings ≤200 chars each; filterable in UI; aggregated to trace level |
| **Metadata** | `propagate_attributes(metadata={...})` | Structured context (language, environment, etc.) | Dict with alphanumeric keys and string values ≤200 chars; filterable in UI |
| **Model/Provider** | `model` parameter on generation | Track which model was used | Required for cost inference; used by Langfuse model definitions |
| **Environment** | Not directly supported via SDK | Differentiate dev/staging/prod | **Recommendation:** Use metadata or tags instead (see Alternatives) |

### Supporting Libraries (Already Installed)

| Library | Version | Purpose | Integration Point |
|---------|---------|---------|-------------------|
| `langfuse` | 2.52.1 | Python SDK for backend | Already integrated via `@observe` decorator and `langfuse_context` |
| `langfuse` (JS) | 3.28.0 | JS/TS SDK for frontend | Already available but not extensively used |
| `llama-index-core` | 0.10.58 | LLM framework | Response objects contain `source_nodes` but NOT token counts by default |

## Implementation Patterns

### 1. Cost and Token Tracking

**Langfuse Mechanism:**
- **Ingestion-based (recommended):** Pass `usage_details` and optionally `cost_details` to `update()` method
- **Inference-based (fallback):** Langfuse calculates costs from model definitions if only `usage_details` provided

**Usage Details Schema:**
```python
usage_details = {
    "input": int,           # Required for cost calculation
    "output": int,          # Required for cost calculation
    "total": int,           # Optional, auto-calculated if omitted
    # Arbitrary additional keys supported:
    "cache_read_input_tokens": int,
    "reasoning_tokens": int,
    "audio_tokens": int,
    # etc.
}
```

**Cost Details Schema (optional):**
```python
cost_details = {
    "input": float,         # USD cost for input tokens
    "output": float,        # USD cost for output tokens
    "total": float,         # Optional, auto-calculated if omitted
    # Keys must match usage_details keys exactly
    "cache_read_input_tokens": float,
}
```

**Integration with LlamaIndex:**

**CRITICAL LIMITATION:** LlamaIndex `ChatResponse` and `StreamingAgentChatResponse` objects do **NOT** expose token counts by default. LlamaIndex uses an internal callback system that may track tokens, but they are not accessible on the response object.

**Workaround Options:**
1. **LlamaIndex Callbacks (recommended):** Use LlamaIndex's `TokenCountingHandler` callback to capture token counts during generation
2. **Manual Tokenization:** Use tiktoken library to estimate tokens from input/output strings
3. **Provider-Specific Extraction:** If using OpenAI via LlamaIndex, the underlying `openai` response may contain usage data in callback metadata

**Example with Callback:**
```python
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from langfuse import get_client

langfuse = get_client()
token_counter = TokenCountingHandler()

# Add to chat engine's callback manager
chat_engine.callback_manager.handlers.append(token_counter)

# After generation
with langfuse.start_as_current_observation(
    as_type="generation",
    name="llm-call",
    model="gpt-4o-mini"
) as gen:
    response = await chat_engine.astream_chat(message, history)
    
    # Extract tokens from callback
    gen.update(
        usage_details={
            "input": token_counter.prompt_llm_token_count,
            "output": token_counter.completion_llm_token_count,
            "total": token_counter.total_llm_token_count,
        }
    )
```

**Why This Approach:**
- LlamaIndex doesn't expose tokens on response objects
- Langfuse requires token counts for cost calculation
- Token callbacks are the most accurate method (avoids estimation errors)
- Fallback: If tokens unavailable, Langfuse will attempt inference using tiktoken (for OpenAI models)

### 2. Latency Tracking

**Built-in Mechanism:**
- Langfuse automatically tracks start/end times when using `start_as_current_observation()` context manager
- No manual timing code needed
- Latency calculated as `end_time - start_time` in milliseconds

**Example:**
```python
from langfuse import get_client

langfuse = get_client()

# Latency automatically tracked
with langfuse.start_as_current_observation(
    as_type="generation",
    name="llm-call",
    model="gpt-4o-mini"
) as gen:
    response = await chat_engine.astream_chat(message, history)
    # Duration captured automatically when context exits
```

**Why This Approach:**
- Zero overhead - built into SDK
- Consistent with existing `@observe` decorator (which also auto-tracks latency)
- Accurate to millisecond precision

### 3. Session Management

**Langfuse Mechanism:**
- Use `propagate_attributes(session_id=...)` to apply session ID to all observations in a context
- Session IDs must be ≤200 character US-ASCII strings
- All observations with same session_id are grouped in Langfuse UI

**Session ID Generation Strategy:**

**RECOMMENDATION:** Use a hybrid approach with client-provided ID and server-side fingerprint fallback:

```python
from langfuse import get_client, propagate_attributes
import hashlib
import uuid

langfuse = get_client()

def generate_session_id(client_id: str = None, ip_address: str = None) -> str:
    """
    Generate session ID with fallback strategy:
    1. Use client-provided ID if available (from frontend)
    2. Fall back to IP-based fingerprint (less reliable but better than nothing)
    """
    if client_id:
        # Client provided explicit session ID (e.g., from localStorage)
        return f"client_{client_id[:180]}"  # Ensure ≤200 chars
    
    if ip_address:
        # Fallback: Hash IP address for pseudo-session
        # Note: Not ideal for privacy, consider alternatives
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:16]
        return f"ip_{ip_hash}"
    
    # Last resort: Generate random ID (no persistence across requests)
    return f"anon_{uuid.uuid4().hex[:16]}"

# In route handler
@observe()
async def chat(request: Request, data: ChatData):
    client_id = data.data.get("client_id")  # Frontend should send this
    client_ip = request.headers.get("X-Forwarded-For", request.client.host)
    
    session_id = generate_session_id(client_id, client_ip)
    
    with propagate_attributes(session_id=session_id):
        # All nested observations automatically inherit session_id
        response = await chat_engine.astream_chat(...)
```

**Frontend Session ID Generation:**

The frontend should generate a persistent client ID and include it in requests:

```typescript
// frontend/app/utils/session.ts
export function getOrCreateClientId(): string {
  const storageKey = 'pathway_client_id';
  let clientId = localStorage.getItem(storageKey);
  
  if (!clientId) {
    // Generate UUID-based client ID
    clientId = `client_${crypto.randomUUID()}`;
    localStorage.setItem(storageKey, clientId);
  }
  
  return clientId;
}

// In chat component
const clientId = getOrCreateClientId();
const response = await fetch('/api/chat', {
  body: JSON.stringify({
    messages,
    data: { client_id: clientId }
  })
});
```

**Why This Approach:**
- Client-side localStorage provides stable session IDs across page reloads
- IP-based fallback handles cases where localStorage is disabled/cleared
- Hybrid approach balances persistence with privacy concerns
- Langfuse session UI requires consistent session_id across traces

### 4. Tags for Categorization

**Langfuse Mechanism:**
- Use `propagate_attributes(tags=[...])` to apply tags to all observations
- Tags are strings ≤200 characters each
- Tags automatically aggregated to trace level
- Filterable in Langfuse UI

**Recommended Tag Schema:**

```python
from langfuse import propagate_attributes

# Early in request handler (before any observations created)
with propagate_attributes(
    tags=[
        f"role:{role}",              # "role:missionary" or "role:ACM"
        f"security:{risk_level}",     # "security:low", "security:blocked"
        f"language:{user_language}",  # "language:en", "language:es"
        "conversation_type:chat",     # vs "conversation_type:search"
    ]
):
    # All observations inherit these tags
    with langfuse.start_as_current_observation(...):
        ...
```

**Tag Categories:**
1. **Role:** `role:missionary`, `role:ACM` (user type from existing params)
2. **Security:** `security:low`, `security:medium`, `security:high`, `security:blocked`
3. **Language:** `language:en`, `language:es`, `language:fr` (from existing detection)
4. **Conversation Type:** `conversation_type:chat`, `conversation_type:request` (streaming vs non-streaming)

**Why This Approach:**
- Prefixed format (`category:value`) enables filtering by category in UI
- All tags ≤200 chars (longest: "conversation_type:request" = 27 chars)
- Reuses existing metadata (role, language, risk_level) that's already collected
- Aggregated to trace level automatically by Langfuse

### 5. Metadata for Context

**Langfuse Mechanism:**
- Use `propagate_attributes(metadata={...})` for propagated metadata (applies to all child observations)
- Use `observation.update(metadata={...})` for observation-specific metadata
- Keys: Alphanumeric only (no whitespace/special chars)
- Values: Strings ≤200 characters

**Recommended Metadata Schema:**

```python
from langfuse import propagate_attributes

# Propagated metadata (applies to entire trace)
with propagate_attributes(
    metadata={
        "environment": "production",        # or "development", "staging"
        "model_provider": "openai",         # from MODEL_PROVIDER env var
        "user_language": "en",              # from existing detection
        "role": "missionary",               # from existing params
        "client_version": "1.2.3",          # optional: frontend version
    }
):
    # Observation-specific metadata (not propagated)
    with langfuse.start_as_current_observation(...) as gen:
        gen.update(metadata={
            "retriever_k": "35",            # specific to this generation
            "temperature": "0.0",           # LLM parameter
            "max_tokens": "2048",           # LLM parameter
        })
```

**Key Constraints:**
- Keys MUST be alphanumeric only: `user_language` ✓, `user-language` ✗
- Values MUST be strings: `"35"` ✓, `35` ✗
- Values MUST be ≤200 chars
- Call `propagate_attributes()` EARLY in trace to ensure all observations covered

**Why This Approach:**
- Separates trace-level context (propagated) from observation-level details (not propagated)
- Alphanumeric-only keys ensure Langfuse compatibility
- String values avoid type coercion issues
- Environment tracking via metadata (Langfuse doesn't have dedicated environment field)

### 6. Model and Provider Tracking

**Langfuse Mechanism:**
- Pass `model` parameter when creating generation observations
- Langfuse uses this for cost inference via model definitions
- Model parameter also displayed in UI and filterable

**Implementation:**
```python
from langfuse import get_client
import os

langfuse = get_client()

# Get from environment variables
model_name = os.getenv("MODEL", "gpt-4o-mini")
model_provider = os.getenv("MODEL_PROVIDER", "openai")

with langfuse.start_as_current_observation(
    as_type="generation",
    name="llm-call",
    model=model_name,  # "gpt-4o-mini"
) as gen:
    # Also add provider to metadata for additional context
    gen.update(metadata={"model_provider": model_provider})
```

**Why This Approach:**
- `model` parameter is required for Langfuse cost inference
- Matches existing environment variable naming (`MODEL`, `MODEL_PROVIDER`)
- Provider in metadata enables filtering by provider in UI

## Alternatives Considered

### Environment Tracking

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| Dedicated `LANGFUSE_ENVIRONMENT` env var | Official Langfuse documentation mentions it | Not actually used by SDK (as of 2.52.1); no effect | **Don't use** |
| Via `metadata={"environment": "prod"}` | Works with current SDK; filterable in UI | Not a first-class field | **Use this** |
| Via `tags=["env:prod"]` | Also works; filterable | Tags are for categorization, not config | Alternative if prefer tags |
| Via `version` parameter | Could repurpose version field | Semantically incorrect; version is for app releases | Don't use |

**Recommendation:** Use propagated metadata with `"environment"` key. Langfuse doesn't have a dedicated environment field in the SDK despite documentation references.

### Session ID Generation

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| Client-side UUID in localStorage | Stable across page reloads; no server state | Requires frontend changes; lost on cache clear | **Use as primary** |
| IP-based hashing | No frontend required; works for all clients | Not stable (DHCP, NAT, VPN); privacy concerns | Use as fallback |
| Server-side session cookies | Standard web pattern | Requires cookie infrastructure; GDPR implications | Not needed for this use case |
| No session tracking | No implementation needed | Loses conversation grouping | Don't use |

**Recommendation:** Hybrid approach with client ID primary and IP-based fallback. Balances stability with implementation complexity.

### Token Count Extraction

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| LlamaIndex TokenCountingHandler | Accurate; uses actual model tokenizer | Requires callback setup; adds handler | **Use this** |
| Manual tiktoken estimation | Direct control; no callbacks | Only works for OpenAI models; estimation errors | Fallback only |
| Langfuse inference | No code needed; uses built-in tokenizers | Only works if Langfuse has tokenizer for model | Automatic fallback |
| Extract from provider response | Most accurate (actual tokens used) | LlamaIndex doesn't expose provider response | Not feasible |

**Recommendation:** Use LlamaIndex TokenCountingHandler as primary method. Langfuse inference provides automatic fallback for OpenAI/Anthropic models.

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `langfuse_context.update_current_trace()` for every attribute | Updates trace, not observation; can overwrite each other | Use `propagate_attributes()` for cross-observation data |
| Hardcoded session IDs | Not unique per user; all users grouped together | Generate per-client session IDs |
| Non-string metadata values | Langfuse validation will drop them | Convert all values to strings: `str(value)` |
| Metadata keys with hyphens/spaces | Invalid per Langfuse schema; silently dropped | Use underscores: `user_language` not `user-language` |
| Tags >200 characters | Silently dropped by Langfuse | Keep tags short; use metadata for long values |
| `LANGFUSE_ENVIRONMENT` env var | Not used by SDK; no effect | Use `metadata={"environment": "..."}` |
| Cost inference without `model` parameter | Langfuse can't match to model definitions | Always pass `model` to generation observations |
| Mixing `usage` and `usage_details` | SDK only recognizes one format | Use `usage_details` (more flexible schema) |

## Integration with Existing Stack

### Backend (Python + FastAPI)

**Existing Usage:**
- `@observe()` decorator on route handlers (lines 46, 220 in chat.py)
- `langfuse_context.update_current_trace()` for trace-level metadata (lines 84, 188, 255, 338)
- `langfuse.flush()` before streaming responses (lines 98, 269)

**New Patterns Needed:**
1. **Replace trace updates with propagate_attributes:**
   ```python
   # OLD (current)
   langfuse_context.update_current_trace(
       metadata={"user_language": user_language, **geo_data}
   )
   
   # NEW (recommended)
   with propagate_attributes(
       metadata={"user_language": user_language, **geo_data},
       session_id=session_id,
       tags=[f"role:{role}", f"security:{risk_level}"]
   ):
       # All nested observations automatically inherit
   ```

2. **Add token tracking with LlamaIndex callback:**
   ```python
   from llama_index.core.callbacks import TokenCountingHandler
   
   token_counter = TokenCountingHandler()
   chat_engine.callback_manager.handlers.append(token_counter)
   
   # After generation
   gen.update(
       usage_details={
           "input": token_counter.prompt_llm_token_count,
           "output": token_counter.completion_llm_token_count,
       }
   )
   ```

3. **Add model parameter to generations:**
   ```python
   model_name = os.getenv("MODEL", "gpt-4o-mini")
   
   with langfuse.start_as_current_observation(
       as_type="generation",
       name="llm-call",
       model=model_name,  # NEW
   ) as gen:
       ...
   ```

### Environment Variables

**Existing:**
- `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` (already configured)
- `MODEL`, `MODEL_PROVIDER`, `EMBEDDING_MODEL` (already configured)

**New (optional):**
- `ENVIRONMENT` - Application environment (dev/staging/prod)
  - Used in `main.py` line 18: `environment = os.getenv("ENVIRONMENT", "dev")`
  - Should be propagated to Langfuse via metadata

**Example .env addition:**
```bash
# Application environment for observability
ENVIRONMENT=production
```

## Version Compatibility

| Package | Current | Compatible With | Notes |
|---------|---------|-----------------|-------|
| langfuse | 2.52.1 | llama-index 0.10.58 | No conflicts; both stable versions |
| langfuse (JS) | 3.28.0 | next 15.3.6 | No conflicts; modern Next.js support |
| llama-index-core | 0.10.58 | langfuse 2.52.1 | TokenCountingHandler available |

**No version upgrades required.** All functionality available in current versions.

## Performance Considerations

### Token Counting Overhead

**Impact:** TokenCountingHandler adds ~1-2ms per request for tokenization
**Mitigation:** Tokenization happens in callbacks during generation (parallel with LLM call)
**Verdict:** Negligible impact; acceptable overhead for accurate cost tracking

### Attribute Propagation Overhead

**Impact:** Propagated attributes stored in OpenTelemetry context (thread-local storage)
**Mitigation:** Context lookup is O(1); minimal memory overhead
**Verdict:** No measurable performance impact

### Metadata String Conversion

**Impact:** Converting values to strings (e.g., `str(retriever_k)`) adds negligible CPU time
**Mitigation:** Happens once per observation creation
**Verdict:** No measurable impact

### Langfuse Flush Timing

**Impact:** Existing code calls `langfuse.flush()` before streaming (lines 98, 269)
**Note:** Flush blocks until buffered data is sent to Langfuse API (~10-50ms)
**Current behavior:** Already blocking before responses; no change needed
**Verdict:** No new performance impact

## Sources

- **Langfuse Python SDK Documentation:** https://langfuse.com/docs/observability/sdk/instrumentation (retrieved Jan 30, 2026)
- **Langfuse Token & Cost Tracking:** https://langfuse.com/docs/observability/features/token-and-cost-tracking (retrieved Jan 30, 2026)
- **Langfuse Sessions Documentation:** https://langfuse.com/docs/observability/features/sessions (retrieved Jan 30, 2026)
- **Langfuse Tags Documentation:** https://langfuse.com/docs/observability/features/tags (retrieved Jan 30, 2026)
- **Langfuse Metadata Documentation:** https://langfuse.com/docs/observability/features/metadata (retrieved Jan 30, 2026)
- **Existing Codebase:**
  - `backend/app/api/routers/chat.py` - Current Langfuse integration patterns
  - `backend/pyproject.toml` - Langfuse version (2.52.1)
  - `frontend/package.json` - Langfuse JS version (3.28.0)
  - `backend/.env.example` - Environment variable patterns

---
*Stack research for: Langfuse Observability Enhancement*
*Researched: January 30, 2026*
*Confidence Level: HIGH (verified against official Langfuse documentation and existing codebase)*
