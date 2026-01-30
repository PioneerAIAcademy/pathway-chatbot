# Technology Stack

**Analysis Date:** 2026-01-30

## Languages

**Primary:**
- TypeScript 5.3.2 - Frontend application (Next.js)
- Python >=3.11,<3.13 - Backend API (FastAPI)

**Secondary:**
- JavaScript - Build configuration and tooling

## Runtime

**Frontend Environment:**
- Node.js v22.21.0
- Next.js 15.3.6

**Backend Environment:**
- Python 3.12.3
- FastAPI 0.109.1
- Uvicorn 0.23.2 (with standard extras)
- Gunicorn 21.2.0 (production server with UvicornWorker)

**Package Manager:**
- Frontend: npm 11.6.3
  - Lockfile: `frontend/package-lock.json` (present)
- Backend: Poetry 1.8.2
  - Lockfile: `backend/poetry.lock` (present)

## Frameworks

**Core:**
- Next.js 15.3.6 - React framework with App Router
- React 18.2.0 - UI library
- FastAPI 0.109.1 - Python web framework
- LlamaIndex 0.10.58 - LLM orchestration framework
- LlamaIndex Core 0.10.58 - Core abstractions

**UI Components:**
- Radix UI primitives (Collapsible, HoverCard, Select, Slot)
- Tailwind CSS 3.3.6 - Utility-first CSS framework
- Lucide React 0.294.0 - Icon library
- Vaul 0.9.1 - Drawer component

**Testing:**
- pytest 8.4.2 - Python testing framework

**Build/Dev:**
- Webpack - Custom webpack config (`frontend/webpack.config.mjs`)
- PostCSS 8.4.32 - CSS processing
- Autoprefixer 10.4.16 - CSS vendor prefixing
- tsx 4.7.2 - TypeScript execution
- cross-env 7.0.3 - Cross-platform environment variables

**Linting/Formatting:**
- ESLint 8.55.0 with Next.js config (14.2.4)
- Prettier 3.2.5 with organize-imports plugin 3.2.4
- eslint-config-prettier 8.10.0 - ESLint/Prettier integration

## Key Dependencies

**Critical:**
- llamaindex 0.5.17 (frontend) - LlamaIndex TypeScript SDK
- llama-index 0.10.58 (backend) - Python LLM framework
- llama-index-vector-stores-pinecone 0.1.3 - Vector storage integration
- llama-index-agent-openai 0.2.6 - OpenAI agent support
- ai 3.0.21 - Vercel AI SDK
- langfuse 3.28.0 (frontend), 2.52.1 (backend) - LLM observability
- voyageai 0.2.3 - Voyage AI embeddings
- pytector 0.2.0 - Prompt injection detection
- spacy 3.7.5 + en_core_web_sm 3.7.1 - NLP library for security validation

**Infrastructure:**
- boto3 1.34.34 - AWS SDK for S3 uploads
- pinecone (via llama-index integration) - Vector database client
- httpx 0.27.0 - Async HTTP client
- requests 2.32.5 - HTTP client
- aiostream 0.5.2 - Async stream utilities
- python-dotenv 1.0.0 - Environment variable loading
- dotenv 16.3.1 (frontend) - Environment variable loading

**Data Processing:**
- pandas 2.1.4 - Data analysis library
- pyarrow 14.0.1 - Columnar data format
- scipy 1.14.1 - Scientific computing
- tiktoken 1.0.15 - Token counting for OpenAI models

**Monitoring & Observability:**
- arize-phoenix 5.5.2 - Phoenix observability platform
- arize-phoenix-otel 0.6.1 - OpenTelemetry integration
- openinference-instrumentation-llama-index >=2 - LlamaIndex instrumentation
- opentelemetry-proto >=1.12.0 - OpenTelemetry protocol
- psutil 5.9.8 - System monitoring

**Scheduling:**
- apscheduler 3.10.4 - Job scheduling for monitoring

**Document Processing:**
- docx2txt 0.8 - Word document parsing
- python-frontmatter 1.1.0 - Markdown frontmatter parsing
- @llamaindex/pdf-viewer 1.1.3 - PDF viewing component

**Utilities:**
- cachetools 5.3.3 - Caching utilities
- langdetect 1.0.9 - Language detection
- uuid 9.0.8 - UUID generation
- got 14.4.1 - HTTP client
- duck-duck-scrape 2.2.5 - DuckDuckGo web scraping
- formdata-node 6.0.3 - FormData implementation

**Markdown & Rendering:**
- react-markdown 8.0.7 - Markdown rendering
- react-syntax-highlighter 15.5.0 - Code syntax highlighting
- remark 14.0.3 - Markdown processor
- remark-gfm 3.0.1 - GitHub Flavored Markdown
- remark-math 5.1.1 - Math support
- remark-code-import 1.2.0 - Code import support
- rehype-katex 7.0.0 - KaTeX math rendering

**Development Tools:**
- jupyterlab 4.2.5 - Interactive development environment

## Configuration

**Environment:**
- Environment variables loaded via `python-dotenv` (backend) and `dotenv` (frontend)
- Config files: `backend/.env`, `frontend/.env`
- Examples provided: `backend/.env.example`, `frontend/.env.example`

**Key Backend Configs Required:**
- `MODEL_PROVIDER` - AI provider (openai/anthropic/groq/ollama/gemini/mistral/azure-openai/t-systems)
- `MODEL` - LLM model name
- `EMBEDDING_MODEL` - Embedding model name
- `EMBEDDING_DIM` - Embedding dimensions
- `OPENAI_API_KEY` - OpenAI API key (if using OpenAI)
- `PINECONE_API_KEY`, `PINECONE_ENVIRONMENT`, `PINECONE_INDEX_NAME` - Vector store config
- `VOYAGE_API_KEY` - Voyage AI embeddings
- `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` - Observability
- `GEOAPIFY_API_KEY` - IP geolocation service
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` - S3 monitoring uploads
- `MONITORING_S3_BUCKET`, `MONITORING_S3_PREFIX` - S3 monitoring config
- `ENABLE_MONITORING_S3_UPLOAD`, `ENABLE_MONITORING_HEARTBEAT` - Monitoring toggles

**Key Frontend Configs Required:**
- `NEXT_PUBLIC_CHAT_API` - Backend API URL (default: http://localhost:8000/api/chat)

**Build:**
- TypeScript config: `frontend/tsconfig.json` (strict mode enabled)
- Next.js config: `frontend/next.config.mjs` + `frontend/next.config.json`
- Tailwind config: `frontend/tailwind.config.ts`
- PostCSS config: `frontend/postcss.config.js`
- Prettier config: `frontend/prettier.config.js`
- Python config: `backend/pyproject.toml` (Poetry)

## Platform Requirements

**Development:**
- Node.js 22.x
- Python 3.11+ (tested with 3.12.3)
- Poetry 1.8.2
- npm 11.x

**Production:**
- Docker-based deployment (Dockerfile: `backend/Dockerfile`)
- Python 3.12-slim base image
- Gunicorn with UvicornWorker (1 worker, max 500 requests per worker)
- Worker rotation to prevent memory leaks
- Container includes Poetry and curl for installations
- Optional: Chromium for web loader (commented out by default)

**Development Container:**
- VS Code DevContainer available (`.devcontainer/devcontainer.json`)
- Base image: `mcr.microsoft.com/vscode/devcontainers/typescript-node:dev-20-bullseye`
- Includes Python 3.11, TypeScript, and development tools

---

*Stack analysis: 2026-01-30*
