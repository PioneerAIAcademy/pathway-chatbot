# 📋 Recommendation Implementation TODO

**Branch:** `recommendation-implementation`
**Based on:** [RECOMMENDATIONS.md](./RECOMMENDATIONS.md)
**Created:** 2026-02-18
**Status:** In Progress

---

## 🎯 Progress Overview

- **Total Tasks:** 30
- **Completed:** 0
- **In Progress:** 0
- **Pending:** 30

---

## 🔴 P0: Critical Security (Immediate Action)

### Rate Limiting

- [ ] **Task 1:** Add slowapi dependency to `backend/pyproject.toml`
  - File: `backend/pyproject.toml`
  - Add: `slowapi = "^0.1.9"`

- [ ] **Task 2:** Implement rate limiting in `backend/main.py`
  - File: `backend/main.py`
  - Import slowapi and create limiter instance
  - Configure rate limits per endpoint

- [ ] **Task 3:** Apply rate limiting to chat endpoints
  - File: `backend/app/api/routers/chat.py`
  - Add `@limiter.limit("10/minute")` decorator to `/api/chat`
  - Add `@limiter.limit("30/minute")` to thumbs endpoints
  - Add `@limiter.limit("5/minute")` to feedback endpoints

### API Authentication

- [ ] **Task 4:** Implement API authentication with API keys
  - File: `backend/main.py`
  - Create `verify_api_key()` function
  - Add API key validation middleware
  - Setup API_KEYS environment variable

- [ ] **Task 5:** Apply authentication to all protected endpoints
  - File: `backend/app/api/routers/chat.py`
  - Add `api_key: str = Depends(verify_api_key)` to chat endpoints
  - Update other routers as needed

### Error Handling & Security

- [ ] **Task 6:** Sanitize error messages in production
  - File: `backend/app/api/routers/chat.py`
  - Create `sanitize_error()` function
  - Replace error details with generic messages in prod
  - Location: Line ~201-207

- [ ] **Task 7:** Validate CORS origins explicitly
  - File: `backend/main.py`
  - Create `ALLOWED_ORIGINS` dict with prod/staging/dev origins
  - Replace `allow_origins=["*"]` with explicit list
  - Default to restrictive (prod) if ENVIRONMENT not set
  - Location: Line ~37-48

### Request Validation

- [ ] **Task 8:** Add request size limits middleware
  - File: `backend/main.py`
  - Create middleware to limit request body to 1MB
  - Return 413 status for oversized requests

- [ ] **Task 9:** Limit conversation history to 50 messages
  - File: `backend/app/api/routers/models.py`
  - Find `ChatData` model
  - Add `max_items=50` to messages field

---

## 🟠 P1: High Priority (This Sprint)

### Logging & Observability

- [ ] **Task 10:** Implement structured logging with JSONFormatter
  - File: `backend/main.py`
  - Create `JSONFormatter` class
  - Configure uvicorn logger with JSON format
  - Include timestamp, level, message, module, function, line
  - Add request_id support

---

## 🟡 P2: Medium Priority (Next Sprint)

### Health Checks

- [ ] **Task 11:** Create health check endpoint
  - File: `backend/app/api/routers/health.py` ⭐ NEW FILE
  - Create `health_router`
  - Add `/health` endpoint (basic liveness)
  - Add `/health/ready` endpoint (dependency checks)
  - Check Pinecone, Langfuse availability

- [ ] **Task 12:** Add health router to main.py
  - File: `backend/main.py`
  - Import health_router
  - Add `app.include_router(health_router, prefix="/api/health")`

### External Service Resilience

- [ ] **Task 13:** Add circuitbreaker dependency
  - File: `backend/pyproject.toml`
  - Add: `circuitbreaker = "^2.0.0"`

- [ ] **Task 14:** Add circuit breaker to geo_ip.py
  - File: `backend/app/utils/geo_ip.py`
  - Import `@circuit` decorator
  - Apply to `get_geo_data()` function
  - Configure: `failure_threshold=5, recovery_timeout=60`

### Input Validation

- [ ] **Task 15:** Add input validation for query filters
  - File: `backend/app/engine/query_filter.py`
  - Create `UserRole` enum (MISSIONARY, ACM)
  - Validate role parameter in `generate_filters()`
  - Default to MISSIONARY if invalid

### Infrastructure

- [ ] **Task 16:** Increase worker count in Dockerfile
  - File: `backend/Dockerfile`
  - Change `-w 1` to `-w 2` (or dynamic based on CPU cores)
  - For 2GB instances, use minimum 2 workers

### Monitoring

- [ ] **Task 17:** Add request tracing headers
  - File: `backend/app/middleware/monitoring_middleware.py`
  - Generate or extract X-Request-ID from headers
  - Add to response headers
  - Include in logging context with LoggerAdapter

### Frontend Error Tracking

- [ ] **Task 18:** Add Sentry dependency to frontend
  - File: `frontend/package.json`
  - Add: `"@sentry/nextjs": "^7.0.0"`
  - Run: `npm install`

- [ ] **Task 19:** Implement frontend error tracking
  - File: `frontend/app/components/chat-section.tsx`
  - Import Sentry
  - Replace `alert()` with Sentry.captureException()
  - Add better error handling with context

### Caching

- [ ] **Task 20:** Create response caching module
  - File: `backend/app/cache.py` ⭐ NEW FILE
  - Create TTLCache (maxsize=100, ttl=3600)
  - Add `cache_key()` function
  - Add `get_cached_response()` function
  - Add `set_cached_response()` function

- [ ] **Task 21:** Integrate caching into chat endpoint
  - File: `backend/app/api/routers/chat.py`
  - Import cache functions
  - Check cache before processing request
  - Save response to cache after generation

---

## 🟢 P3: Lower Priority (Backlog)

### API Improvements

- [ ] **Task 22:** Add API versioning
  - Files: `backend/main.py`, `backend/app/api/routers/*.py`
  - Change route prefixes from `/api/chat` to `/api/v1/chat`
  - Update frontend API calls accordingly

- [ ] **Task 23:** Add OpenAPI documentation configuration
  - File: `backend/main.py`
  - Update `FastAPI()` constructor:
    - title: "Pathway Missionary Assistant API"
    - version: "1.0.0"
    - docs_url: "/api/docs"
    - redoc_url: "/api/redoc"

- [ ] **Task 24:** Implement graceful shutdown
  - File: `backend/main.py`
  - Add SIGTERM handler
  - Allow in-flight requests to complete before shutdown
  - Close connections gracefully

### Frontend Security

- [ ] **Task 25:** Add CSP headers to frontend
  - File: `frontend/next.config.json`
  - Add Content-Security-Policy headers
  - Configure: `default-src 'self'; script-src 'self' 'unsafe-inline';`

---

## ✅ Testing & Documentation

### Testing

- [ ] **Task 26:** Test all P0 changes
  - Verify rate limiting blocks excess requests
  - Test API authentication rejects invalid keys
  - Confirm error messages are sanitized in prod
  - Test CORS only allows specified origins
  - Verify request size limits work

- [ ] **Task 27:** Test all P1-P2 changes
  - Check structured logging outputs JSON
  - Test health endpoints return correct status
  - Verify circuit breaker trips after failures
  - Test role validation rejects invalid inputs
  - Confirm request tracing headers present
  - Test frontend error tracking sends to Sentry
  - Verify caching works and reduces API calls

- [ ] **Task 28:** Run security audit
  - Run `npm audit` on frontend
  - Run `safety check` on backend (if available)
  - Verify all critical vulnerabilities addressed
  - Document remaining acceptable risks

### Documentation

- [ ] **Task 29:** Update documentation
  - Update API docs with new endpoints
  - Document authentication requirements
  - Add health check endpoint docs
  - Document rate limits per endpoint
  - Update environment variable requirements

### Deployment

- [ ] **Task 30:** Create pull request
  - Ensure all tests pass
  - Update CHANGELOG.md
  - Write comprehensive PR description
  - Request code review
  - Merge to main after approval

---

## 📝 Implementation Notes

### Environment Variables to Add

```bash
# Backend (.env)
API_KEYS=key1,key2,key3  # Comma-separated API keys for authentication
ENVIRONMENT=prod         # prod/staging/dev (affects CORS, error messages)
REDIS_URL=redis://...    # Optional: For distributed caching (future)
```

### Dependencies to Install

**Backend:**
```bash
cd backend
poetry add slowapi circuitbreaker
```

**Frontend:**
```bash
cd frontend
npm install @sentry/nextjs
```

### Files to Create

1. `backend/app/api/routers/health.py` - Health check endpoints
2. `backend/app/cache.py` - Response caching module

### Files to Modify

**Backend:**
- `backend/main.py` (multiple changes)
- `backend/app/api/routers/chat.py` (auth, rate limits, caching)
- `backend/app/api/routers/models.py` (message limits)
- `backend/app/utils/geo_ip.py` (circuit breaker)
- `backend/app/engine/query_filter.py` (role validation)
- `backend/app/middleware/monitoring_middleware.py` (request tracing)
- `backend/Dockerfile` (worker count)
- `backend/pyproject.toml` (dependencies)

**Frontend:**
- `frontend/app/components/chat-section.tsx` (error tracking)
- `frontend/next.config.json` (CSP headers)
- `frontend/package.json` (Sentry dependency)

---

## 🚦 Implementation Order

### Week 1: Critical Security
1. Tasks 1-9 (P0: Rate limiting, Auth, CORS, Request limits)
2. Task 26 (Test P0 changes)

### Week 2: High Priority
3. Task 10 (P1: Structured logging)

### Week 3: Medium Priority Part 1
4. Tasks 11-17 (P2: Health checks, Circuit breaker, Monitoring)

### Week 4: Medium Priority Part 2
5. Tasks 18-21 (P2: Error tracking, Caching)
6. Task 27 (Test P1-P2 changes)

### Week 5: Lower Priority
7. Tasks 22-25 (P3: API versioning, Documentation, CSP)
8. Tasks 28-30 (Testing, Documentation, PR)

---

## ✅ Completion Checklist

Once all tasks are complete, verify:

- [ ] All P0 security measures implemented and tested
- [ ] Rate limiting prevents abuse
- [ ] API authentication required for all endpoints
- [ ] Error messages don't leak sensitive information
- [ ] CORS properly configured for production
- [ ] Request size limits prevent DoS
- [ ] Structured logging outputs parseable JSON
- [ ] Health checks return accurate status
- [ ] Circuit breakers prevent cascading failures
- [ ] Frontend errors tracked in Sentry
- [ ] Response caching reduces API costs
- [ ] All tests passing
- [ ] Documentation updated
- [ ] Code reviewed and approved
- [ ] Deployed to production successfully

---

## 📚 References

- [RECOMMENDATIONS.md](./RECOMMENDATIONS.md) - Detailed implementation guide
- [OWASP API Security Top 10](https://owasp.org/API-Security/)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/tutorial/security/)
- [slowapi Documentation](https://slowapi.readthedocs.io/)
- [Sentry Next.js Setup](https://docs.sentry.io/platforms/javascript/guides/nextjs/)

---

**Last Updated:** 2026-02-18
**Branch:** `recommendation-implementation`
**Next Action:** Start with Task 1 (Add slowapi dependency)
