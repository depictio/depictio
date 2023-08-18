import aioredis
from fastapi import FastAPI, HTTPException, Depends

app = FastAPI()

REDIS_URL = "redis://localhost:6379"
CACHE_TTL = 300  # Time to live in seconds

async def get_cache():
    redis = await aioredis.create_redis_pool(REDIS_URL)
    try:
        yield redis
    finally:
        redis.close()
        await redis.wait_closed()

@app.get("/file/{file_name}")
async def get_file(file_name: str, cache: aioredis.Redis = Depends(get_cache)):
    cached_file = await cache.get(file_name)
    if cached_file:
        return cached_file
    
    # If file is not in cache, load it from its source (e.g., from disk)
    # and then store it in cache for subsequent requests.
    try:
        with open(file_name, "rb") as f:
            data = f.read()
        await cache.setex(file_name, CACHE_TTL, data)
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
