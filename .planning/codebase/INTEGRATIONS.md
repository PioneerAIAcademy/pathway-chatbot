# External Integrations

**Analysis Date:** 2026-01-30

## APIs & External Services

**LLM Providers:**
- OpenAI - Primary LLM and embeddings provider
  - SDK/Client: `llama-index-llms-openai`, `llama-index-embeddings-openai`
  - Auth: `OPENAI_API_KEY`
  - Models: Configurable via `MODEL` env var (e.g., gpt-4o-mini)
  - Embeddings: Configurable via `EMBEDDING_MODEL` (e.g., text-embedding-3-large)
  
- Anthropic - Alternative LLM provider
  - SDK/Client: `llama-index-llms-anthropic`
  - Auth: Requires API key
  - Implementation: `backend/app/settings.py` (init_anthropic)

- Groq - Fast inference provider
  - SDK/Client: `llama-index-llms-groq`
  - Auth: Requires API key
  - Implementation: `backend/app/settings.py` (init_groq)

- Google Gemini - Google's LLM provider
  - SDK/Client: `llama-index-llms-gemini`, `llama-index-embeddings-gemini`
  - Auth: Requires API key
  - Implementation: `backend/app/settings.py` (init_gemini)

- Mistral AI - European LLM provider
  - SDK/Client: `llama-index-llms-mistralai`, `llama-index-embeddings-mistralai`
  - Auth: Requires API key
  - Implementation: `backend/app/settings.py` (init_mistral)

- Azure OpenAI - Enterprise OpenAI deployment
  - SDK/Client: `llama-index-llms-azure-openai`, `llama-index-embeddings-azure-openai`
  - Auth: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_LLM_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
  - Implementation: `backend/app/settings.py` (init_azure_openai)

- Ollama - Local/self-hosted LLM provider
  - SDK/Client: `llama-index-llms-ollama`, `llama-index-embeddings-ollama`
  - Auth: None (local)
  - Connection: `OLLAMA_BASE_URL` (default: http://127.0.0.1:11434)

- T-Systems LLM Hub - Enterprise LLM hub
  - SDK/Client: Custom integration via OpenAILike
  - Implementation: `backend/app/llmhub.py`

**Embeddings:**
- Voyage AI - Specialized embeddings provider
  - SDK/Client: `voyageai` 0.2.3
  - Auth: `VOYAGE_API_KEY`
  - Usage: `backend/app/engine/custom_condense_plus_context.py`
  - Client initialization: `voyageai.Client()` (auto-reads env var)

- FastEmbed - Local embeddings
  - SDK/Client: `llama-index-embeddings-fastembed`
  - Implementation: `backend/app/settings.py`

**Geolocation:**
- Geoapify - IP geolocation service
  - API: `https://api.geoapify.com/v1/ipinfo`
  - Auth: `GEOAPIFY_API_KEY`
  - Usage: `backend/app/utils/geo_ip.py`
  - Purpose: IP address lookup and location tracking

## Data Storage

**Databases:**
- Pinecone - Vector database
  - Connection: `PINECONE_API_KEY`, `PINECONE_ENVIRONMENT`, `PINECONE_INDEX_NAME`
  - Client: `llama-index-vector-stores-pinecone` 0.1.3
  - Implementation: `backend/app/engine/vectordb.py`
  - Purpose: Vector embeddings storage and similarity search

- Generic Database Support
  - Client: `llama-index-readers-database` (DatabaseReader)
  - Implementation: `backend/app/engine/loaders/db.py`
  - Purpose: Loading data from external databases via URI

**File Storage:**
- AWS S3 - Cloud object storage
  - Connection: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
  - Client: `boto3` 1.34.34
  - Bucket: `MONITORING_S3_BUCKET`
  - Prefix: `MONITORING_S3_PREFIX` (default: "metrics")
  - Usage: `backend/app/monitoring.py`
  - Purpose: Monitoring reports and metrics storage (Parquet files)
  - Toggle: `ENABLE_MONITORING_S3_UPLOAD` (true/false)
  - Heartbeat: `ENABLE_MONITORING_HEARTBEAT` (uploads JSON heartbeat every 5 minutes)

- Local Filesystem
  - Static files mounted at `/api/files/data` (DATA_DIR)
  - Tool outputs mounted at `/api/files/output`
  - Implementation: `backend/main.py`

**Caching:**
- In-memory caching via `cachetools` 5.3.3
- No external cache service (Redis/Memcached)

**Document Store:**
- SimpleDocumentStore - Local document storage
  - Implementation: `backend/app/engine/generate.py`
  - Part of LlamaIndex storage abstraction

## Authentication & Identity

**Auth Provider:**
- No dedicated authentication service detected
- API appears to be open or relies on external auth layer
- Security validation via custom `InputValidator` class
  - Prompt injection detection using `pytector` 0.2.0
  - Length validation (max 500 chars)
  - Risk level classification (LOW, MEDIUM, CRITICAL)
  - Implementation: `backend/app/security/input_validator.py`

## Monitoring & Observability

**LLM Observability:**
- Langfuse - LLM tracing and monitoring
  - SDK: `langfuse` 3.28.0 (frontend), 2.52.1 (backend)
  - Auth: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`
  - Host: `LANGFUSE_HOST` (e.g., https://us.cloud.langfuse.com)
  - Client initialization: `backend/app/langfuse.py`
  - Usage: `@observe` decorator, `langfuse_context`
  - Implementation: `backend/app/api/routers/chat.py`

- Phoenix (Arize) - OpenTelemetry observability
  - SDK: `arize-phoenix` 5.5.2, `arize-phoenix-otel` 0.6.1
  - Instrumentation: `openinference-instrumentation-llama-index` >=2
  - Protocol: `opentelemetry-proto` >=1.12.0
  - Implementation: `backend/app/observability.py` (currently no-op)

**Error Tracking:**
- No dedicated service (Sentry/Rollbar) detected
- Logging via Python's logging module

**Logs:**
- Uvicorn logger for backend
- Console logging throughout application
- Production: Gunicorn access logs to stdout

**System Monitoring:**
- Custom monitoring service
  - Tracks memory, performance, requests, errors
  - Generates Parquet reports
  - Uploads to S3 periodically
  - Implementation: `backend/app/monitoring.py`, `backend/app/middleware/monitoring_middleware.py`
  - Scheduler: APScheduler with cron/interval triggers
  - Metrics: Memory usage, response times, request counts, security blocks

## CI/CD & Deployment

**Hosting:**
- Render (inferred from memory optimization comments)
- Docker-based deployment
- Container: Python 3.12-slim with Poetry

**CI Pipeline:**
- No GitHub Actions workflows detected in `.github/workflows/`
- No CI configuration files found

**Build Process:**
- Backend: Poetry build system
- Frontend: Next.js build (`npm run build`)
- Docker: Multi-stage build (build → release)

**Production Server:**
- Gunicorn with UvicornWorker
- Configuration: 1 worker, max 500 requests, 120s timeout
- Worker rotation to prevent memory leaks

## Environment Configuration

**Required env vars:**

Backend critical:
- `MODEL_PROVIDER` - Which LLM provider to use
- `MODEL` - LLM model identifier
- `EMBEDDING_MODEL` - Embedding model identifier
- `OPENAI_API_KEY` or provider-specific key
- `PINECONE_API_KEY`, `PINECONE_ENVIRONMENT`, `PINECONE_INDEX_NAME`

Frontend critical:
- `NEXT_PUBLIC_CHAT_API` - Backend API endpoint

Optional but recommended:
- `VOYAGE_API_KEY` - Voyage embeddings
- `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` - Observability
- `GEOAPIFY_API_KEY` - IP geolocation
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` - S3 monitoring
- `MONITORING_S3_BUCKET`, `ENABLE_MONITORING_S3_UPLOAD` - S3 uploads
- `SYSTEM_PROMPT` - Custom system prompt
- `TOP_K` - Number of similar embeddings to retrieve
- `STREAM_TIMEOUT` - Response timeout in milliseconds

**Secrets location:**
- `.env` files (backend and frontend)
- Environment variables in deployment platform
- Not committed to git (in `.gitignore`)

## Webhooks & Callbacks

**Incoming:**
- Chat API endpoint: `/api/chat` (streaming responses)
- Upload endpoint: `/api/chat/upload` (file uploads)
- Config endpoint: `/api/chat/config` (configuration)
- No webhook endpoints detected

**Outgoing:**
- LLM provider API calls (OpenAI, Anthropic, etc.)
- Pinecone vector search API
- Voyage AI embeddings API
- Geoapify geolocation API
- S3 upload operations
- Langfuse tracing callbacks
- No external webhook notifications

## Data Loaders

**Web:**
- WholeSiteReader - Scrape entire websites
  - SDK: `llama-index-readers-web`
  - Implementation: `backend/app/engine/loaders/web.py`

**File:**
- SimpleDirectoryReader - Load files from directories
  - Implementation: `backend/app/engine/loaders/file.py`
- FlatReader - File reading utility
  - Implementation: `backend/app/api/services/file.py`

**Database:**
- DatabaseReader - Load data from databases
  - Implementation: `backend/app/engine/loaders/db.py`

## Security

**Input Validation:**
- pytector 0.2.0 - Prompt injection detection
- spacy 3.7.5 + en_core_web_sm 3.7.1 - NLP-based validation
- langdetect 1.0.9 - Language detection
- Custom risk scoring and pattern matching
- Implementation: `backend/app/security/input_validator.py`

---

*Integration audit: 2026-01-30*
