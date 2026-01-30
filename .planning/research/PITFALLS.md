# Pitfalls Research: LLM Observability Enhancement

**Domain:** LLM Observability and Metadata Tracking Enhancement
**Researched:** January 30, 2026
**Confidence:** HIGH

**Context:** Enhancing existing Langfuse integration in production chatbot with comprehensive metadata tracking (cost, sessions, performance, multi-provider support).

---

## Critical Pitfalls

### Pitfall 1: Forgetting to Flush in Streaming/Async Contexts

**What goes wrong:**
Metadata updates and trace finalization fail to reach Langfuse because the streaming response returns before the SDK batches and sends events. In FastAPI streaming endpoints, the connection closes while events are still queued, resulting in incomplete traces with missing cost data, timing information, or metadata.

**Why it happens:**
- Langfuse SDK batches events for efficiency (default: flush every 10 events or 10 seconds)
- Streaming responses return immediately while background threads are still processing
- Developers assume decorators like `@observe()` handle everything automatically
- The `langfuse_context.update_current_trace()` is called but never flushed before response completes

**How to avoid:**
- **Always** call `langfuse.flush()` after `update_current_trace()` and before returning streaming responses
- Use explicit flush in FastAPI streaming endpoints: `langfuse_context.update_current_trace(...); langfuse.flush()`
- In serverless/short-lived contexts, use `langfuse.shutdown()` instead of `flush()` to ensure all pending requests complete
- Add a finally block to guarantee flush even on errors

**Warning signs:**
- Traces appear in Langfuse but metadata fields are empty or `null`
- Cost calculations show $0.00 despite successful completions
- Session IDs missing from traces that should have them
- Intermittent data loss (appears sometimes but not always)
- Logs show "queued N events" but traces are incomplete

**Phase to address:**
Phase 1 (Core Metadata Infrastructure) - Must establish reliable flush pattern before adding complex metadata

**Real-world example:**
```python
# WRONG - metadata gets lost
langfuse_context.update_current_trace(
    metadata={"cost": calculated_cost, "session_id": session_id}
)
return VercelStreamResponse(...)  # Returns immediately, flush never happens

# CORRECT - flush before returning
langfuse_context.update_current_trace(
    metadata={"cost": calculated_cost, "session_id": session_id}
)
langfuse.flush()  # Ensure data is sent
return VercelStreamResponse(...)
```

---

### Pitfall 2: Token Count Mismatches Breaking Cost Calculations

**What goes wrong:**
Cost tracking becomes unreliable or completely wrong because token counts from different sources don't match. Model definitions expect specific usage_detail keys (e.g., `input`, `output`) but the integration sends different keys (e.g., `prompt_tokens`, `completion_tokens`). Cost multiplies by wrong token counts, or pricing tier conditions fail to match because the token field names differ.

**Why it happens:**
- Different LLM providers use different token count field names
- Langfuse model definitions expect exact key matches for cost calculation
- OpenAI SDK returns `usage.prompt_tokens` but custom models expect `usage_details.input`
- Cached tokens, reasoning tokens, and audio tokens have provider-specific naming
- Copy-pasting token tracking code without understanding the schema mismatch

**How to avoid:**
- **Normalize token counts to Langfuse schema** before ingesting: `input`, `output`, `total`
- Use OpenAI-compatible schema for provider-neutral tracking, then let Langfuse map to internal schema
- For provider-specific fields (cached tokens, reasoning tokens), use consistent prefixes: `input_cached_tokens`, `output_reasoning_tokens`
- Create helper function to transform provider response → Langfuse usage_details schema
- Document token field mappings for each of the 7 providers in a central location
- Verify model definitions in Langfuse UI match the keys you're sending

**Warning signs:**
- Cost shows $0.00 despite tokens being tracked
- Cost dashboards show wildly inaccurate numbers (10x off)
- Some providers track cost correctly, others don't
- Model definition warnings in Langfuse logs about missing keys
- Token counts appear in metadata but not in cost calculations
- Pricing tiers don't activate despite meeting token thresholds

**Phase to address:**
Phase 1 (Core Metadata Infrastructure) - Token normalization must work before building cost tracking on top

**Real-world example:**
```python
# WRONG - provider-specific field names
langfuse_context.update_current_trace(
    usage_details={
        "prompt_tokens": 100,  # Model definition expects "input"
        "completion_tokens": 50,  # Model definition expects "output"
        "cached_prompt_tokens": 20  # Won't match pricing tier conditions
    }
)

# CORRECT - normalized to Langfuse schema
langfuse_context.update_current_trace(
    usage_details={
        "input": response.usage.prompt_tokens,
        "output": response.usage.completion_tokens,
        "input_cached_tokens": response.usage.prompt_tokens_details.cached_tokens,
        "total": response.usage.total_tokens
    }
)
```

---

### Pitfall 3: Session ID Propagation Failures in Multi-Turn Conversations

**What goes wrong:**
Session tracking breaks silently across conversation turns. First message gets session_id, but subsequent messages in the same conversation lose it. Analytics show thousands of 1-message "sessions" instead of actual multi-turn conversations. Session-level metrics become meaningless because traces aren't grouped correctly.

**Why it happens:**
- `propagate_attributes()` context manager must wrap EVERY observation that should inherit session_id
- Async context switching loses propagated attributes between await calls
- Session ID set on root trace but not propagated to child generations/spans
- Frontend generates new session ID per request instead of persisting across conversation
- Anonymous user fingerprinting changes between requests (browser fingerprint drift)
- Called `propagate_attributes()` too late in trace lifecycle - child observations already created

**How to avoid:**
- **Call `propagate_attributes()` as early as possible** in request handler, before any child observations
- Wrap entire request processing in propagate context: `with propagate_attributes(session_id=..., user_id=...)`
- For anonymous users, generate stable fingerprint-based session ID on first request, persist in client localStorage
- Validate session ID format (max 200 chars, US-ASCII only) before propagating to avoid silent drops
- Use middleware to inject session_id at request level for all endpoints
- Log session_id at request start to verify propagation

**Warning signs:**
- Session view in Langfuse shows mostly single-message sessions
- Conversation history works in app but doesn't appear grouped in Langfuse
- Session-level cost aggregation shows incorrect totals
- User journey analysis is impossible because turns are disconnected
- Session filters in Langfuse return no results
- Some traces have session_id, others in same conversation don't

**Phase to address:**
Phase 2 (Session Management) - Core infrastructure must be solid before tackling sessions

**Real-world example:**
```python
# WRONG - session_id set too late, generations already created
@observe()
async def chat_endpoint(message: str):
    chat_response = await chat_engine.achat(message)  # Generation already created
    with propagate_attributes(session_id="session-123"):  # Too late!
        langfuse_context.update_current_trace(...)
    return chat_response

# CORRECT - propagate early, wrap entire processing
@observe()
async def chat_endpoint(message: str, session_id: str):
    with propagate_attributes(session_id=session_id, user_id=user_id):
        # All observations created here inherit session_id
        chat_response = await chat_engine.achat(message)
        langfuse_context.update_current_trace(...)
    return chat_response
```

---

### Pitfall 4: Metadata Size Explosion Causing Performance Degradation

**What goes wrong:**
Adding comprehensive metadata tracking causes request latency to increase from 10ms to 200ms+. Trace ingestion API calls time out. Langfuse dashboard becomes slow to load. Storage costs increase unexpectedly. The overhead of observability exceeds the stated <50ms constraint.

**Why it happens:**
- Storing entire retrieved document content in metadata (can be 100KB+ per trace)
- Including full conversation history in every trace update
- Serializing large Python objects (LangChain chains, LlamaIndex indices) into metadata
- Not using references/IDs - duplicating data instead
- Geo-data API calls adding 50-100ms per request without caching
- Synchronous metadata enrichment blocking the response path

**How to avoid:**
- **Store references, not content**: Use document IDs, not full text
- Set metadata size limits: max 10KB per trace, 2KB per metadata field
- Use Langfuse's built-in fields (input, output) for prompts/responses, not metadata
- Store large payloads (retrieved docs) in separate storage, link by ID in metadata
- Move expensive enrichment (geo-lookup, fingerprinting) to background tasks
- Cache frequently-accessed enrichment data (geo-location for IP, model definitions)
- Profile metadata serialization time - don't serialize complex objects

**Warning signs:**
- P95 latency increases after adding metadata tracking
- Langfuse API returns 413 (Payload Too Large) errors
- Traces take 5+ seconds to appear in Langfuse UI
- Browser DevTools shows multi-megabyte trace payloads
- Cost per trace increases significantly
- Background worker queues backing up
- Memory usage spikes during trace finalization

**Phase to address:**
Phase 1 (Core Metadata Infrastructure) - Set size limits from the start, before adding rich metadata

**Real-world example:**
```python
# WRONG - storing massive objects in metadata
enhanced_metadata = {
    "retrieved_docs": retrieved,  # 100KB+ of document content
    "conversation_history": messages,  # Full 50-turn conversation
    "geo_data": await get_geo_data(ip),  # Blocks for 80ms
    "llama_index_node": node.dict()  # Serializes entire index
}

# CORRECT - references and essential data only
enhanced_metadata = {
    "retrieved_doc_ids": [node.node_id for node in nodes],  # Just IDs
    "conversation_turn": turn_number,  # Count, not content
    "country": geo_cache.get(ip, {}).get("country"),  # Cached, non-blocking
    "node_count": len(nodes)  # Summary stats only
}
```

---

### Pitfall 5: Race Conditions in Multi-Provider Token Counting

**What goes wrong:**
Cost tracking intermittently shows wrong values or fails completely when using multiple LLM providers. Same prompt costs $0.01 with OpenAI, $0.00 with Anthropic, $0.15 with Google. Token counts are sometimes correct, sometimes zero, for the same provider. Model definition lookup fails unpredictably.

**Why it happens:**
- Model definitions cached but not invalidated when adding new custom models
- Race condition: token counting happens before model definition is registered in Langfuse
- Different providers have different tokenizer initialization times (tiktoken vs Anthropic)
- Model name matching fails because of version suffixes (`gpt-4o-2024-11-20` vs `gpt-4o`)
- Relying on inference when provider returns tokens - should always use provider data
- Provider wrappers (LlamaIndex, LangChain) strip token counts before they reach Langfuse

**How to avoid:**
- **Always ingest token counts from provider response**, never rely on inference for production
- Use regex-based model matching in model definitions to handle versioned model names
- Register model definitions before deploying code that uses them
- Create provider-agnostic token count extraction: `extract_tokens(provider, response) -> UsageDetails`
- Add fallback: if provider tokens unavailable, log warning and use inference as last resort
- For custom/self-hosted models, define pricing BEFORE using in production
- Test token tracking for each provider independently before combining

**Warning signs:**
- Cost varies for identical prompts with same provider
- Some traces show token counts, others show 0 for same model
- "Model not found" errors in Langfuse logs despite model being used
- Cost tracking works in staging, breaks in production
- Model definition changes don't reflect in live traces
- Different integrations (SDK vs LangChain) produce different token counts

**Phase to address:**
Phase 1 (Core Metadata Infrastructure) - Multi-provider foundation must be robust before scaling

**Real-world example:**
```python
# WRONG - relying on inference for multi-provider
def track_generation(response, model: str):
    # Inference might fail for custom models or versioned names
    langfuse_context.update_current_trace(model=model)
    # No usage_details - relying on Langfuse to infer

# CORRECT - extract from provider, with fallback
def track_generation(response, provider: str, model: str):
    usage = extract_usage_by_provider(provider, response)
    if not usage:
        logger.warning(f"Token counts unavailable for {provider}/{model}")
        usage = {"input": 0, "output": 0}  # Explicit fallback
    
    langfuse_context.update_current_trace(
        model=model,
        usage_details=usage,
        metadata={"provider": provider, "usage_source": "provider_response"}
    )
```

---

### Pitfall 6: DRY Violations Leading to Metadata Drift

**What goes wrong:**
Metadata tracking logic duplicated across multiple endpoints (`/api/chat`, `/api/chat/request`, `/thumbs_request`). One endpoint gets cost tracking update, others don't. Inconsistent metadata schema across traces makes analysis impossible. Different serialization logic produces incompatible data structures.

**Why it happens:**
- Copy-paste development: duplicate tracking code in each endpoint
- No shared abstraction for metadata enrichment
- Different developers implement tracking differently
- Streaming and non-streaming endpoints diverge over time
- Edge cases (blocked requests, errors) handled inconsistently
- Rush to ship features leads to "works for me" implementations

**How to avoid:**
- **Create single source of truth**: `MetadataTracker` class or decorator that all endpoints use
- Extract metadata enrichment into shared utility: `enrich_trace_metadata(trace_id, request, response)`
- Use FastAPI dependency injection to inject tracker into all endpoints
- Version your metadata schema and validate against it
- Write integration test that verifies metadata consistency across all endpoints
- Code review checklist: "Does this duplicate existing tracking logic?"

**Warning signs:**
- Same metadata field has different keys in different traces (`sessionId` vs `session_id` vs `session`)
- Query/filter syntax that works for one endpoint's traces fails for another
- Cost calculations accurate for `/chat` but missing for `/chat/request`
- Metadata schema documentation doesn't match reality
- Bug fixes to tracking logic need to be applied in multiple places
- Traces from different endpoints can't be analyzed together

**Phase to address:**
Phase 1 (Core Metadata Infrastructure) - Build shared abstraction from the start

**Prevention strategy:**
```python
# WRONG - duplicated tracking in each endpoint
@r.post("/chat")
async def chat(...):
    langfuse_context.update_current_trace(
        metadata={"user_language": detect_language(...), "geo": geo_data}
    )
    langfuse.flush()

@r.post("/chat/request")
async def chat_request(...):
    # Different metadata structure, different field names
    langfuse_context.update_current_trace(
        metadata={"language": detect_language(...)}  # Missing geo!
    )
    # Forgot to flush!

# CORRECT - shared metadata tracker
class MetadataTracker:
    @staticmethod
    async def enrich_trace(request, response, model, provider):
        metadata = {
            "user_language": LocalizationManager.detect_language(response),
            "geo": await get_geo_data(request.client.host),
            "provider": provider,
            "model": model,
        }
        langfuse_context.update_current_trace(metadata=metadata)
        langfuse.flush()

# Use in all endpoints consistently
@r.post("/chat")
async def chat(...):
    await MetadataTracker.enrich_trace(request, response, model, provider)
```

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip flush in non-critical endpoints | Faster development | 20-30% data loss, inconsistent metrics | Never - flush cost is minimal (~5ms) |
| Store full documents in metadata | Quick debugging | 10x storage cost, slow queries, timeouts | Only in dev/staging, never production |
| Hard-code provider names | Simple implementation | Breaks when adding providers, no extensibility | Only for MVP with single provider |
| Duplicate tracking logic per endpoint | Fast feature delivery | Inconsistent data, expensive refactoring | Acceptable for prototype, must refactor before production |
| Infer tokens instead of ingesting | No code changes needed | 5-10% cost calculation errors | Acceptable for providers that never return tokens |
| Use basic string session IDs | Simple implementation | No anonymous user support, poor UX | Acceptable if all users authenticate |
| Synchronous geo-lookup in request path | Simple code flow | +80ms latency per request | Never - always use background tasks or caching |
| Store cost in metadata instead of cost_details | Works for basic cases | Can't use Langfuse cost dashboards/alerting | Acceptable for MVP, must migrate to cost_details |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **FastAPI Streaming** | Returning response before flush completes | Always `langfuse.flush()` before `return VercelStreamResponse()` |
| **LlamaIndex** | Assuming callback handler auto-flushes | Explicitly call `langfuse.flush()` after each request |
| **Multiple Providers** | Using provider-specific token field names | Normalize to `{input, output, total}` schema before ingesting |
| **Anonymous Users** | Generating new session ID each request | Use stable browser fingerprint, persist in localStorage |
| **Geo-IP Lookup** | Calling API synchronously per request | Cache results by IP, use background task for new lookups |
| **Model Definitions** | Creating after code deployment | Register models in Langfuse UI BEFORE using in code |
| **Cost Tracking** | Mixing metadata cost with cost_details | Always use `cost_details`, never store cost in metadata |
| **Session Tracking** | Setting session_id after children created | Call `propagate_attributes()` at request entry point |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| **Synchronous Metadata Enrichment** | +50-200ms per request latency | Move geo-lookup, fingerprinting to background tasks | Every request immediately |
| **Unbounded Metadata Size** | Timeouts, 413 errors, slow dashboard | Enforce 10KB trace limit, 2KB field limit | >1000 daily active users |
| **Missing Flush in Streaming** | Intermittent data loss | Always flush before returning streaming response | 30% of streaming requests |
| **Excessive Model Definition Lookups** | Slow cost calculation | Cache model definitions, use regex matching | >10K requests/day |
| **Duplicate Token Counting** | CPU spikes during tracing | Ingest from provider, disable inference | >5K requests/day |
| **Geo API Rate Limits** | Request failures during traffic spikes | Cache by IP with TTL, implement fallback | Traffic > API rate limit |
| **Metadata JSON Serialization** | Memory pressure, GC pauses | Use primitive types, avoid complex objects | Large traces (>50 metadata fields) |
| **Cost Calculation on Every Request** | High CPU usage | Pre-calculate in background, cache results | >1K concurrent users |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| **Storing PII in Metadata** | GDPR violations, data breach liability | Never store emails, IPs, names in metadata; use hashed user IDs |
| **Leaking API Keys in Traces** | Credential compromise | Sanitize all inputs/outputs before ingesting to Langfuse |
| **Verbose Error Messages** | Information disclosure | Sanitize stack traces, don't include system paths in metadata |
| **Unvalidated Session IDs** | Injection attacks, XSS | Validate format (alphanumeric only), max 200 chars |
| **Storing Retrieved Documents** | PII exposure, copyright issues | Store document IDs/hashes only, not content |
| **Exposing Internal Model Names** | Architecture disclosure | Use public-facing model aliases in metadata |
| **Trace URLs in Logs** | Access token leakage | Never log full trace URLs (contain access tokens) |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| **Slow Response Due to Metadata** | Users experience 2x slower responses | Move all tracking to background, never block response |
| **Failed Requests Due to Tracking Errors** | Application breaks when Langfuse is down | Wrap tracking in try-except, gracefully degrade |
| **Missing Context in Support** | Support can't debug user issues | Always track session_id and user_id for support queries |
| **Inconsistent Cost Reporting** | Users confused by billing | Ensure cost tracking is accurate across all providers |
| **Lost Conversation History** | Users repeat themselves | Session tracking must be bulletproof for multi-turn UX |

---

## "Looks Done But Isn't" Checklist

- [ ] **Cost Tracking:** Verify ALL providers return token counts - don't assume inference works
- [ ] **Session Management:** Test anonymous user flows - authenticated users are easy mode
- [ ] **Metadata Flush:** Check streaming endpoints - non-streaming is easy, streaming loses data
- [ ] **Multi-Provider:** Test provider switching mid-session - single provider is not representative
- [ ] **Error Paths:** Verify tracking works for failed/blocked requests - success path is incomplete
- [ ] **Latency:** Profile with realistic traffic - works fine at 1 req/sec, breaks at 100 req/sec
- [ ] **Token Normalization:** Test versioned model names - base model names aren't sufficient
- [ ] **Geo-IP Caching:** Verify cache hit rate >95% - no cache = API rate limit death
- [ ] **Model Definitions:** Test custom models and self-hosted - public APIs are easy mode
- [ ] **Background Tasks:** Verify tasks complete during traffic spikes - works fine at low load
- [ ] **Session Propagation:** Test async/streaming contexts - synchronous endpoints are misleading
- [ ] **Metadata Size:** Test with realistic document retrieval - toy examples don't reveal issues

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| **Missing Flushes (Data Loss)** | LOW | 1. Add flush calls to all endpoints 2. Deploy 3. No backfill possible - data is lost |
| **Token Field Mismatch** | MEDIUM | 1. Create token normalization helper 2. Update all endpoints 3. Backfill costs via batch job |
| **Session ID Not Propagated** | HIGH | 1. Refactor to propagate early 2. Can't retroactively group traces - historical data broken |
| **Metadata Too Large** | MEDIUM | 1. Add size limits 2. Migrate to references 3. May need Langfuse support to delete oversized traces |
| **Multi-Provider Race Conditions** | MEDIUM | 1. Always ingest provider tokens 2. Add model definitions 3. Backfill costs from logs if available |
| **DRY Violations** | HIGH | 1. Extract shared module 2. Refactor all endpoints 3. Write integration tests 4. Requires careful migration |
| **PII in Metadata** | CRITICAL | 1. Stop ingestion immediately 2. Contact Langfuse to purge data 3. May require legal notification |
| **Performance Regression** | LOW | 1. Move to background tasks 2. Add caching 3. Immediate deployment possible |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Missing Flushes | Phase 1: Core Infrastructure | Integration test: streaming endpoint + verify trace complete |
| Token Count Mismatches | Phase 1: Core Infrastructure | Test: verify cost matches expected for each provider |
| Session Propagation | Phase 2: Session Management | Test: multi-turn conversation shows in single session view |
| Metadata Size Explosion | Phase 1: Core Infrastructure | Load test: P95 latency <50ms with metadata enabled |
| Multi-Provider Races | Phase 1: Core Infrastructure | Test: sequential requests across all 7 providers succeed |
| DRY Violations | Phase 1: Core Infrastructure | Code review: zero duplication in metadata tracking |
| Synchronous Enrichment | Phase 3: Performance Measurement | Performance test: geo-lookup doesn't block response |
| Model Definition Missing | Phase 1: Core Infrastructure | Pre-deployment checklist: models exist in Langfuse |
| PII in Metadata | Phase 1: Core Infrastructure | Security review: no PII fields in metadata schema |
| Inconsistent Schemas | Phase 1: Core Infrastructure | Schema validation test: all endpoints produce compatible metadata |

---

## Sources

### Official Documentation (HIGH Confidence)
- Langfuse Token & Cost Tracking: https://langfuse.com/docs/observability/features/token-and-cost-tracking
  - Usage details schema and provider compatibility
  - Model definition pricing tiers
  - Cost inference behavior
- Langfuse Sessions: https://langfuse.com/docs/observability/features/sessions
  - Session ID propagation requirements
  - 200-character limit and US-ASCII constraint
- Langfuse Event Queuing: https://langfuse.com/docs/observability/features/queuing-batching
  - Flush behavior and manual flushing requirements
  - Serverless/streaming context warnings
- Langfuse Troubleshooting: https://langfuse.com/docs/observability/sdk/troubleshooting-and-faq
  - Common integration issues
  - Missing traces diagnosis

### Codebase Analysis (HIGH Confidence)
- `/backend/app/api/routers/chat.py`
  - Current metadata tracking implementation
  - Flush patterns in streaming vs non-streaming endpoints
  - Geo-data and security metadata structure
- `/backend/app/langfuse.py`
  - Langfuse client configuration
  - Integration patterns
- `/backend/app/settings.py`
  - Multi-provider configuration (7 providers: OpenAI, Groq, Ollama, Anthropic, Gemini, Mistral, Azure)
  - Model and embedding configuration

### Domain Expertise (MEDIUM Confidence)
- FastAPI async/streaming context behavior with background tasks
- LlamaIndex callback handler integration patterns
- Browser fingerprinting stability challenges
- Common cost tracking pitfalls from LLM application operations

### Known Gaps
- Specific error rates for each pitfall (would need production metrics)
- Exact latency impact of each metadata enrichment operation (needs profiling)
- Langfuse model definition cache invalidation timing (not documented)
- Maximum safe metadata size before performance degradation (needs load testing)

---

*Research confidence assessment:*
- **Token/Cost Tracking Pitfalls:** HIGH - Based on official docs and clear API contracts
- **Session Management Pitfalls:** HIGH - Official docs explicit about requirements
- **Performance Pitfalls:** MEDIUM - Based on patterns but needs load testing validation
- **Multi-Provider Pitfalls:** MEDIUM - Inferred from provider documentation and codebase structure
- **Integration Pitfalls:** HIGH - Based on codebase analysis and official troubleshooting docs
