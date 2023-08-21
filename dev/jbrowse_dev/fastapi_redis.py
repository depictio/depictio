from fastapi import FastAPI, Response
import redis
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Assuming you have some kind of settings or configuration in place
# If you don't, just replace settings.redis_host, etc., with the actual values.
redis_client = redis.Redis(host="localhost", port=6379, db=0)


@app.get("/assets/{filename:path}")
async def get_asset(filename: str):
    print(filename)
    # Assuming filename is unique
    cached_content = redis_client.get(filename)
    # print(cached_content)

    if cached_content:
        print("CACHED")
        return Response(content=cached_content, media_type="application/octet-stream")

    # If not in cache, load it from disk (this is just a basic idea)
    with open(f"assets/{filename}", "rb") as file:
        print("NOT CACHED")

        content = file.read()
        # Store in Redis
        redis_client.set(filename, content)
        return Response(content=content, media_type="application/octet-stream")


# redis_host: localhost
# redis_port: 6379
# redis_db: 0
# redis_cache_ttl: 300
# user_secret_key: mysecretkey

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8090)
