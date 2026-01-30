# Codebase Structure

**Analysis Date:** 2026-01-30

## Directory Layout

```
pathway-chatbot/
├── backend/                # FastAPI Python backend
│   ├── app/               # Application code
│   │   ├── api/          # API layer
│   │   ├── engine/       # RAG engine
│   │   ├── security/     # Input validation
│   │   ├── middleware/   # Request middleware
│   │   ├── utils/        # Utilities
│   │   └── notebooks/    # Development notebooks
│   ├── tests/            # pytest test suite
│   ├── config/           # Configuration files
│   ├── docs/             # Backend documentation
│   ├── main.py           # Application entry point
│   ├── pyproject.toml    # Poetry dependencies
│   └── poetry.lock       # Locked dependencies
├── frontend/             # Next.js React frontend
│   ├── app/             # Next.js 15 app directory
│   │   ├── components/  # React components
│   │   ├── observability/ # Observability config
│   │   ├── layout.tsx   # Root layout
│   │   ├── page.tsx     # Home page
│   │   └── globals.css  # Global styles
│   ├── public/          # Static assets
│   ├── config/          # Configuration files
│   ├── docs/            # Frontend documentation
│   ├── package.json     # npm dependencies
│   └── tsconfig.json    # TypeScript config
├── docs/                # Project documentation
├── .planning/           # Planning documents
│   └── codebase/       # Codebase analysis docs
├── .devcontainer/       # Dev container config
├── AGENTS.md            # AI agent guidelines
├── GC_IMPLEMENTATION.md # Implementation docs
└── README.md            # Project overview
```

## Directory Purposes

**`backend/`:**
- Purpose: Python FastAPI server and AI engine
- Contains: API routers, RAG pipeline, security validation, utilities
- Key files: `main.py` (entry point), `pyproject.toml` (dependencies)

**`backend/app/api/`:**
- Purpose: API request handling and routing
- Contains: Router modules, request/response models, event handlers
- Key files: 
  - `routers/chat.py` (main chat endpoint)
  - `routers/models.py` (Pydantic models)
  - `routers/vercel_response.py` (streaming response formatter)

**`backend/app/api/routers/`:**
- Purpose: FastAPI route handlers
- Contains: Chat endpoints, config endpoints, upload handlers
- Key files:
  - `chat.py` (streaming and non-streaming chat)
  - `chat_config.py` (client configuration)
  - `upload.py` (file upload)

**`backend/app/api/services/`:**
- Purpose: Business logic services
- Contains: File service, suggestion service
- Key files:
  - `file.py` (file processing)
  - `suggestion.py` (question suggestions)

**`backend/app/engine/`:**
- Purpose: LlamaIndex RAG implementation
- Contains: Chat engine factory, vector store interface, query filters, node processors
- Key files:
  - `__init__.py` (chat engine factory)
  - `generate.py` (data ingestion script)
  - `vectordb.py` (Pinecone connection)
  - `index.py` (index loading)
  - `custom_condense_plus_context.py` (custom chat engine)
  - `query_filter.py` (metadata filtering)

**`backend/app/engine/loaders/`:**
- Purpose: Document loading utilities
- Contains: Web scraper, file loader
- Key files:
  - `web.py` (web content extraction)
  - `file.py` (file parsing)

**`backend/app/security/`:**
- Purpose: Security validation and threat detection
- Contains: Input validator with multilingual pattern matching
- Key files:
  - `input_validator.py` (security validation)
  - `__init__.py` (exports)

**`backend/app/middleware/`:**
- Purpose: FastAPI middleware components
- Contains: Monitoring middleware
- Key files:
  - `monitoring_middleware.py` (performance tracking)

**`backend/app/utils/`:**
- Purpose: Shared utilities
- Contains: Localization, geo-IP lookup
- Key files:
  - `localization.py` (multilingual support)
  - `geo_ip.py` (IP geolocation)

**`backend/tests/`:**
- Purpose: pytest test suite
- Contains: Security validation tests, integration tests
- Key files:
  - `test_security_validation.py` (unit tests)
  - `test_security_integration.py` (integration tests)

**`frontend/app/`:**
- Purpose: Next.js 15 application code
- Contains: Pages, components, styles, API client logic
- Key files:
  - `page.tsx` (home page)
  - `layout.tsx` (root layout with theme provider)

**`frontend/app/components/`:**
- Purpose: React component library
- Contains: Page components and reusable UI components
- Key files:
  - `chat-section.tsx` (main chat interface)
  - `header.tsx` (app header)
  - `mobile-settings.tsx` (mobile settings dialog)

**`frontend/app/components/ui/`:**
- Purpose: Reusable UI components
- Contains: Buttons, inputs, chat components
- Key files:
  - `button.tsx`, `input.tsx`, `select.tsx` (form controls)

**`frontend/app/components/ui/chat/`:**
- Purpose: Chat-specific components
- Contains: Message display, input handling, chat logic
- Key files:
  - `chat-messages.tsx` (message list)
  - `chat-input.tsx` (message input with ACM toggle)
  - `chat.interface.ts` (TypeScript interfaces)

**`frontend/app/components/ui/chat/chat-message/`:**
- Purpose: Message rendering components
- Contains: Message parts (markdown, sources, avatar, feedback)
- Key files:
  - `index.tsx` (message component)
  - `markdown.tsx` (markdown renderer)
  - `chat-sources.tsx` (citation display)
  - `UserFeedbackComponent.tsx` (thumbs up/down)

**`frontend/app/components/ui/chat/hooks/`:**
- Purpose: Custom React hooks
- Contains: Configuration, file handling, clipboard utilities
- Key files:
  - `use-config.ts` (backend URL configuration)
  - `use-file.ts` (file upload logic)
  - `use-copy-to-clipboard.tsx` (clipboard operations)

**`frontend/app/components/ui/chat/utils/`:**
- Purpose: Chat utility functions
- Contains: Localization helpers
- Key files:
  - `localization.ts` (frontend localization)

**`frontend/app/components/ui/chat/widgets/`:**
- Purpose: Interactive message widgets
- Contains: Custom UI elements in messages
- Key files:
  - `LlamaCloudSelector.tsx`, `WeatherCard.tsx`, `PdfDialog.tsx`

**`frontend/app/observability/`:**
- Purpose: Frontend observability configuration
- Contains: Tracing setup
- Key files:
  - `index.ts` (observability init)

## Key File Locations

**Entry Points:**
- `backend/main.py`: FastAPI application entry point
- `frontend/app/page.tsx`: Frontend home page
- `frontend/app/layout.tsx`: Root layout with providers

**Configuration:**
- `backend/.env`: Backend environment variables (API keys, model config)
- `frontend/.env`: Frontend environment variables (API URL)
- `backend/pyproject.toml`: Python dependencies and project metadata
- `frontend/package.json`: Node.js dependencies and scripts
- `frontend/tsconfig.json`: TypeScript compiler configuration
- `frontend/tailwind.config.ts`: Tailwind CSS configuration

**Core Logic:**
- `backend/app/api/routers/chat.py`: Chat endpoint with security and streaming
- `backend/app/engine/__init__.py`: Chat engine factory with prompts
- `backend/app/security/input_validator.py`: Security validation logic
- `frontend/app/components/chat-section.tsx`: Main chat UI orchestration

**Testing:**
- `backend/tests/test_security_validation.py`: Security validator tests
- `backend/tests/test_security_integration.py`: End-to-end security tests

**Styling:**
- `frontend/app/globals.css`: Global CSS styles
- `frontend/app/markdown.css`: Markdown-specific styles
- `frontend/app/components/ui/lib/utils.ts`: Tailwind utility helpers

## Naming Conventions

**Files:**
- Backend Python: `snake_case.py` (e.g., `input_validator.py`, `chat_config.py`)
- Frontend TypeScript: `kebab-case.tsx` or `kebab-case.ts` (e.g., `chat-section.tsx`, `use-config.ts`)
- React components: `kebab-case.tsx` with PascalCase exports
- Test files: `test_*.py` prefix (e.g., `test_security_validation.py`)

**Directories:**
- Backend: `snake_case` (e.g., `app/api/routers/`)
- Frontend: `kebab-case` (e.g., `app/components/ui/chat/`)
- Special: `__pycache__`, `.next`, `node_modules` (generated)

**Code:**
- Python classes: `PascalCase` (e.g., `InputValidator`, `CustomCondensePlusContextChatEngine`)
- Python functions/variables: `snake_case` (e.g., `get_chat_engine`, `risk_level`)
- Python constants: `UPPER_SNAKE_CASE` (e.g., `MAX_QUESTION_LENGTH`, `SYSTEM_CITATION_PROMPT`)
- TypeScript interfaces: `PascalCase` (e.g., `ChatConfig`, `Message`)
- React components: `PascalCase` (e.g., `ChatSection`, `MobileSettings`)
- TypeScript functions/variables: `camelCase` (e.g., `useClientConfig`, `hasStartedChat`)

## Where to Add New Code

**New Feature:**
- Primary code (backend): `backend/app/api/routers/{feature}.py` for API, `backend/app/engine/` for AI logic
- Primary code (frontend): `frontend/app/components/{feature}.tsx` for UI
- Tests: `backend/tests/test_{feature}.py`

**New API Endpoint:**
- Router: `backend/app/api/routers/{router_name}.py`
- Models: Add to `backend/app/api/routers/models.py` or create new model file
- Register: Import and include router in `backend/main.py`

**New React Component:**
- Shared UI: `frontend/app/components/ui/{component-name}.tsx`
- Page-level: `frontend/app/components/{component-name}.tsx`
- Chat-specific: `frontend/app/components/ui/chat/{component-name}.tsx`

**New Security Pattern:**
- Add pattern to `backend/app/security/input_validator.py` class constants
- Update tests in `backend/tests/test_security_validation.py`

**New LLM Provider:**
- Add init function to `backend/app/settings.py` (e.g., `init_provider_name()`)
- Update match statement in `init_settings()`
- Document in `.env.example`

**Utilities:**
- Backend: `backend/app/utils/{utility_name}.py`
- Frontend: `frontend/app/components/ui/chat/utils/{utility-name}.ts`
- Shared helpers (frontend): `frontend/app/components/ui/lib/utils.ts`

**New Middleware:**
- Implementation: `backend/app/middleware/{middleware_name}.py`
- Registration: Add to `backend/main.py` via `app.add_middleware()`

**New Hook:**
- Location: `frontend/app/components/ui/chat/hooks/use-{hook-name}.ts`
- Naming: `use{HookName}` function (e.g., `useConfig`, `useFile`)

## Special Directories

**`backend/.venv/`:**
- Purpose: Python virtual environment
- Generated: Yes (via `poetry install`)
- Committed: No (.gitignore)

**`frontend/node_modules/`:**
- Purpose: Node.js dependencies
- Generated: Yes (via `npm install`)
- Committed: No (.gitignore)

**`frontend/.next/`:**
- Purpose: Next.js build output and cache
- Generated: Yes (during build/dev)
- Committed: No (.gitignore)

**`backend/__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes (automatic)
- Committed: No (.gitignore)

**`backend/tests/.pytest_cache/`:**
- Purpose: pytest cache for faster re-runs
- Generated: Yes (during test runs)
- Committed: No (.gitignore)

**`backend/monitoring_reports/`:**
- Purpose: Monitoring report storage
- Generated: Yes (by monitoring service)
- Committed: No (appears in .gitignore)

**`backend/config/`:**
- Purpose: Static configuration files
- Generated: No (manual)
- Committed: Yes

**`frontend/config/`:**
- Purpose: Static frontend configuration
- Generated: No (manual)
- Committed: Yes

**`frontend/public/`:**
- Purpose: Static assets (images, fonts, etc.)
- Generated: No (manual)
- Committed: Yes

**`frontend/out/`:**
- Purpose: Static export output (if used)
- Generated: Yes (via `npm run build` with static export)
- Committed: No

**`.planning/codebase/`:**
- Purpose: Codebase analysis documents
- Generated: Yes (by GSD mapping commands)
- Committed: Depends on workflow

**`.devcontainer/`:**
- Purpose: Development container configuration
- Generated: No (manual)
- Committed: Yes

---

*Structure analysis: 2026-01-30*
