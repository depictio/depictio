
from bson import ObjectId
import httpx
import polars as pl
import pandas as pd
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN
from depictio.api.v1.s3 import s3_client, minio_storage_options
from depictio.api.v1.configs.config import logger

def load_deltatable_lite(workflow_id: ObjectId, data_collection_id: ObjectId, cols: list = None, raw: bool = False):
    # print("load_deltatable_lite")

    # Turn objectid to string
    workflow_id = str(workflow_id)
    data_collection_id = str(data_collection_id)

    # Get file location corresponding to Dfrom API
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{workflow_id}/{data_collection_id}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )

    # Check if the response is successful
    if response.status_code == 200:
        file_id = response.json()["delta_table_location"]

        ### FIXME: not-delete below - optimise and benchmark to check if redis is useful or if optimised polars read is more eficient

        # if redis_cache.exists(file_id):
        #     # print("Loading from redis cache")
        #     data_stream = BytesIO(redis_cache.get(file_id))
        #     data_stream.seek(0)  # Important: reset stream position to the beginning
        #     df = pl.read_parquet(data_stream, columns=cols if cols else None)
        #     # print(df)
        # else:
        #     # print("Loading from DeltaTable")

        #     # Convert DataFrame to parquet and then to bytes
        #     output_stream = BytesIO()
        #     df.write_parquet(output_stream)
        #     output_stream.seek(0)  # Reset stream position after writing
        #     redis_cache.set(file_id, output_stream.read())

        # Read the file from DeltaTable using polars and convert to pandas

        df = pl.read_delta(file_id, columns=cols if cols else None, storage_options=minio_storage_options)

        # TODO: move to polars
        df = df.to_pandas()
        return df
    else:
        raise Exception("Error loading deltatable")


def join_deltatables(workflow_id: str, data_collection_id: str):
    # Turn str to objectid
    workflow_id = ObjectId(workflow_id)
    data_collection_id = ObjectId(data_collection_id)

    # Load the main data collection
    main_data_collection_df = load_deltatable_lite(workflow_id, data_collection_id)

    # FIXME: remove the column "Depictio_aggregation_time" from the main data collection
    main_data_collection_df = main_data_collection_df.drop(["depictio_aggregation_time"], axis=1)

    # Get join tables for the workflow
    join_tables_for_wf = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_join_tables/{workflow_id}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    # print("main_data_collection_df")
    print(main_data_collection_df)
    # print("join_tables_for_wf")
    # print(join_tables_for_wf.json())

    logger.info("Join tables for workflow")
    logger.info(join_tables_for_wf.json())

    # Check if the response is not successful
    if join_tables_for_wf.status_code != 200:
        raise Exception("Error loading join tables")

    elif join_tables_for_wf.status_code == 200:
        # Check if the data collection is present in the join config of other data collections
        if str(data_collection_id) in join_tables_for_wf.json():
            # Extract the join tables for the current data collection
            join_tables_dict = join_tables_for_wf.json()[str(data_collection_id)]

            # print('join_tables_dict["with_dc_id"]')
            # print(join_tables_dict["with_dc_id"])
            # Iterate over the data collections that the current data collection is joined with
            for tmp_dc_id in join_tables_dict["with_dc_id"]:
                logger.info(tmp_dc_id)
                # Load the deltable from the join data collection
                tmp_df = load_deltatable_lite(str(workflow_id), str(tmp_dc_id))

                print(tmp_df)
                # Merge the main data collection with the join data collection on the specified columns
                # NOTE: hard-coded join for depictio_run_id currently (defined when creating the DeltaTable)
                tmp_df = tmp_df.drop(["depictio_aggregation_time"], axis=1)
                if "Metadata" in tmp_df["depictio_run_id"].values.tolist():
                    tmp_df = tmp_df.drop(["depictio_run_id"], axis=1)

                join_columns = join_tables_dict["on_columns"]
                if ("depictio_run_id" in main_data_collection_df.columns) and ("depictio_run_id" in tmp_df.columns):
                    join_columns = ["depictio_run_id"] + join_columns

                # print("tmp_df")
                # print(tmp_df)
                print(main_data_collection_df)
                main_data_collection_df = pd.merge(main_data_collection_df, tmp_df, on=join_columns)
                # print("main_data_collection_df AFTER MERGE")
                # print(main_data_collection_df)
                # print(main_data_collection_df.columns)

    # print(main_data_collection_df)
    return main_data_collection_df
