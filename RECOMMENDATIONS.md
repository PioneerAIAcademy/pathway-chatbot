# Codebase Improvement Recommendations

**Prepared by:** Security & Architecture Review
**Date:** 2026-02-08
**Scope:** Medium-High Priority Items

This document outlines recommended improvements for the BYU Pathway Missionary Assistant codebase. Items are prioritized by security impact, reliability concerns, and implementation complexity.

---

## Priority Matrix

| Priority | Security Impact | Effort |
|----------|----------------|--------|
| P0 | Critical vulnerability | Hours-Days |
| P1 | High security/reliability risk | Days |
| P2 | Medium risk, best practice | Days-Week |
| P3 | Low risk, nice to have | Week+ |

---

## P0: Critical (Immediate Action)

### 1. Implement Rate Limiting

**Location:** `backend/main.py`
**Risk:** DoS attacks, resource exhaustion, abuse

The API has no request throttling. Any client can make unlimited requests, enabling:
- Denial of service attacks
- LLM cost explosion (each request costs money)
- Brute force attempts against security validation

**Recommended Implementation:**

```python
# Option 1: slowapi (simple, in-process)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/chat")
@limiter.limit("10/minute")  # 10 requests per minute per IP
async def chat(...):
    ...

# Option 2: Redis-backed (distributed, production-ready)
# Requires Redis instance but survives restarts and scales horizontally
```

**Suggested Limits:**
- `/api/chat`: 10 requests/minute per IP
- `/api/chat/thumbs_request`: 30 requests/minute per IP
- `/api/chat/feedback/general`: 5 requests/minute per IP

---

### 2. Add API Authentication

**Location:** `backend/main.py`, new `backend/app/auth/` module
**Risk:** Unauthorized access, no accountability, abuse

The API is completely public. Anyone with the URL can:
- Consume LLM resources at your expense
- Submit malicious feedback
- Probe security validation

**Recommended Implementation:**

```python
# Minimum viable: API key validation
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
VALID_API_KEYS = set(os.getenv("API_KEYS", "").split(","))

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key

@app.post("/api/chat")
async def chat(..., api_key: str = Depends(verify_api_key)):
    ...
```

**For production:** Consider OAuth2 or JWT with refresh tokens for user-facing deployments.

---

## P1: High Priority (This Sprint)

### 3. Sanitize Error Messages in Production

**Location:** `backend/app/api/routers/chat.py:201-207`
**Risk:** Information disclosure

Current code exposes exception details to clients:

```python
raise HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail=f"Error in chat engine: {e}",  # Leaks internal info
)
```

**Recommended Fix:**

```python
import os

def sanitize_error(e: Exception) -> str:
    if os.getenv("ENVIRONMENT") == "prod":
        return "An internal error occurred. Please try again."
    return str(e)

raise HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail=sanitize_error(e),
)
```

---

### 4. Validate CORS Origins Explicitly

**Location:** `backend/main.py:26-35`
**Risk:** CSRF-like attacks from malicious origins

Current code:

```python
if environment == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Wide open
        ...
    )
```

**Problem:** If `ENVIRONMENT` is unset or misconfigured, production runs with `allow_origins=["*"]`.

**Recommended Fix:**

```python
ALLOWED_ORIGINS = {
    "prod": [
        "https://pathway.byu.edu",
        "https://missionaries.prod.byu-pathway.psdops.com",
    ],
    "staging": [
        "https://staging.pathway.byu.edu",
    ],
    "dev": ["*"],
}

environment = os.getenv("ENVIRONMENT", "prod")  # Default to restrictive
origins = ALLOWED_ORIGINS.get(environment, ALLOWED_ORIGINS["prod"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    ...
)
```

---

### 5. Add Request Size Limits

**Location:** `backend/main.py`
**Risk:** Memory exhaustion, DoS

No limits on request body size. An attacker could send massive payloads.

**Recommended Fix:**

```python
from starlette.middleware.trustedhost import TrustedHostMiddleware

# Limit request body to 1MB
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 1_000_000:  # 1MB
        return JSONResponse(
            status_code=413,
            content={"detail": "Request too large"}
        )
    return await call_next(request)
```

Also limit conversation history length in `ChatData` model:

```python
class ChatData(BaseModel):
    messages: List[Message] = Field(..., max_items=50)  # Max 50 messages
```

---

### 6. Implement Structured Logging

**Location:** `backend/main.py`, all logging calls
**Risk:** Poor observability, difficult debugging

Current logging uses plain text, making it hard to parse and aggregate.

**Recommended Implementation:**

```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Apply to uvicorn logger
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger("uvicorn").handlers = [handler]
```

---

## P2: Medium Priority (Next Sprint)

### 7. Add Health Check Endpoint

**Location:** `backend/app/api/routers/health.py` (new file)
**Risk:** Poor operability, no load balancer integration

**Recommended Implementation:**

```python
from fastapi import APIRouter
from app.langfuse import langfuse
from app.engine import get_index

health_router = APIRouter()

@health_router.get("/health")
async def health_check():
    """Basic liveness check."""
    return {"status": "ok"}

@health_router.get("/health/ready")
async def readiness_check():
    """Checks all dependencies are available."""
    checks = {}

    # Check Pinecone
    try:
        index = get_index()
        checks["pinecone"] = "ok" if index else "unavailable"
    except Exception:
        checks["pinecone"] = "error"

    # Check Langfuse
    try:
        langfuse.flush()
        checks["langfuse"] = "ok"
    except Exception:
        checks["langfuse"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks
    }
```

---

### 8. Add Circuit Breaker for External Services

**Location:** `backend/app/utils/geo_ip.py`, Langfuse calls
**Risk:** Cascading failures when external services are down

**Recommended Implementation:**

```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
async def get_geo_data(ip_address: str) -> dict:
    # Existing implementation
    ...

# Or use tenacity for retry with circuit breaker
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
async def get_geo_data_with_retry(ip_address: str) -> dict:
    ...
```

---

### 9. Add Input Validation for Query Filters

**Location:** `backend/app/engine/query_filter.py`
**Risk:** Filter injection, unexpected behavior

The `generate_filters()` function takes user-provided role without strict validation:

```python
def generate_filters(doc_ids: List[str], role: str):
    # role comes from user input (params.get("role", "missionary"))
```

**Recommended Fix:**

```python
from enum import Enum

class UserRole(str, Enum):
    MISSIONARY = "missionary"
    ACM = "ACM"

def generate_filters(doc_ids: List[str], role: str):
    # Validate role
    try:
        validated_role = UserRole(role)
    except ValueError:
        validated_role = UserRole.MISSIONARY  # Safe default

    # Use validated_role.value in filters
    ...
```

---

### 10. Increase Worker Count for Production

**Location:** `backend/Dockerfile`
**Risk:** Poor concurrency, request queuing

Current configuration runs a single worker:

```dockerfile
CMD ["gunicorn", "main:app", "-w", "1", ...]
```

**Recommended Fix:**

```dockerfile
# Dynamic worker count based on CPU cores
CMD ["gunicorn", "main:app", \
     "-w", "$(( 2 * $(nproc) + 1 ))", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     ...]
```

For memory-constrained environments (like 2GB Render instances), use:

```dockerfile
CMD ["gunicorn", "main:app", "-w", "2", ...]  # 2 workers minimum
```

---

### 11. Add Request Tracing Headers

**Location:** `backend/app/middleware/monitoring_middleware.py`
**Risk:** Difficult debugging across services

**Recommended Implementation:**

```python
import uuid

class MonitoringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Add to response headers
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        # Include in all logs
        logger = logging.getLogger("uvicorn")
        logger = logging.LoggerAdapter(logger, {"request_id": request_id})

        return response
```

---

### 12. Add Frontend Error Tracking

**Location:** `frontend/app/components/chat-section.tsx`
**Risk:** Silent failures, poor user experience debugging

Current error handling:

```typescript
onError: (error: unknown) => {
    if (!(error instanceof Error)) throw error;
    const message = JSON.parse(error.message);
    alert(message.detail);  // Poor UX, no tracking
}
```

**Recommended Fix:**

```typescript
// Install: npm install @sentry/nextjs
import * as Sentry from "@sentry/nextjs";

onError: (error: unknown) => {
    const errorMessage = error instanceof Error
        ? error.message
        : "An unexpected error occurred";

    // Log to Sentry
    Sentry.captureException(error, {
        tags: { component: "chat" },
        extra: { messages: messages.length }
    });

    // Show user-friendly toast instead of alert
    showToast(errorMessage, "error");
}
```

---

### 13. Implement Response Caching

**Location:** New `backend/app/cache.py` module
**Risk:** Unnecessary LLM costs, slow repeated queries

**Recommended Implementation:**

```python
import hashlib
from functools import lru_cache
from cachetools import TTLCache

# In-memory cache for common queries (simple approach)
response_cache = TTLCache(maxsize=100, ttl=3600)  # 1 hour TTL

def cache_key(question: str, role: str) -> str:
    normalized = question.lower().strip()
    return hashlib.sha256(f"{normalized}:{role}".encode()).hexdigest()

async def get_cached_response(question: str, role: str) -> Optional[str]:
    key = cache_key(question, role)
    return response_cache.get(key)

async def set_cached_response(question: str, role: str, response: str):
    key = cache_key(question, role)
    response_cache[key] = response
```

For production, use Redis:

```python
import redis.asyncio as redis

cache = redis.from_url(os.getenv("REDIS_URL"))

async def get_cached_response(question: str, role: str) -> Optional[str]:
    key = cache_key(question, role)
    return await cache.get(key)
```

---

## P3: Lower Priority (Backlog)

### 14. Add API Versioning

Prefix routes with `/api/v1/` to allow non-breaking changes in future versions.

### 15. Add OpenAPI Documentation

Enable Swagger UI for API documentation:

```python
app = FastAPI(
    title="Pathway Missionary Assistant API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
```

### 16. Implement Graceful Shutdown

Handle SIGTERM properly to finish in-flight requests before exiting.

### 17. Add Dependency Scanning

Add `safety` or `pip-audit` to CI pipeline:

```bash
pip install safety
safety check --full-report
```

### 18. Add Frontend CSP Headers

Configure Content Security Policy in `next.config.mjs`:

```javascript
const securityHeaders = [
    {
        key: 'Content-Security-Policy',
        value: "default-src 'self'; script-src 'self' 'unsafe-inline';"
    }
];
```

### 19. Implement Conversation History Pagination

Limit the number of messages sent to the LLM to control token usage and costs.

### 20. Add Automated Security Testing

Integrate OWASP ZAP or similar into CI/CD pipeline for automated vulnerability scanning.

---

## Implementation Order

Based on risk and effort, recommended implementation order:

1. **Week 1:** Rate limiting (#1), Error sanitization (#3)
2. **Week 2:** API authentication (#2), CORS validation (#4)
3. **Week 3:** Request size limits (#5), Health checks (#7)
4. **Week 4:** Structured logging (#6), Circuit breaker (#8)
5. **Ongoing:** Cache, workers, error tracking (#10, #12, #13)

---

## Dependencies to Add

```toml
# backend/pyproject.toml
slowapi = "^0.1.9"           # Rate limiting
circuitbreaker = "^2.0.0"    # Circuit breaker pattern
redis = "^5.0.0"             # Distributed caching (optional)
```

```json
// frontend/package.json
"@sentry/nextjs": "^7.0.0"   // Error tracking
```

---

## Metrics to Track Post-Implementation

After implementing these changes, monitor:

1. **Rate limit hits** - Tune limits if legitimate users are blocked
2. **Auth failures** - Detect brute force attempts
3. **Circuit breaker trips** - Identify flaky dependencies
4. **Cache hit ratio** - Measure cost savings
5. **Error rates by type** - Ensure sanitization works
6. **P95 latency** - Verify no performance regression

---

## References

- [OWASP API Security Top 10](https://owasp.org/API-Security/)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/tutorial/security/)
- [Twelve-Factor App](https://12factor.net/)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
