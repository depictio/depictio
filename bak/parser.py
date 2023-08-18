import os
import pandas as pd
import pydantic
import magic
import typing as tp
import gzip
import pyarrow.parquet as pq
import pyarrow.feather as feather
import pymongo
import pickle
import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Define the FastAPI app
app = FastAPI()

# Define a list of supported file formats
class TabularFileFormats(str, pydantic.BaseModel):
    csv = "text/csv"
    tsv = "text/tab-separated-values"
    parquet = "application/x-parquet"
    feather = "application/x-feather"


# Define a list of supported file extensions for each format
supported_file_extensions = {
    TabularFileFormats.csv: ["csv"],
    TabularFileFormats.tsv: ["tsv"],
    TabularFileFormats.parquet: ["parquet"],
    TabularFileFormats.feather: ["feather"],
}

# Define a pydantic model to represent a tabular file
class TabularFile(pydantic.BaseModel):
    path: str
    format: TabularFileFormats
    header: tp.List[str]
    data: pd.DataFrame


# Define a function to check if the processed data is already stored in the cache or the database
def get_cached_data(
    file_path: str, cache: redis.Redis, db: pymongo.MongoClient;;
) -> tp.Optional[TabularFile]:
    # Check if the processed data is already stored in the cache
    data_bytes = cache.get(file_path)
    if data_bytes:
        return pickle.loads(data_bytes)
    # Check if the processed data is already stored in the database
    collection = db["files"]
    row = collection.find_one({"path": file_path})
    if row:
        return TabularFile.parse_obj(
            {
                "path": row["path"],
                "format": row["format"],
                "header": row["header"],
                "data": pd.read_pickle(row["data"]),
            }
        )
    return None


# Define a function to store the processed data in the cache and the database
def store_processed_data(
    data: TabularFile, cache: redis.Redis, db: pymongo.MongoClient
):
    # Store the processed data in the cache
    cache.set(data.path, pickle.dumps(data))
    # Store the processed data in the database
    collection = db["files"]
    collection.insert_one(
        {
            "path": data.path,
            "format": data.format,
            "header": data.header,
            "data": pickle.dumps(data.data),
        }
    )


# Define a pydantic model to represent a request body
class FileInput(BaseModel):
    filename: str
    data: bytes


# Define the API endpoint to upload a file
@app.post("/upload_file/")
async def upload_file(file_input: FileInput):
    # Get the file extension
    file_extension = os.path.splitext(file_input.filename)[1].lstrip(".")
    # Check if the file extension matches a supported format
    supported_formats = [
        format
        for format, extensions in supported_file_extensions.items()
        if file_extension in extensions
    ]
    if supported_formats:
        # Detect the file format using python-magic
        file_bytes = file_input.data
        file_format = magic.from_buffer(file_bytes, mime=True)
        if file_format in supported_formats:
            # Read the file into a pandas DataFrame
            file_name = file_input.filename
            file_path = os.path.join(output_dir, file_name)
            with open(file_path, "wb") as f:
                f.write(file_bytes)
