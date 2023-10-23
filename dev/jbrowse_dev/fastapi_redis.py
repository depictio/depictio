import os
from fastapi import FastAPI, Request, Response, HTTPException
import redis
import uvicorn
from fastapi.middleware.cors import CORSMiddleware



app = FastAPI()

origins = [
    "http://localhost:5500",
    # Add other origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Assuming you have some kind of settings or configuration in place
# If you don't, just replace settings.redis_host, etc., with the actual values.
redis_client = redis.Redis(host="localhost", port=6379, db=0)


# @app.get("/assets/{filename:path}")
# async def get_asset(filename: str):
#     print(filename)
#     # Assuming filename is unique
#     cached_content = redis_client.get(filename)
#     # print(cached_content)

#     if cached_content:
#         print("CACHED")
#         return Response(content=cached_content, media_type="application/octet-stream")

#     # If not in cache, load it from disk (this is just a basic idea)
#     with open(f"assets/{filename}", "rb") as file:
#         print("NOT CACHED")

#         content = file.read()
#         # Store in Redis
#         redis_client.set(filename, content)
#         return Response(content=content, media_type="application/octet-stream")



@app.get("/assets/{filename:path}")
async def get_asset(filename: str, request: Request):
    # Check for Range header
    range_header = request.headers.get("Range")
    
    if range_header:
        start, end = range_header.replace("bytes=", "").split("-")
        start, end = int(start), int(end)

        # Define a cache key specific to the byte range
        cache_key = f"{filename}_{start}_{end}"
        cached_content = redis_client.get(cache_key)

        if cached_content:
            print("CACHED")
            return Response(content=cached_content, status_code=206, headers={
                "Content-Range": f"bytes {start}-{end}/{os.path.getsize(f'assets/{filename}')}"
            })

        # If not in cache, load the specified range from the file
        with open(f"assets/{filename}", "rb") as file:
            file.seek(start)
            content = file.read(end - start + 1)
            # Store in Redis
            redis_client.set(cache_key, content)
            return Response(content=content, status_code=206, headers={
                "Content-Range": f"bytes {start}-{end}/{os.path.getsize(f'assets/{filename}')}"
            })

    # If no Range header, check the cache for the entire file content
    cached_content = redis_client.get(filename)
    if cached_content:
        return Response(content=cached_content, media_type="application/octet-stream")

    # If not in cache, return the whole file
    with open(f"assets/{filename}", "rb") as file:
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
