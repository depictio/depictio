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
import polars as pl
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
    "border": "3px solid",
    "opacity": 1,
}


def load_data():
    if os.path.exists("data.json"):
        with open("data.json", "r") as file:
            data = json.load(file)
            # print(data.keys())
        return data
    return None


token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NGE4NDI4NDJiZjRmYTdkZWFhM2RiZWQiLCJleHAiOjE3MDY4NTQzOTJ9.q3sJLcwEwes32JoeAEGQdjlaTnn6rC1xmfHs2jjwJuML1jWgWBzuv37fJDb70y7-pRaRjTojAz9iGcUPC91Zc9krbmO6fXedLVre8a4_TvsgVwZTSPXpikA_t6EeHYjVxCDh_FftGZv0hXeRbOV83ob7GykkUP5HWTuXrv_o8v4S8ccnsy3fVIIy51NZj6MuU4YL2BfPDuWdBp2d0IN2UDognt1wcwsjIt_26AQJQHwQaxDevvzlNA6RvQIcxC5Es5PSHfpaF7w4MxiZ6J-JE25EnQ7Fw1k-z7bsleb_30Qdh68Kjs-c-BOoTm_hxDF-15G9qLPhFTqJMl148oxAjw"


def list_workflows_for_dropdown():
    workflows_model_list = list_workflows(token)
    workflows = [wf["workflow_tag"] for wf in workflows_model_list]
    workflows_dict_for_dropdown = [{"label": wf, "value": wf} for wf in workflows]
    return workflows_dict_for_dropdown


def list_data_collections_for_dropdown(workflow_tag: str = None):
    if workflow_tag is None:
        return []
    else:
        data_collections = [
            dc["data_collection_tag"]
            for wf in list_workflows(token)
            for dc in wf["data_collections"]
            if wf["workflow_tag"] == workflow_tag
        ]
        data_collections_dict_for_dropdown = [
            {"label": dc, "value": dc} for dc in data_collections
        ]
        return data_collections_dict_for_dropdown


# TODO: utils / config


def get_columns_from_data_collection(
    workflow_id: str,
    data_collection_id: str,
):
    # print("\n\n\n")
    # print("get_columns_from_data_collection")

    workflows = list_workflows(token)
    workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_id][0]["_id"]
    data_collection_id = [
        f
        for e in workflows
        if e["_id"] == workflow_id
        for f in e["data_collections"]
        if f["data_collection_tag"] == data_collection_id
    ][0]["_id"]

    if workflow_id is not None and data_collection_id is not None:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {token}",
            },
        )
        # print(response)
        if response.status_code == 200:
            json = response.json()

            json_cols = json["columns"]
            reformat_cols = collections.defaultdict(dict)
            print(json_cols)
            for c in json_cols:
                reformat_cols[c["name"]]["type"] = c["type"]
                reformat_cols[c["name"]]["description"] = c["description"]
                reformat_cols[c["name"]]["specs"] = c["specs"]
            return reformat_cols
        else:
            print("No workflows found")
            return None


def load_deltatable(workflow_id: str, data_collection_id: str, cols: list = None, raw: bool = False):
    workflows = list_workflows(token)

    if workflow_id is None or data_collection_id is None:
        default_workflow = workflows[0]
        workflow_id = default_workflow["_id"]
        data_collection_id = default_workflow["data_collections"][0]["_id"]

    else:

        try:
            # check if workflow_id and data_collection_id can be converted to ObjectId
            # print("try")
            # print(workflow_id, data_collection_id)
            workflow_id = ObjectId(workflow_id)
            data_collection_id = ObjectId(data_collection_id)
            # print(workflow_id, data_collection_id)
            # check if workflow_id and data_collection_id are valid ObjectId
            # assert workflows_collection.find_one({"_id": workflow_id}) is not None
            # assert (
            #     workflow_id in [e["_id"] for e in workflows]
            # ), "Workflow ID not found"
            # assert (
            #     data_collection_id
            #     in [
            #         f["_id"]
            #         for e in workflows
            #         for f in e["data_collections"]
            #         if e["_id"] == workflow_id
            #     ]
            # ), "Data collection ID not found"
            

        except:
            workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_id][0][
                "_id"
            ]
            data_collection_id = [
                f
                for e in workflows
                if e["_id"] == workflow_id
                for f in e["data_collections"]
                if f["data_collection_tag"] == data_collection_id
            ][0]["_id"]

        # Check if there is join defined in config
        # if so, load the joined data collection
        # if not, load the data collection

        headers = {
            "Authorization": f"Bearer {token}",
        }





        def tmp_load_deltatable(workflow_id: str, data_collection_id: str):
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{workflow_id}/{data_collection_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                },
            )

            if response.status_code == 200:
                file_id = response.json()["delta_table_location"]
                # print(file_id)


                if redis_cache.exists(file_id):
                    # print("Loading from redis cache")
                    data_stream = BytesIO(redis_cache.get(file_id))
                    data_stream.seek(0)  # Important: reset stream position to the beginning
                    df = pl.read_parquet(data_stream, columns=cols if cols else None)
                    # print(df)
                else:
                    # print("Loading from DeltaTable")
                    df = pl.read_delta(file_id, columns=cols if cols else None)

                    # Convert DataFrame to parquet and then to bytes
                    output_stream = BytesIO()
                    df.write_parquet(output_stream)
                    output_stream.seek(0)  # Reset stream position after writing
                    redis_cache.set(file_id, output_stream.read())
                # TODO: move to polars
                df = df.to_pandas()
                return df
            else:
                raise Exception("Error loading deltatable")



        main_data_collection_df = tmp_load_deltatable(workflow_id, data_collection_id)

        print("main_data_collection_df")
        print(main_data_collection_df)


        if raw == True:
            print("Raw data = TRUE")
            return main_data_collection_df
        
        else:


            # print(main_data_collection_df)
            # TODO: URGENT: remove this - used for debugging
            if "cell" in main_data_collection_df.columns:
                main_data_collection_df["cell"] = main_data_collection_df["cell"].str.replace(".sort.mdup.bam", "")




            # print("\n\n\n")
            # print("JOIN TABLES")

            join_tables_for_wf = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/workflows/get_join_tables/{workflow_id}",
                headers=headers,
            )

        
            if join_tables_for_wf.status_code == 200:
                # print(join_tables_for_wf.json())
                if str(data_collection_id) in join_tables_for_wf.json():
                    # print(data_collection_id)
                    for join in join_tables_for_wf.json()[str(data_collection_id)]:
                        # print(["depictio_run_id"] + join["on"])
                        for tmp_dc_id in join["with_dc"]:
                            # print(tmp_dc_id)
                            tmp_df = tmp_load_deltatable(str(workflow_id), str(tmp_dc_id))
                            # TODO: remove this - used for debugging
                            tmp_df["cell"] = tmp_df["cell"].str.replace(".sort.mdup.bam", "")
                            # print("tmp_df")
                            # print(tmp_df)
                            # print("\n")
                            main_data_collection_df = pd.merge(main_data_collection_df, tmp_df, on=["depictio_run_id"] + join["on"])
                            # print("main_data_collection_df")
                            # print(main_data_collection_df)

            return main_data_collection_df

                        
                    
        #             tmp_df = 
        #             print(tmp_df)

        # print(join_tables_for_wf.json())
        # for association in join_tables_for_wf:
        #     print(association)
        #     if data_collection_id in association:
        #         for tmp_dc_id in association:
        #             print(tmp_dc_id)
        #             tmp_df = load_deltatable(workflow_id, tmp_dc_id)

        #     # print(association["join"])
        #     #

        # print(
        #     [
        #         f["join"]
        #         for e in workflows
        #         if e["_id"] == workflow_id
        #         for f in e["data_collections"]
        #     ]
        # )

    # print(workflow_id)

    # workflow_engine = workflow_id.split("/")[0]
    # workflow_name = workflow_id.split("/")[1]

    # print(workflow_engine, workflow_name)
    # print(data_collection_id)

    # response = httpx.get(
    #     f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{workflow_id}/{data_collection_id}",
    #     headers={
    #         "Authorization": f"Bearer {token}",
    #     },
    # )

    # if response.status_code == 200:
    #     file_id = response.json()["delta_table_location"]

    #     # Get the file from GridFS

    #     # Check if present in redis cache otherwise load and save to redis

    #     if redis_cache.exists(file_id):
    #         # print("Loading from redis cache")
    #         data_stream = BytesIO(redis_cache.get(file_id))
    #         data_stream.seek(0)  # Important: reset stream position to the beginning
    #         df = pl.read_parquet(data_stream, columns=cols if cols else None)
    #         # print(df)
    #     else:
    #         # print("Loading from DeltaTable")
    #         df = pl.read_delta(file_id, columns=cols if cols else None)

    #         # Convert DataFrame to parquet and then to bytes
    #         output_stream = BytesIO()
    #         df.write_parquet(output_stream)
    #         output_stream.seek(0)  # Reset stream position after writing
    #         redis_cache.set(file_id, output_stream.read())
    #     # TODO: move to polars
    #     df = df.to_pandas()
    #     return df
