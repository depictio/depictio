import collections
from io import BytesIO
import sys

import bson
from jose import JWTError
import jwt

sys.path.append("/Users/tweber/Gits/depictio")

from depictio.api.v1.db import grid_fs, redis_cache
from depictio.api.v1.configs.config import settings
# from CLI_client.cli import list_workflows
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
# API_BASE_URL = "http://host.docker.internal:8058"



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


token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NGE4NDI4NDJiZjRmYTdkZWFhM2RiZWQiLCJleHAiOjE3ODQ5ODY3ODV9.a5bkSctoCNYXVh035g_wt-bio3iC3uuM9anFKiJOKrmBHDH0tmcL2O9Rc1HIQtAxCH-mc1K4q4aJsAO8oeayuPyA3w7FPIUnLsZGRHB8aBoDCoxEIpmACi0nEH8hF9xd952JuBt6ggchyMyrnxHC65Qc8mHC9PeylWonHvNl5jGZqi-uhbeLpsjuPcsyg76X2aqu_fip67eJ8mdr6yuII6DLykpfbzALpn0k66j79YzOzDuyn4IjBfBPWiqZzl_9oDMLK7ODebu6FTDmQL0ZGto_dxyIJtkf1CdxPaYkgiXVOh00Y6sXJ24jHSqfNP-dqvAQ3G8izuurq6B4SNgtDw"

from depictio.api.v1.endpoints.user_endpoints.auth import (
    ALGORITHM,
    PUBLIC_KEY,
    fetch_user_from_id,
)

def return_user_from_token(token: str) -> dict:
    # print(token)
    # print(PUBLIC_KEY)
    # print(ALGORITHM)
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            print("Token is invalid or expired.")
            raise sys.exit(code=1)
        # Fetch user from the database or wherever it is stored
        user = fetch_user_from_id(user_id)
        return user
    except JWTError as e:
        print(f"Token verification failed: {e}")
        raise sys.exit(code=1)


def list_workflows(token: str = None):
    if not token:
        print("A valid token must be provided for authentication.")
        raise sys.exit(code=1)

    # print(token)
    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        print("Invalid token or unable to decode user information.")
        raise sys.exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory


    # print(token)
    workflows = httpx.get(f"{API_BASE_URL}/depictio/api/v1/workflows/get", headers=headers)
    workflows_json = workflows.json()
    # pretty_workflows = json.dumps(workflows_json, indent=4)
    # typer.echo(pretty_workflows)
    return workflows_json


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
            # print(json_cols)
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
    # print(workflows)

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
            
            # Get data_collection_id from data_collection_tag
            # print('tmp_load_deltatable')
            # print("workflow_id", workflow_id)
            # print("data_collection_tag", data_collection_tag)
            # data_collection_id = [
            #     f
            #     for e in workflows
            #     if e["_id"] == workflow_id
            #     for f in e["data_collections"]
            #     if f["data_collection_tag"] == data_collection_tag
            # ][0]["_id"]

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

        # print("main_data_collection_df")
        # print(main_data_collection_df)


        if raw == True:
            # print("Raw data = TRUE")
            return main_data_collection_df
        
        else:
            # print("Raw data = FALSE")


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
                        for tmp_dc_tag in join["with_dc"]:
                            print("tmp_dc_tag")
                            print(tmp_dc_tag)
                            # check if tmp_dc_tag is str or pyobjectid
                            # if str, retrieve pyobjectid
                            # else skip
                            if not bson.objectid.ObjectId.is_valid(tmp_dc_tag): 
                                print("tmp_dc_tag is not valid pyobjectid")
                                print(tmp_dc_tag)
                                print("workflow_id")
                                print(workflow_id)
                                # print(workflows)
                                # print([
                                #     f
                                #     for e in workflows
                                #     if e["_id"] == workflow_id
                                #     for f in e["data_collections"]
                                #     if f["data_collection_tag"] == tmp_dc_tag
                                # ])
                                tmp_dc_id = None
                                for e in workflows:
                                    print(e["_id"], workflow_id, e["_id"] == workflow_id)
                                    for f in e["data_collections"]:
                                        print(f["data_collection_tag"], tmp_dc_tag, f["data_collection_tag"] == tmp_dc_tag)
                                        if f["data_collection_tag"] == tmp_dc_tag:
                                            print(f["_id"])
                                            tmp_dc_id = f["_id"]
                                            break
                                        
                            else:
                                tmp_dc_id = tmp_dc_tag
                            tmp_df = tmp_load_deltatable(str(workflow_id), str(tmp_dc_id))
                            # TODO: remove this - used for debugging
                            tmp_df["cell"] = tmp_df["cell"].str.replace(".sort.mdup.bam", "")
                            # print("tmp_df")
                            # print(tmp_df)
                            # print("\n")
                            main_data_collection_df = pd.merge(main_data_collection_df, tmp_df, on=["depictio_run_id"] + join["on_columns"])
                            # print("main_data_collection_df")
                            # print(main_data_collection_df)
            # print("Raw data = FALSE")

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
