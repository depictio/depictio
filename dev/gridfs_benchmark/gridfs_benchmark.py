import io
import time

import pandas as pd
from gridfs import GridFS
from pymongo import MongoClient

# Connect to MongoDB and GridFS
client = MongoClient("mongodb://localhost:27018/")
db = client["mydatabase"]
fs = GridFS(db)


def benchmark_format(data, serialize_fn, deserialize_fn, ext):
    # Serialize and store
    start_time = time.time()
    serialized_data = serialize_fn(data)
    file_id = fs.put(serialized_data, filename=f"test.{ext}")
    store_time = time.time()
    serialize_store_time = store_time - start_time

    # Retrieve and deserialize
    retrieve_start_time = time.time()
    retrieved_data = fs.get(file_id).read()
    deserialized_data = deserialize_fn(retrieved_data)
    retrieve_deserialize_time = time.time() - retrieve_start_time

    # Cleanup: remove stored file from GridFS
    fs.delete(file_id)

    return serialize_store_time, retrieve_deserialize_time


def pickle_serialize(data):
    buf = io.BytesIO()
    data.to_pickle(buf)
    buf.seek(0)
    return buf.read()


def feather_serialize(data):
    buf = io.BytesIO()
    data.to_feather(buf)
    buf.seek(0)
    return buf.read()


def feather_deserialize(f):
    return pd.read_feather(io.BytesIO(f))


def parquet_serialize(data):
    buf = io.BytesIO()
    data.to_parquet(buf)
    buf.seek(0)
    return buf.read()


def parquet_deserialize(f):
    return pd.read_parquet(io.BytesIO(f))


serializers = {
    "pickle": (pickle_serialize, lambda f: pd.read_pickle(io.BytesIO(f)), "pkl"),
    "feather": (feather_serialize, feather_deserialize, "feather"),
    "parquet": (parquet_serialize, parquet_deserialize, "parquet"),
    # Add other formats as needed
}

# Varying the number of rows
# rows_list = [int(1e5), int(1e6), int(1e7)]
# columns_fixed = 2

# for num_rows in rows_list:
#     df = pd.DataFrame({f"col_{i}": range(num_rows) for i in range(columns_fixed)})
#     for name, (serializer, deserializer, ext) in serializers.items():
#         serialize_time, deserialize_time = benchmark_format(
#             df, serializer, deserializer
#         )
#         print(
#             f"{name} with {num_rows} rows: Serialize & Store: {serialize_time:.2f}s, Retrieve & Deserialize: {deserialize_time:.2f}s"
#         )

# Varying the number of columns
columns_list = [5, 10, 20, 50, 100]
rows_list = [int(1e4), int(1e5), int(1e6), int(1e7)]

for num_columns in columns_list:
    for rows_fixed in rows_list:
        df = pd.DataFrame({f"col_{i}": range(rows_fixed) for i in range(num_columns)})
        for name, (serializer, deserializer, ext) in serializers.items():
            serialize_time, deserialize_time = benchmark_format(df, serializer, deserializer, ext)
            print(
                f"{name} with {num_columns} columns and {rows_fixed} rows: Serialize & Store: {serialize_time:.2f}s, Retrieve & Deserialize: {deserialize_time:.2f}s"
            )
        print("\n\n")
