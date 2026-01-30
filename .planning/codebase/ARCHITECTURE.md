# Architecture

**Analysis Date:** 2026-01-30

## Pattern Overview

**Overall:** Monorepo with Client-Server Architecture + RAG (Retrieval-Augmented Generation)

**Key Characteristics:**
- Frontend: Next.js 15 React SPA with server-side rendering
- Backend: FastAPI Python REST API with streaming support
- Communication: REST API with streaming responses via Vercel AI SDK
- AI Layer: LlamaIndex RAG pipeline with Pinecone vector store
- Security-First: Multi-layer input validation with risk scoring

## Layers

**Presentation Layer (Frontend):**
- Purpose: User interface for chatbot interaction
- Location: `frontend/app/`
- Contains: React components, UI state management, API client logic
- Depends on: Backend REST API (`/api/chat`)
- Used by: End users (missionaries)
- Technology: Next.js 15 App Router, React hooks, Vercel AI SDK

**API Layer (Backend):**
- Purpose: Request routing, security validation, response orchestration
- Location: `backend/app/api/routers/`
- Contains: FastAPI routers (`chat.py`, `chat_config.py`, `upload.py`), request/response models
- Depends on: Engine layer, security layer, utils
- Used by: Frontend via HTTP/HTTPS
- Pattern: Router-based modular design with dependency injection

**Security Layer:**
- Purpose: Input validation, prompt injection prevention, risk assessment
- Location: `backend/app/security/`
- Contains: `InputValidator` class with multilingual pattern matching
- Depends on: Localization utils, pytector library
- Used by: API routers (pre-processing)
- Pattern: Class-based validators with risk scoring (LOW/MEDIUM/CRITICAL)

**Engine Layer (AI Core):**
- Purpose: RAG query engine, document retrieval, response generation
- Location: `backend/app/engine/`
- Contains: Chat engine initialization, vector store interface, query filters, node postprocessors
- Depends on: LlamaIndex framework, vector store, LLM providers
- Used by: API layer for chat operations
- Pattern: Factory pattern for chat engine creation (`get_chat_engine()`)

**Data Layer:**
- Purpose: Vector embeddings storage and retrieval
- Location: External (Pinecone cloud)
- Interface: `backend/app/engine/vectordb.py`
- Contains: Document embeddings indexed by metadata (role, URL, sequence)
- Accessed by: Engine layer via LlamaIndex abstractions

**Utility Layer:**
- Purpose: Cross-cutting concerns (localization, geo-IP, monitoring)
- Location: `backend/app/utils/`, `backend/app/middleware/`
- Contains: Localization manager, geo-IP lookup, monitoring middleware
- Depends on: External services (IP geolocation API)
- Used by: All layers

## Data Flow

**Chat Request Flow (Streaming):**

1. **User Input** → Frontend `ChatSection` component captures input
2. **API Call** → Vercel AI SDK (`useChat` hook) POSTs to `${backend}/api/chat`
3. **Security Check** → `InputValidator.validate_input_security_async()` analyzes input
   - Length validation (max 500 chars)
   - Pattern matching (system prompts, injection attempts)
   - ML-based detection (pytector)
   - Risk scoring and blocking if MEDIUM/CRITICAL
4. **Geo-Location** → Extract client IP, fetch geo data for monitoring
5. **Query Preparation** → Extract role (missionary/ACM), generate metadata filters
6. **Engine Creation** → `get_chat_engine()` initializes:
   - Vector store connection (Pinecone)
   - Retriever with filters (role-based document access)
   - Chat memory buffer (conversation context)
   - Node postprocessors (citation injection)
7. **Retrieval** → Retriever fetches top-k similar nodes from vector store
8. **LLM Generation** → Custom condense+context chat engine:
   - Condense follow-up question with conversation history
   - Generate response using retrieved context
   - Stream tokens asynchronously
9. **Response Streaming** → `VercelStreamResponse` formats stream with:
   - Message tokens
   - Source citations
   - Suggested questions
   - Annotations
10. **Observability** → Langfuse captures trace with metadata (security, geo, sources)
11. **Client Rendering** → Frontend receives stream, renders markdown with citations

**State Management:**
- Frontend: React state (`useState`, `useChat` hook manages messages)
- Backend: Stateless per-request (chat memory scoped to request lifecycle)
- Conversation Context: In-memory buffer (token-limited, 8000 tokens)

## Key Abstractions

**Chat Engine (`CustomCondensePlusContextChatEngine`):**
- Purpose: Orchestrates RAG pipeline with conversation history
- Examples: `backend/app/engine/__init__.py`, `backend/app/engine/custom_condense_plus_context.py`
- Pattern: Extends LlamaIndex `CondensePlusContextChatEngine` with custom prompts
- Lifecycle: Created per-request, reset after response

**Input Validator:**
- Purpose: Security gate for all user input
- Examples: `backend/app/security/input_validator.py`
- Pattern: Class methods with pattern matching and ML detection
- Returns: `(is_suspicious, blocked_message, details)` tuple

**Vector Store Interface:**
- Purpose: Abstract vector database operations
- Examples: `backend/app/engine/vectordb.py` (Pinecone implementation)
- Pattern: Factory function returning LlamaIndex `PineconeVectorStore`

**Message Models:**
- Purpose: Type-safe API contracts
- Examples: `backend/app/api/routers/models.py` (`ChatData`, `Message`, `Result`)
- Pattern: Pydantic models with validation

**Localization Manager:**
- Purpose: Multilingual response generation
- Examples: `backend/app/utils/localization.py`
- Pattern: Static class methods with language detection

## Entry Points

**Frontend:**
- Location: `frontend/app/page.tsx`
- Triggers: User navigates to application root
- Responsibilities: Renders main layout with `Header` and `ChatSection`

**Backend:**
- Location: `backend/main.py`
- Triggers: `python main.py` or `uvicorn main:app`
- Responsibilities:
  - Initialize FastAPI app
  - Configure CORS (dev mode)
  - Mount static file routes
  - Register API routers
  - Initialize observability (Phoenix, Langfuse)
  - Start monitoring middleware and scheduler
  - Lifecycle hooks (startup: memory trimmer, shutdown: HTTP client cleanup)

**API Endpoints:**
- `POST /api/chat` → Streaming chat (`backend/app/api/routers/chat.py::chat()`)
- `POST /api/chat/request` → Non-streaming chat (`chat_request()`)
- `GET /api/chat/config` → Client configuration
- `POST /api/chat/upload` → File upload
- `POST /api/chat/thumbs_request` → User feedback

**Data Ingestion:**
- Location: `backend/app/engine/generate.py`
- Triggers: Manual CLI (`poetry run generate`)
- Responsibilities: Load documents, create embeddings, store in Pinecone

## Error Handling

**Strategy:** Layered error handling with graceful degradation

**Patterns:**
- **Security Errors:** Return localized message as normal response (not HTTP error)
  - Blocked inputs generate assistant message explaining refusal
  - Logged to Langfuse with `security_blocked: True` metadata
- **API Errors:** Raise `HTTPException` with appropriate status codes
  - 400 for validation errors
  - 500 for server/engine errors
  - Full traceback logged via `logger.exception()`
- **Frontend Errors:** Display alert dialog with error detail
  - `useChat` hook's `onError` callback parses JSON error
- **LLM Errors:** Try-catch in chat engine, fallback to error message
- **Cleanup:** `finally` blocks ensure chat engine memory reset

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module (uvicorn logger)
- Levels: INFO (normal ops), WARNING (security blocks), ERROR (exceptions)
- Format: Structured logs with context (IP, risk level, trace ID)

**Validation:**
- Input: Security validation (length, patterns, ML detection)
- Type: Pydantic models for API requests/responses
- Runtime: FastAPI dependency injection validates schemas

**Authentication:**
- Approach: None (application-level auth not implemented)
- Access Control: Role-based document filtering (missionary/ACM)
- IP Tracking: Geo-location logged for monitoring

**Observability:**
- Tracing: Langfuse `@observe` decorator on all API endpoints
- Metrics: Custom monitoring middleware tracks memory/performance
- OpenTelemetry: Phoenix integration for LLM spans

**Memory Management:**
- Periodic malloc_trim (every 5 minutes) returns freed memory to OS
- Chat engine reset after each request
- Token-limited conversation buffer (8000 tokens)

**Localization:**
- Language Detection: `LocalizationManager.detect_language()`
- Supported: English, Spanish, French, German, Portuguese, Russian
- Context: Security messages, UI labels, error responses

---

*Architecture analysis: 2026-01-30*
