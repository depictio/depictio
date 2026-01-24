"""
Background task management for data collection processing.

Handles delayed processing of data collections after API startup.
"""

import asyncio
import os
import threading
import time

from depictio.api.v1.configs.logging_init import logger

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
    Process all reference datasets after a delay to ensure the API is fully started.

    Replaces hardcoded iris processing with multi-dataset support.

    Returns:
        A future that can be cancelled during shutdown (placeholder for compatibility)
    """
    # Wait for API to fully start
    delay = 5
    logger.info(f"Worker {WORKER_ID}: Waiting {delay}s before processing reference datasets")
    time.sleep(delay)

    # Process all datasets (replaces iris-specific logic)
    from depictio.api.v1.services.process_reference_datasets import process_all_reference_datasets

    logger.info(f"Worker {WORKER_ID}: Starting reference dataset processing thread")
    thread = threading.Thread(
        target=lambda: asyncio.run(process_all_reference_datasets()),
        daemon=True,
    )
    thread.start()

    return asyncio.Future()
