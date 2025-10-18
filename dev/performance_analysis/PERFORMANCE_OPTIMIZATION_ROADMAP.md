# Depictio Performance Optimization Roadmap

**Document Version**: 1.0
**Date**: 2025-10-17
**Status**: Planning Phase

---

## Executive Summary

This document outlines the complete performance optimization strategy for Depictio, organized into progressive phases based on impact and implementation difficulty. The roadmap builds upon the successful Phase 4E optimizations that reduced routing callbacks from 261ms to 15ms (95% improvement).

**Current Baseline** (After Phase 4E):
- ✅ Routing callback: **15ms** (optimized)
- ⚠️ Consolidated API: **266ms cold** / **98ms warm** (main bottleneck)
- ⚠️ Initial page load: **745ms** (needs improvement)

**Target After All Phases**:
- Consolidated API: **60ms** (77% faster)
- Initial page load: **350ms** (53% faster)
- Overall application: **60-70% performance improvement**

---

## Optimization Phases Overview

| Phase | Focus Area | Expected Improvement | Priority |
|-------|-----------|---------------------|----------|
| **Phase 5** | Database & Backend | 150-200ms | ⭐⭐⭐⭐⭐ Critical |
| **Phase 6** | Frontend Loading | 200-300ms | ⭐⭐⭐⭐⭐ Critical |
| **Phase 7** | Infrastructure | 50-100ms | ⭐⭐⭐⭐ High |
| **Phase 8** | Client Optimization | 100-300ms | ⭐⭐⭐ Medium |

---

## Phase 5: Database & Backend Optimization

**Objective**: Reduce API response times by 60-70%
**Total Expected Improvement**: 150-200ms
**Timeline**: 2-3 weeks

### Phase 5A: Redis Caching Layer ⭐⭐⭐⭐⭐

**Impact**: VERY HIGH (eliminates 100-150ms per cold request)
**Difficulty**: Medium
**Timeline**: 5-7 days

#### Problem Statement
Currently, every API call hits MongoDB directly, even for frequently accessed data:
- User data fetched 20+ times per session
- Project metadata re-fetched on every dashboard load
- Server status checked repeatedly

This results in:
- 266ms consolidated API callback (cold)
- Unnecessary database load
- Poor scalability under high traffic

#### Solution: Multi-Layer Caching

**Cache Architecture**:
```
Client Request → Redis Cache (if hit) → MongoDB (if miss) → Update Cache
                     ↓ (<5ms)              ↓ (40-60ms)
                  Return                Return + Cache
```

**Cache Keys Design**:
```python
# User data cache
f"user:{user_id}" → {
    "id": "...",
    "email": "...",
    "is_admin": bool,
    "timestamp": float
}  # TTL: 5 minutes

# Token to user mapping
f"token:{access_token_hash}" → user_id  # TTL: 5 minutes

# Project metadata
f"project:{dashboard_id}" → {
    "project": {...},
    "workflows": [...],
    "timestamp": float
}  # TTL: 10 minutes

# Server status
"server:status" → {
    "status": "online",
    "version": "...",
    "timestamp": float
}  # TTL: 2 minutes
```

**TTL Strategy**:
- User data: 5 minutes (balance freshness vs performance)
- Project data: 10 minutes (infrequently updated)
- Server status: 2 minutes (health checks)
- Token mappings: Same as token expiry

#### Implementation Plan

**Step 1: Add Redis Dependencies**
```bash
# pyproject.toml
[tool.poetry.dependencies]
redis = {extras = ["hiredis"], version = "^5.0.0"}
```

**Step 2: Create Cache Service**

**File**: `depictio/api/v1/services/cache_service.py`

```python
"""
Redis caching service for Depictio API.

Provides caching layer for frequently accessed data:
- User data
- Project metadata
- Server status
"""

import json
import hashlib
from typing import Any, Optional
from datetime import timedelta

import redis.asyncio as redis
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


class CacheService:
    """Async Redis cache service."""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.enabled = settings.redis.enabled  # Config flag

    async def connect(self):
        """Initialize Redis connection."""
        if not self.enabled:
            logger.info("Redis caching disabled via config")
            return

        try:
            self.redis_client = await redis.from_url(
                settings.redis.url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_keepalive=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self.redis_client.ping()
            logger.info("✅ Redis cache connected successfully")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            self.enabled = False

    async def disconnect(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()

    async def get(self, key: str) -> Optional[dict]:
        """Get cached data."""
        if not self.enabled or not self.redis_client:
            return None

        try:
            data = await self.redis_client.get(key)
            if data:
                logger.debug(f"🎯 Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"❌ Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache get error for {key}: {e}")
            return None

    async def set(self, key: str, value: dict, ttl: int):
        """Set cached data with TTL."""
        if not self.enabled or not self.redis_client:
            return

        try:
            await self.redis_client.setex(
                key,
                timedelta(seconds=ttl),
                json.dumps(value, default=str)
            )
            logger.debug(f"💾 Cache SET: {key} (TTL: {ttl}s)")
        except Exception as e:
            logger.error(f"Cache set error for {key}: {e}")

    async def delete(self, key: str):
        """Delete cached data."""
        if not self.enabled or not self.redis_client:
            return

        try:
            await self.redis_client.delete(key)
            logger.debug(f"🗑️ Cache DELETE: {key}")
        except Exception as e:
            logger.error(f"Cache delete error for {key}: {e}")

    async def invalidate_user(self, user_id: str):
        """Invalidate all user-related caches."""
        await self.delete(f"user:{user_id}")
        # Also clear token mappings (requires scan)
        pattern = f"token:*:{user_id}"
        try:
            async for key in self.redis_client.scan_iter(match=pattern):
                await self.delete(key)
        except Exception as e:
            logger.error(f"Cache invalidation error: {e}")

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash token for cache key (security)."""
        return hashlib.sha256(token.encode()).hexdigest()[:16]


# Global cache instance
cache_service = CacheService()
```

**Step 3: Update Configuration**

**File**: `depictio/api/v1/configs/config.py`

```python
class RedisSettings(BaseSettings):
    """Redis configuration."""
    enabled: bool = Field(default=True, description="Enable Redis caching")
    url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )

    model_config = SettingsConfigDict(env_prefix="REDIS_")


class Settings(BaseSettings):
    """Application settings."""
    # ... existing settings ...
    redis: RedisSettings = Field(default_factory=RedisSettings)
```

**Step 4: Integrate into User Fetch Endpoint**

**File**: `depictio/api/v1/endpoints/user_endpoints/routes.py`

```python
from depictio.api.v1.services.cache_service import cache_service

@router.get("/fetch_user/from_token")
async def fetch_user_from_token(token: str):
    """
    Fetch user with Redis caching.

    Performance optimization:
    - Cache hit: ~5ms
    - Cache miss: ~45ms (MongoDB + cache update)
    """
    # Check cache first
    token_hash = cache_service.hash_token(token)
    cache_key = f"token:{token_hash}"

    cached_user_id = await cache_service.get(cache_key)
    if cached_user_id:
        # Get user from cache
        user_cache_key = f"user:{cached_user_id}"
        cached_user = await cache_service.get(user_cache_key)
        if cached_user:
            logger.info(f"🎯 User cache HIT: {cached_user['email']}")
            return cached_user

    # Cache miss - fetch from database
    logger.info("❌ User cache MISS - fetching from MongoDB")
    user = await _async_fetch_user_from_token(token)

    if user:
        # Cache user data
        user_data = {
            "id": str(user.id),
            "email": user.email,
            "is_admin": user.is_admin,
            "is_anonymous": getattr(user, "is_anonymous", False),
        }

        # Cache token → user_id mapping
        await cache_service.set(cache_key, str(user.id), ttl=300)  # 5 min

        # Cache user data
        user_cache_key = f"user:{user.id}"
        await cache_service.set(user_cache_key, user_data, ttl=300)  # 5 min

        logger.info(f"💾 Cached user: {user.email}")
        return user_data

    return None
```

**Step 5: Add Cache Invalidation**

**File**: `depictio/api/v1/endpoints/user_endpoints/routes.py`

```python
@router.put("/edit_password")
async def edit_password(user_id: str, new_password: str):
    """Update password and invalidate cache."""
    success = await _edit_password(user_id, new_password)

    if success:
        # Invalidate user cache
        await cache_service.invalidate_user(user_id)
        logger.info(f"🗑️ Invalidated cache for user {user_id}")

    return {"success": success}
```

**Step 6: Initialize on Startup**

**File**: `depictio/api/main.py`

```python
from depictio.api.v1.services.cache_service import cache_service

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting Depictio API...")

    # Connect to Redis
    await cache_service.connect()

    # Start cleanup tasks
    start_cleanup_tasks()

    logger.info("✅ Depictio API started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Depictio API...")

    # Disconnect Redis
    await cache_service.disconnect()

    logger.info("✅ Depictio API shutdown complete")
```

#### Testing & Validation

**Performance Tests**:
```bash
# Test cache hit performance
ab -n 1000 -c 10 http://localhost:8058/depictio/api/v1/auth/fetch_user/from_token?token=...

# Expected results:
# - Cold (first request): ~45ms
# - Warm (cached): ~5ms
```

**Cache Monitoring**:
```python
# Add metrics endpoint
@router.get("/cache/stats")
async def cache_stats():
    """Get cache statistics."""
    info = await cache_service.redis_client.info("stats")
    return {
        "hits": info["keyspace_hits"],
        "misses": info["keyspace_misses"],
        "hit_rate": info["keyspace_hits"] / (info["keyspace_hits"] + info["keyspace_misses"]),
    }
```

#### Rollout Strategy

1. **Development**: Test with local Redis
2. **Staging**: Deploy with monitoring
3. **Production**:
   - Canary deploy (10% traffic)
   - Monitor cache hit rate (target: >80%)
   - Full rollout if successful

#### Rollback Plan

If issues arise:
1. Set `REDIS_ENABLED=false` in environment
2. Application falls back to direct MongoDB queries
3. No data loss (cache is read-through)

---

### Phase 5B: MongoDB Query Optimization ⭐⭐⭐⭐⭐

**Impact**: HIGH (30-50ms per query)
**Difficulty**: Low
**Timeline**: 2-3 days

#### Problem Statement

Current MongoDB queries lack proper indexing:
- Full collection scans for user lookups by email
- Unindexed token queries (N*M complexity)
- Large document transfers (fetching unnecessary fields)

**Query Analysis**:
```python
# Slow query (no index on email)
await UserBeanie.find_one({"email": "admin@example.com"})  # 30-40ms

# Slow query (compound index missing)
await TokenBeanie.find_one({"access_token": "...", "user_id": "..."})  # 20-30ms

# Over-fetching (entire document)
user = await UserBeanie.get(user_id)  # 25-35ms (includes all fields)
```

#### Solution: Index Strategy + Query Optimization

**1. Add Database Indexes**

**File**: `depictio/models/models/users.py`

```python
from beanie import Document, Indexed
from pydantic import EmailStr

class UserBeanie(Document):
    """User document with optimized indexes."""

    # Single field indexes
    email: Indexed(EmailStr, unique=True)  # Unique index on email

    # Compound index for common query pattern
    class Settings:
        name = "users"
        indexes = [
            "email",  # Single field index
            [("_id", 1), ("is_anonymous", 1)],  # Compound for admin checks
            [("is_temporary", 1), ("expiration_time", 1)],  # For cleanup tasks
        ]
```

**File**: `depictio/models/models/tokens.py`

```python
class TokenBeanie(Document):
    """Token document with optimized indexes."""

    class Settings:
        name = "tokens"
        indexes = [
            "access_token",  # Frequently queried
            [("user_id", 1), ("expire_datetime", -1)],  # User tokens ordered by expiry
            [("refresh_expire_datetime", 1)],  # For purge tasks
        ]
```

**2. Use Query Projections**

Instead of fetching entire documents, only fetch needed fields:

```python
# Before: Fetch entire user document (all fields)
user = await UserBeanie.find_one({"email": email})  # ~35ms

# After: Fetch only needed fields
user = await UserBeanie.find_one(
    {"email": email},
    projection_model=UserContext  # Only id, email, is_admin
)  # ~15ms (50% faster!)
```

**Create lightweight projection model**:

**File**: `depictio/models/models/users.py`

```python
class UserContext(BaseModel):
    """Lightweight user model for API responses."""
    id: PyObjectId
    email: EmailStr
    is_admin: bool = False
    is_anonymous: bool = False

    class Config:
        from_attributes = True
```

**3. Optimize Aggregation Queries**

For complex queries, use aggregation pipelines:

```python
# Before: Multiple queries
user = await UserBeanie.get(user_id)
tokens = await TokenBeanie.find({"user_id": user_id}).to_list()
# 2 round-trips, 60-80ms total

# After: Single aggregation
user_with_tokens = await UserBeanie.aggregate([
    {"$match": {"_id": user_id}},
    {"$lookup": {
        "from": "tokens",
        "localField": "_id",
        "foreignField": "user_id",
        "as": "tokens"
    }},
    {"$project": {
        "email": 1,
        "is_admin": 1,
        "tokens": {"$slice": ["$tokens", 5]}  # Limit tokens
    }}
]).to_list()
# 1 round-trip, 30-40ms total (50% faster!)
```

#### Implementation Steps

**Step 1: Create Migration Script**

**File**: `scripts/create_mongodb_indexes.py`

```python
"""
Create MongoDB indexes for performance optimization.

Run once to create indexes on existing collections.
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from depictio.api.v1.configs.config import settings

async def create_indexes():
    """Create all required indexes."""
    client = AsyncIOMotorClient(settings.mongodb.url)
    db = client[settings.mongodb.database]

    # Users collection
    users = db["users"]
    await users.create_index("email", unique=True)
    await users.create_index([("is_temporary", 1), ("expiration_time", 1)])
    print("✅ Created users indexes")

    # Tokens collection
    tokens = db["tokens"]
    await tokens.create_index("access_token")
    await tokens.create_index([("user_id", 1), ("expire_datetime", -1)])
    await tokens.create_index("refresh_expire_datetime")
    print("✅ Created tokens indexes")

    # Projects collection
    projects = db["projects"]
    await projects.create_index("permissions.owners._id")
    print("✅ Created projects indexes")

    client.close()

if __name__ == "__main__":
    asyncio.run(create_indexes())
```

**Step 2: Update User Fetch Function**

**File**: `depictio/api/v1/endpoints/user_endpoints/core_functions.py`

```python
async def _async_fetch_user_from_token(token: str) -> UserBeanie | None:
    """
    Fetch user with optimized query projection.

    Performance improvement:
    - Before: 35-40ms (full document)
    - After: 15-20ms (projected fields only)
    """
    # Find token with projection (only need user_id)
    token_doc = await TokenBeanie.find_one(
        {"access_token": token},
        projection_model=TokenProjection  # Only user_id field
    )

    if not token_doc:
        return None

    # Find user with projection
    user = await UserBeanie.find_one(
        {"_id": token_doc.user_id},
        projection_model=UserContext  # Only needed fields
    )

    return user
```

**Step 3: Verify Indexes**

```python
# Check index creation
db.users.getIndexes()
# Should show:
# [
#   {"key": {"_id": 1}},  # Default
#   {"key": {"email": 1}, "unique": true},
#   {"key": {"is_temporary": 1, "expiration_time": 1}}
# ]
```

#### Performance Testing

**Before Optimization**:
```bash
# Average query time
User fetch: 35-40ms
Token fetch: 25-30ms
Total: 60-70ms
```

**After Optimization**:
```bash
# Average query time
User fetch: 15-20ms (50% faster!)
Token fetch: 10-15ms (50% faster!)
Total: 25-35ms (58% faster!)
```

**Verify with explain()**:
```python
# Check query execution plan
explain = await UserBeanie.find({"email": "test@example.com"}).explain()
print(explain["executionStats"]["executionTimeMillis"])
# Should use IXSCAN (index scan) not COLLSCAN (collection scan)
```

---

### Phase 5C: HTTP Connection Pooling ⭐⭐⭐⭐

**Impact**: MEDIUM (10-20ms per request)
**Difficulty**: Low
**Timeline**: 1-2 days

#### Problem Statement

Currently creating new `httpx.AsyncClient` for each API call:

```python
# Current: New connection every time
async def fetch_user_data(token):
    async with httpx.AsyncClient(timeout=5) as client:  # Connection overhead!
        response = await client.get(...)
```

**Issues**:
- TCP handshake overhead: ~5-10ms per request
- SSL/TLS negotiation: ~10-20ms per request
- Connection not reused across requests
- Inefficient under high load

#### Solution: Persistent Connection Pool

**File**: `depictio/dash/layouts/consolidated_api.py`

```python
import httpx

# Global persistent client (initialized on app startup)
http_client: Optional[httpx.AsyncClient] = None

def init_http_client():
    """Initialize persistent HTTP client."""
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0, connect=3.0),
        limits=httpx.Limits(
            max_keepalive_connections=20,  # Keep 20 connections alive
            max_connections=50,  # Max concurrent connections
            keepalive_expiry=30.0,  # Keep connections for 30s
        ),
        http2=True,  # Enable HTTP/2 for multiplexing
        follow_redirects=True,
    )


async def fetch_user_data(token):
    """Fetch user with persistent connection."""
    # Reuse existing connection!
    response = await http_client.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        params={"token": token},
    )
    return response.json()
```

**Initialize on app startup**:

**File**: `depictio/dash/app.py`

```python
from depictio.dash.layouts.consolidated_api import init_http_client, http_client

@app.callback(...)
def startup_callback(...):
    """Initialize services on first callback."""
    init_http_client()
```

**Cleanup on shutdown** (if using Flask/FastAPI lifecycle):
```python
async def shutdown():
    """Close HTTP client on shutdown."""
    if http_client:
        await http_client.aclose()
```

#### Expected Improvement

- **First request**: 5ms connection overhead saved
- **Subsequent requests**: 15-20ms saved (connection reuse)
- **Under load**: Significant improvement (fewer connections to manage)

---

## Phase 6: Frontend Loading Optimization

**Objective**: Reduce initial page load by 40-50%
**Total Expected Improvement**: 200-300ms
**Timeline**: 2-3 weeks

### Phase 6A: Component Lazy Loading ⭐⭐⭐⭐⭐

**Impact**: VERY HIGH (100-150ms)
**Difficulty**: Medium
**Timeline**: 5-7 days

#### Problem Statement

Currently all dashboard components load sequentially:
1. Fetch metadata (100ms)
2. Wait for all component data (200-300ms)
3. Render all components at once (50-100ms)

**Total**: 350-500ms before user sees anything

#### Solution: Progressive Rendering

**Strategy**:
1. Render skeleton UI immediately (0ms perceived wait)
2. Load critical components first (above-the-fold)
3. Lazy-load remaining components
4. Show loading indicators for each component

**Implementation**: Already exists but needs enhancement

**File**: `depictio/dash/layouts/draggable_scenarios/progressive_loading.py`

Enhance existing progressive loading to:
- Prioritize visible components
- Defer off-screen components
- Show individual component skeletons

---

### Phase 6B: Component Data Pre-fetching ⭐⭐⭐⭐

**Impact**: MEDIUM-HIGH (50-100ms)
**Difficulty**: Medium
**Timeline**: 3-5 days

#### Solution: Parallel Data Loading

Fetch dashboard metadata in consolidated API callback (already on dashboard route):

```python
# consolidated_api.py
if "/dashboard/" in pathname:
    dashboard_id = pathname.split("/")[-1]

    # Fetch project AND metadata in parallel
    project_task = fetch_project_data(token, dashboard_id)
    metadata_task = fetch_dashboard_metadata(token, dashboard_id)

    project, metadata = await asyncio.gather(project_task, metadata_task)
```

**Benefit**: Eliminates waterfall loading (sequential → parallel)

---

## Phase 7: Infrastructure Optimization

### Phase 7A: Database Connection Pooling ⭐⭐⭐

**Impact**: MEDIUM (20-30% query improvement)
**Difficulty**: Low
**Timeline**: 1-2 days

**File**: `depictio/api/v1/db.py`

```python
client = AsyncIOMotorClient(
    settings.mongodb.url,
    maxPoolSize=50,  # Increased from default 100
    minPoolSize=10,  # Keep 10 connections warm
    maxIdleTimeMS=45000,  # Close idle connections after 45s
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
)
```

---

### Phase 7B: API Response Aggregation ⭐⭐⭐

**Impact**: MEDIUM (30-40ms)
**Difficulty**: Medium
**Timeline**: 3-5 days

Create unified endpoint to reduce HTTP round-trips:

**File**: `depictio/api/v1/endpoints/consolidated/routes.py`

```python
@router.get("/bootstrap")
async def get_bootstrap_data(token: str, dashboard_id: Optional[str] = None):
    """
    Get all bootstrap data in one request.

    Returns:
        - User data
        - Server status
        - Project data (if dashboard_id provided)
    """
    # Fetch in parallel
    user_task = fetch_user(token)
    status_task = fetch_server_status()
    project_task = fetch_project(dashboard_id) if dashboard_id else None

    user, status, project = await asyncio.gather(
        user_task,
        status_task,
        project_task or asyncio.sleep(0)
    )

    return {
        "user": user,
        "server": status,
        "project": project
    }
```

**Benefit**: 3 HTTP requests → 1 HTTP request (2 round-trips saved)

---

## Phase 8: Client Optimization (Future)

### Phase 8A: Asset Optimization
- Code splitting
- Lazy component loading
- Compression (gzip/brotli)

### Phase 8B: Service Worker
- Cache static assets
- Offline support
- Background sync

---

## Implementation Timeline

### Month 1: Backend Optimization (Phase 5)
- **Week 1**: Phase 5B (MongoDB indexes) + 5C (HTTP pooling)
- **Week 2-3**: Phase 5A (Redis caching)
- **Week 4**: Testing, monitoring, documentation

### Month 2: Frontend Optimization (Phase 6)
- **Week 1-2**: Phase 6A (Lazy loading enhancement)
- **Week 3**: Phase 6B (Pre-fetching)
- **Week 4**: Testing, performance validation

### Month 3: Infrastructure (Phase 7)
- **Week 1**: Phase 7A (DB connection pooling)
- **Week 2**: Phase 7B (API aggregation)
- **Week 3-4**: Load testing, production rollout

---

## Success Metrics

### Performance Targets

| Metric | Baseline | Phase 5 | Phase 6 | Phase 7 | Target |
|--------|----------|---------|---------|---------|--------|
| **Consolidated API (cold)** | 266ms | 120ms | 100ms | 80ms | **70% faster** |
| **Consolidated API (warm)** | 98ms | 15ms | 10ms | 10ms | **90% faster** |
| **Initial page load** | 745ms | 600ms | 400ms | 350ms | **53% faster** |
| **Cache hit rate** | 0% | >80% | >85% | >90% | **90%+** |

### Monitoring

**Key Metrics to Track**:
1. P50, P95, P99 response times
2. Cache hit/miss ratio
3. Database query duration
4. Connection pool utilization
5. Error rates

**Tools**:
- Application logs (structured JSON)
- Redis INFO stats
- MongoDB slow query log
- Custom performance report (existing)

---

## Risk Mitigation

### Phase 5A: Redis Caching

**Risk**: Redis failure breaks application
**Mitigation**:
- Graceful degradation (fall back to MongoDB)
- Redis health checks
- Read-through cache pattern

### Phase 5B: MongoDB Indexes

**Risk**: Index creation blocks database
**Mitigation**:
- Create indexes with `background: true`
- Run during low-traffic window
- Monitor index build progress

### Phase 6A: Lazy Loading

**Risk**: Poor UX if loading indicators unclear
**Mitigation**:
- High-quality skeleton UI
- Progress indicators
- Fallback to synchronous load if needed

---

## Rollback Procedures

### Phase 5A: Disable Redis
```bash
# Environment variable
export REDIS_ENABLED=false

# Or config file
redis:
  enabled: false
```

### Phase 5B: Drop Indexes
```python
db.users.dropIndex("email_1")
```

### Phase 6A: Disable Lazy Loading
```python
# Feature flag
ENABLE_PROGRESSIVE_LOADING=false
```

---

## Appendix

### A. Performance Testing Checklist

- [ ] Cold start performance (no cache)
- [ ] Warm performance (cache hit)
- [ ] Concurrent user load (10, 50, 100 users)
- [ ] Database query latency (P50, P95, P99)
- [ ] Cache hit rate (target: >80%)
- [ ] Error rate under load (<0.1%)

### B. Deployment Checklist

- [ ] Code review completed
- [ ] Unit tests passing
- [ ] Integration tests passing
- [ ] Performance tests passing
- [ ] Staging deployment successful
- [ ] Monitoring dashboards created
- [ ] Rollback plan documented
- [ ] Production deployment approved

### C. Documentation Updates

- [ ] API documentation updated
- [ ] Architecture diagrams updated
- [ ] Configuration guide updated
- [ ] Troubleshooting guide updated
- [ ] Changelog updated

---

**Document Owner**: Performance Team
**Last Updated**: 2025-10-17
**Next Review**: After Phase 5 completion
