import collections
from io import BytesIO
import sys

sys.path.append("/Users/tweber/Gits/depictio")

from depictio.api.v1.db import grid_fs, redis_cache
from depictio.api.v1.configs.config import settings
from CLI_client.cli import list_workflows
import httpx
from bson import ObjectId
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import inspect
import numpy as np
import os, json
import pandas as pd
import plotly.express as px
import re

API_BASE_URL = "http://localhost:8058"




SELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "border": "3px solid",
    "opacity": 1,
}

UNSELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "opacity": 0.65,
}


def load_data():
    if os.path.exists("data.json"):
        with open("data.json", "r") as file:
            data = json.load(file)
            print(data)
        return data
    return None


def load_gridfs_file(workflow_id: str, data_collection_id: str, cols: list = None):
    print(workflow_id, data_collection_id)

    if workflow_id is None or data_collection_id is None:
        response = httpx.get(f"{API_BASE_URL}/api/v1/workflows/get_workflows")
        print(response)
        if response.status_code == 200:
            workflow_id = response.json()[0]["workflow_id"]
            data_collection_id = response.json()[0]["data_collection_ids"][0]
            print(response.json())

        else:
            print("No workflows found")
            return None

    print(workflow_id)

    workflow_engine = workflow_id.split("/")[0]
    workflow_name = workflow_id.split("/")[1]

    print(workflow_engine, workflow_name)
    print(data_collection_id)

    response = httpx.get(
        f"{API_BASE_URL}/api/v1/datacollections/get_aggregated_file_id/{workflow_engine}/{workflow_name}/{data_collection_id}"
    )
    print(response)

    if response.status_code == 200:
        file_id = response.json()["gridfs_file_id"]

        # Get the file from GridFS

        # Check if present in redis cache otherwise load and save to redis

        if redis_cache.exists(file_id):
            print("Loading from redis cache")
            # Convert the binary data to a BytesIO stream
            data_stream = BytesIO(redis_cache.get(file_id))
            if not cols:
                df = pd.read_parquet(data_stream)
            else:
                df = pd.read_parquet(data_stream, columns=cols)

        else:
            print("Loading from gridfs")
            associated_file = grid_fs.get(ObjectId(file_id))
            if not cols:
                df = pd.read_parquet(associated_file)
            else:
                df = pd.read_parquet(associated_file, columns=cols)
            redis_cache.set(file_id, df.to_parquet())

        return df


def get_columns_from_data_collection(
    workflow_id: str,
    data_collection_id: str,
):
    print("get_columns_from_data_collection")
    print(workflow_id, data_collection_id)

    if workflow_id is not None and data_collection_id is not None:
        # print("OK")
        # print(workflow_id, data_collection_id)
        workflow_engine = workflow_id.split("/")[0]
        workflow_name = workflow_id.split("/")[1]
        # print(workflow_engine, workflow_name)
        response = httpx.get(
            f"{API_BASE_URL}/api/v1/datacollections/get_columns/{workflow_engine}/{workflow_name}/{data_collection_id}"
        )
        # print(response)
        if response.status_code == 200:
            json = response.json()
            # print(json)
            return json
        else:
            print("No workflows found")
            return None


def list_workflows_for_dropdown():
    workflows = [wf["workflow_id"] for wf in list_workflows()]
    workflows_dict_for_dropdown = [{"label": wf, "value": wf} for wf in workflows]
    print(workflows_dict_for_dropdown)
    return workflows_dict_for_dropdown


def list_data_collections_for_dropdown(workflow_id: str = None):
    if workflow_id is None:
        return []
    else:
        data_collections = [
            dc
            for wf in list_workflows()
            for dc in wf["data_collection_ids"]
            if wf["workflow_id"] == workflow_id
        ]
        data_collections_dict_for_dropdown = [
            {"label": dc, "value": dc} for dc in data_collections
        ]
        return data_collections_dict_for_dropdown


# TODO: utils / config

