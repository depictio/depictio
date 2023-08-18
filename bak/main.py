# from src import multiqc_watcher
from fastapi import FastAPI, Depends, HTTPException
import pymongo
import redis
from src import config, models, auth

# from src.auth import app as auth_app
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from typing import List, Optional
import json
import time
import sys

app = FastAPI()

# app.mount("/auth", auth_app)


settings = config.Settings.from_yaml("config.yaml")

# Set up the MongoDB client and database
mongo_client = pymongo.MongoClient(settings.mongo_url)
mongo_db = mongo_client[settings.mongo_db]
# multiqc_files_collection = mongo_db["multiqc_files"]

# Set up the Redis client and cache
redis_client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db)

# Test MongoDB connection
try:
    mongo_client.server_info()
    print("Connected to MongoDB!")
    # auth.seed_initial_admin_user(mongo_db)
except pymongo.errors.ConnectionFailure:
    print("Failed to connect to MongoDB.")


@app.post("/multiqc_files/{workflow_name}")
async def create_multiqc_file(workflow_name: str, multiqc_file: models.MultiQCFile):
    # Check if the multiqc_file already exists in the collection

    collection = mongo_db[workflow_name]

    if mongo_db.collection.count_documents({}) == 0:
        collection.create_index([("file_path", pymongo.ASCENDING)])
        collection.create_index([("run_name", pymongo.ASCENDING)], sparse=True)

    existing_file = collection.find_one({"file_path": multiqc_file.file_path})
    if existing_file:
        return {"message": "File already exists in the database."}
    else:
        # Insert the new multiqc_file document into the collection
        result = collection.insert_one(multiqc_file.dict())

        # Delete the cache for the corresponding workflow
        redis_client.delete(multiqc_file.wf_name)

        return {"inserted_id": str(result.inserted_id)}


@app.get("/multiqc_files/{workflow_name}")
async def get_multiqc_files(workflow_name: str, run_name: Optional[str] = None):
    collection = mongo_db[workflow_name]

    start_time = time.time()

    print(workflow_name)
    # Find all documents in the collection with the specified workflow name
    q_dict = {"wf_name": workflow_name}
    print(workflow_name, run_name, type(run_name))
    if run_name:
        q_dict["run_name"] = run_name
    print(q_dict)

    # Check if the query exists in Redis cache
    redis_key = f"multiqc_files_query:{workflow_name}:{run_name}"
    redis_value = redis_client.get(redis_key)
    if redis_value:
        # Convert Redis value from JSON string to list of dictionaries
        print("CACHED")
        result = json.loads(redis_value)
        # print(result)
        end_time = time.time()
        elapsed_time = end_time - start_time
        size_in_megabytes = sys.getsizeof(result) / 1048576

        return {"Message": "OK", "Size": f"{size_in_megabytes:.2f}", "Query elapsed time": f"{elapsed_time:.6f}s"}

        # return result

    multiqc_files_query = list(collection.find(q_dict))
    # print(multiqc_files_query)

    multiqc_files = list()

    for file in multiqc_files_query:
        # Convert ObjectId instances to strings
        file["_id"] = str(file["_id"])
        # Serialize the object using jsonable_encoder
        multiqc_files.append(jsonable_encoder(file))

    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Query elapsed time: {elapsed_time:.6f}s")

    # Store the query result in Redis cache
    redis_value = json.dumps([jsonable_encoder(file) for file in multiqc_files])
    redis_client.set(redis_key, redis_value, ex=settings.redis_cache_ttl)

    size_in_megabytes = sys.getsizeof(multiqc_files) / 1048576
    # return multiqc_files
    return {"Message": "OK", "Size": f"{size_in_megabytes:.2f}", "Query elapsed time": f"{elapsed_time:.6f}s"}


@app.get("/workflows")
async def get_workflows():
    # Check if the results are already in the cache
    # if redis_client.exists("workflows"):
    #     workflows = redis_client.get("workflows")
    #     return jsonable_encoder(workflows)

    workflows = mongo_db.list_collection_names()
    print(workflows)
    # Cache the results
    # redis_client.setex("workflows", settings.redis_cache_ttl, jsonable_encoder(workflows))

    return workflows


@app.get("/runs/{workflow_name}")
async def get_runs(workflow_name: str):
    # Check if the results are already in the cache
    # if redis_client.exists("workflows"):
    #     workflows = redis_client.get("workflows")
    #     return jsonable_encoder(workflows)

    result = dict()
    collection = mongo_db[workflow_name]
    run_names = collection.distinct("run_name", {"wf_name": workflow_name})
    result[workflow_name] = run_names
    # Cache the results
    # redis_client.setex("workflows", settings.redis_cache_ttl, jsonable_encoder(workflows))

    return result


@app.get("/multiqc_data_sources/{workflow_name}")
async def get_data_sources(workflow_name: str):
    # Check if the results are already in the cache
    # if redis_client.exists("workflows"):
    #     workflows = redis_client.get("workflows")
    #     return jsonable_encoder(workflows)

    result = dict()
    collection = mongo_db[workflow_name]
    data_sources = collection.distinct("metadata.report_data_sources", {"wf_name": workflow_name})
    result[workflow_name] = data_sources
    # Cache the results
    # redis_client.setex("workflows", settings.redis_cache_ttl, jsonable_encoder(workflows))

    return result


# Start observing the MultiQC directory for new files
# multiqc_watcher.observe_multiqc_files(settings)
