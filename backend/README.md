This is a [LlamaIndex](https://www.llamaindex.ai/) project using [FastAPI](https://fastapi.tiangolo.com/) bootstrapped with [`create-llama`](https://github.com/run-llama/LlamaIndexTS/tree/main/packages/create-llama).

## Getting Started

First, setup the environment with poetry: https://python-poetry.org/

> **_Note:_** This step is not needed if you are using the dev-container.

```
poetry install
poetry shell
```

Copy `.env.example` to `.env` and fill in the required values:

```
cp .env.example .env
```

Run the development server:

```
python main.py
```

## API Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/v1/chat` | Streaming chat | Yes |
| POST | `/api/v1/chat/request` | Non-streaming chat | Yes |
| GET | `/api/v1/chat/config` | Frontend config | No |
| POST | `/api/v1/chat/upload` | File upload | Yes |
| POST | `/api/v1/chat/thumbs_request` | Feedback thumbs | Yes |
| POST | `/api/v1/chat/feedback/general` | General feedback | Yes |
| GET | `/api/health` | Health check | No |
| GET | `/api/health/ready` | Readiness check | No |

Interactive API docs: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)

## Authentication

All protected endpoints require an `X-API-Key` header:

```
X-API-Key: your_api_key_here
```

Set valid keys in the `API_KEYS` environment variable (comma-separated for multiple keys).
In `dev` mode (`ENVIRONMENT=dev`), authentication is skipped.

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| POST `/api/v1/chat` | 10 requests/minute |
| POST `/api/v1/chat/request` | 10 requests/minute |
| POST `/api/v1/chat/feedback/*` | 30 requests/minute |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `PINECONE_API_KEY` | Yes | Pinecone vector store key |
| `ENVIRONMENT` | Yes | `dev` or `prod` |
| `API_KEYS` | Prod | Comma-separated valid API keys |
| `ALLOWED_ORIGINS` | Prod | Comma-separated allowed frontend URLs |
| `LANGFUSE_SECRET_KEY` | No | Langfuse observability key |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse public key |
| `VOYAGE_API_KEY` | No | Voyage AI embedding key |
| `GEOAPIFY_API_KEY` | No | Geoapify geo-IP key |

## Example curl

```bash
curl --location 'localhost:8000/api/v1/chat' \
--header 'Content-Type: application/json' \
--header 'X-API-Key: your_api_key_here' \
--data '{ "messages": [{ "role": "user", "content": "Hello" }] }'
```

## Production CORS

Set `ENVIRONMENT=prod` and `ALLOWED_ORIGINS` to restrict cross-origin requests:

```
ENVIRONMENT=prod
ALLOWED_ORIGINS=https://your-frontend.onrender.com
```
