This is a [LlamaIndex](https://www.llamaindex.ai/) project using [Next.js](https://nextjs.org/) bootstrapped with [`create-llama`](https://github.com/run-llama/LlamaIndexTS/tree/main/packages/create-llama).

## Getting Started

Install dependencies:

```
npm install
```

Copy `.env.local.example` to `.env.local` and fill in the required values:

```
cp .env.local.example .env.local
```

Run the development server:

```
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_CHAT_API` | Yes | Backend base URL (e.g. `http://localhost:8000`) |
| `NEXT_PUBLIC_API_KEY` | Yes | API key matching backend `API_KEYS` |
| `NEXT_PUBLIC_SENTRY_DSN` | No | Sentry DSN for frontend error tracking |

> **Note:** `NEXT_PUBLIC_*` variables are baked into the bundle at build time. On Render, they must be set as **Build environment variables**, not just runtime variables.

## API Routes Used

All requests go to the backend at `NEXT_PUBLIC_CHAT_API`:

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/chat` | Streaming chat |
| `GET /api/v1/chat/config` | Load frontend config |
| `POST /api/v1/chat/upload` | File uploads |
| `POST /api/v1/chat/thumbs_request` | Thumbs up/down feedback |
| `POST /api/v1/chat/feedback/general` | General feedback with screenshot |

## Security Headers

The following headers are set on all responses via `next.config.json`:

- `Content-Security-Policy` — restricts resource loading
- `X-Frame-Options: DENY` — prevents clickjacking
- `X-Content-Type-Options: nosniff` — prevents MIME sniffing

## Error Tracking

Sentry is configured for frontend error tracking in production. Set `NEXT_PUBLIC_SENTRY_DSN` to enable it. Errors are only reported when `NEXT_PUBLIC_SENTRY_DSN` is present.

## Deployment (Render)

Build command: `npm run build` (via Dockerfile)

Required Render environment variables:
```
NEXT_PUBLIC_CHAT_API=https://your-backend.onrender.com
NEXT_PUBLIC_API_KEY=your_api_key
NEXT_PUBLIC_SENTRY_DSN=your_sentry_dsn
```
