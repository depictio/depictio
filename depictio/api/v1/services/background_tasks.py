"""
Background task management for data collection processing.

Handles delayed processing of data collections after API startup.
"""

import asyncio
import os
import threading
import time

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import process_collections

WORKER_ID = os.getpid()


def check_s3_delta_table_exists(bucket: str, data_collection_id: str) -> bool:
    """
    Check if a delta table exists in S3 by looking for the _delta_log directory.

    Args:
        bucket: S3 bucket name
        data_collection_id: Data collection ID (used as S3 prefix)

    Returns:
        True if delta table exists in S3, False otherwise
    """
    from depictio.api.v1.s3 import s3_client

    try:
        delta_log_prefix = f"{data_collection_id}/_delta_log/"
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=delta_log_prefix, MaxKeys=1)
        exists = "Contents" in response and len(response["Contents"]) > 0

        if exists:
            logger.info(
                f"Worker {WORKER_ID}: Delta table found in S3 at s3://{bucket}/{data_collection_id}"
            )
        else:
            logger.info(
                f"Worker {WORKER_ID}: Delta table NOT found in S3 at s3://{bucket}/{data_collection_id}"
            )

        return exists

    except Exception as e:
        logger.error(f"Worker {WORKER_ID}: Error checking S3 for delta table: {e}")
        return False


def delayed_process_data_collections() -> asyncio.Future:
    """
    Process initial data collections after a delay to ensure the API is fully started.

    Skips processing if delta table already exists in S3 (for multi-instance deployments).

    Returns:
        A future that can be cancelled during shutdown (placeholder for compatibility)
    """
    from depictio.api.v1.db import deltatables_collection, projects_collection

    # Find the iris_table data collection
    project_doc = projects_collection.find_one(
        {"workflows.data_collections.data_collection_tag": "iris_table"}
    )

    if project_doc:
        workflows = project_doc.get("workflows", [])
        if workflows:
            data_collections = workflows[0].get("data_collections", [])
            if data_collections:
                dc_id = data_collections[0].get("_id")

                if dc_id:
                    # Check if already processed in local MongoDB
                    if deltatables_collection.find_one({"data_collection_id": dc_id}, {"_id": 1}):
                        logger.info(
                            f"Worker {WORKER_ID}: Data collections already processed in local DB, skipping"
                        )
                        return asyncio.Future()

                    # Check S3 for existing delta table (multi-instance scenario)
                    dc_id_str = str(dc_id)
                    if check_s3_delta_table_exists(settings.minio.bucket, dc_id_str):
                        logger.info(
                            f"Worker {WORKER_ID}: Delta table exists in S3, will process with overwrite=True"
                        )

    # Wait for API to fully start
    logger.info(f"Worker {WORKER_ID}: Waiting 5 seconds before processing data collections")
    time.sleep(5)

    # Run processing in a background thread
    logger.info(f"Worker {WORKER_ID}: Starting data collection processing thread")
    thread = threading.Thread(target=process_collections, daemon=True)
    thread.start()

    return asyncio.Future()
