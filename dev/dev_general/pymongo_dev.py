from pprint import pprint

import pymongo

mongo_client = pymongo.MongoClient("mongodb://localhost:27018/")
mongo_db = mongo_client["depictioDB"]

workflow_name = "ashleys-qc-pipeline"
collection = mongo_db[workflow_name]
data_sources = collection.distinct(
    "metadata.report_general_stats_headers", {"wf_name": workflow_name}
)
pprint(data_sources)

import pandas as pd

print(pd.DataFrame.from_records(data_sources))
df = pd.json_normalize(data_sources, max_level=1)
print(df.T)
