# from src import multiqc_watcher
from fastapi import FastAPI, Depends, HTTPException
import pymongo
from src import config, models
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from typing import List, Optional


app = FastAPI()
settings = config.Settings.from_yaml("config.yaml")

# Set up the MongoDB client and database
client = pymongo.MongoClient(settings.mongo_url)
db = client[settings.mongo_db]
multiqc_files_collection = db["multiqc_files"]


# Test MongoDB connection
try:
    client.server_info()
    print("Connected to MongoDB!")
except pymongo.errors.ConnectionFailure:
    print("Failed to connect to MongoDB.")


@app.post("/multiqc_files/")
async def create_multiqc_file(multiqc_file: models.MultiQCFile):
    # Check if the multiqc_file already exists in the collection
    existing_file = multiqc_files_collection.find_one({"file_path": multiqc_file.file_path})
    if existing_file:
        return {"message": "File already exists in the database."}
    else:

        # Insert the new multiqc_file document into the collection
        result = multiqc_files_collection.insert_one(multiqc_file.dict())
        return {"inserted_id": str(result.inserted_id)}


@app.get("/multiqc_files/{workflow_name}")
async def get_multiqc_files(workflow_name: str, run_name: Optional[str] = None):
    print(workflow_name)
    # Find all documents in the collection with the specified workflow name
    q_dict = {"wf_name": workflow_name}
    print(workflow_name, run_name, type(run_name))
    if run_name:
        q_dict["run_name"] = run_name
    print(q_dict)
    multiqc_files_query = list(multiqc_files_collection.find(q_dict))
    print(multiqc_files_query)

    multiqc_files = list()

    for file in multiqc_files_query:
        # Convert ObjectId instances to strings
        file["_id"] = str(file["_id"])
        # Serialize the object using jsonable_encoder
        multiqc_files.append(jsonable_encoder(file))

    return multiqc_files


@app.get("/workflows")
async def get_workflows():
    workflows = multiqc_files_collection.distinct("wf_name")
    return {"workflows": workflows}


# Start observing the MultiQC directory for new files
# multiqc_watcher.observe_multiqc_files(settings)
