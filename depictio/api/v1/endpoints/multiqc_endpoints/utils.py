"""Utility functions for MultiQC endpoints."""

from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import multiqc_collection
from depictio.api.v1.s3 import s3_client

# Import build_sample_mapping from CLI utils to avoid code duplication
# This function is now shared between API and CLI without circular dependencies
from depictio.cli.cli.utils.sample_mapping import build_sample_mapping
from depictio.models.models.multiqc_reports import MultiQCReport

# Re-export for backward compatibility
__all__ = ["build_sample_mapping"]


async def check_duplicate_multiqc_report(
    data_collection_id: str, original_file_path: str
) -> Optional[MultiQCReport]:
    """
    Check if a MultiQC report already exists for the same data collection and file path.

    Args:
        data_collection_id: ID of the data collection
        original_file_path: Original local file path of the MultiQC report

    Returns:
        Existing MultiQC report if found, None otherwise
    """
    try:
        query = {
            "data_collection_id": data_collection_id,
            "original_file_path": original_file_path,
        }
        report_doc = multiqc_collection.find_one(query)

        if report_doc:
            report_doc["id"] = str(report_doc["_id"])
            logger.info(
                f"Found existing MultiQC report for DC {data_collection_id}, file {original_file_path}"
            )
            return MultiQCReport(**report_doc)

        return None

    except Exception as e:
        logger.warning(f"Failed to check for duplicate MultiQC report: {e}")
        return None


async def create_multiqc_report_in_db(report: MultiQCReport) -> MultiQCReport:
    """
    Create a new MultiQC report in the database.

    Args:
        report: MultiQC report data to save

    Returns:
        Created MultiQC report with assigned ID

    Raises:
        HTTPException: If database insertion fails
    """
    try:
        # Convert report to MongoDB document format
        report_dict = report.model_dump()

        # Generate new ObjectId for the document
        new_id = ObjectId()
        report_dict["_id"] = new_id
        report_dict["id"] = str(new_id)

        # Insert into MongoDB
        result = multiqc_collection.insert_one(report_dict)

        if not result.inserted_id:
            raise HTTPException(
                status_code=500, detail="Failed to insert MultiQC report into database"
            )

        # Return the saved report
        return MultiQCReport(**report_dict)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create MultiQC report: {str(e)}")


async def update_multiqc_report_by_id(
    report_id: str, updated_report: MultiQCReport
) -> MultiQCReport:
    """
    Update an existing MultiQC report in the database.

    Args:
        report_id: ID of the MultiQC report to update
        updated_report: Updated MultiQC report data

    Returns:
        Updated MultiQC report

    Raises:
        HTTPException: If report not found or update fails
    """
    try:
        # Verify the report exists
        existing_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not existing_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert updated report to dict, excluding id fields
        update_dict = updated_report.model_dump(exclude={"id"}, exclude_none=True)

        # Update the document
        result = multiqc_collection.update_one({"_id": ObjectId(report_id)}, {"$set": update_dict})

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        if result.modified_count == 0:
            logger.warning(f"MultiQC report {report_id} was matched but not modified")

        # Fetch and return the updated report
        updated_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if updated_doc:
            updated_doc["id"] = str(updated_doc["_id"])
            return MultiQCReport(**updated_doc)
        else:
            raise HTTPException(status_code=500, detail="Failed to retrieve updated report")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update MultiQC report: {str(e)}")


async def get_multiqc_reports_by_data_collection(
    data_collection_id: str, limit: int = 50, offset: int = 0
) -> tuple[List[MultiQCReport], int]:
    """
    Get MultiQC reports for a specific data collection.

    Args:
        data_collection_id: ID of the data collection
        limit: Maximum number of reports to return
        offset: Number of reports to skip

    Returns:
        Tuple of (reports list, total count)

    Raises:
        HTTPException: If database query fails
    """
    try:
        # Query for all reports associated with this data collection
        query = {"data_collection_id": data_collection_id}
        total_count = multiqc_collection.count_documents(query)
        cursor = multiqc_collection.find(query).skip(offset).limit(limit).sort("processed_at", -1)

        reports = []
        for doc in cursor:
            try:
                # Convert ObjectId to string for proper serialization
                if "_id" in doc:
                    doc["id"] = str(doc["_id"])
                reports.append(MultiQCReport(**doc))
            except Exception as doc_error:
                logger.warning(f"Failed to parse MultiQC report document: {doc_error}")
                continue

        logger.info(
            f"Found {len(reports)} MultiQC reports for data collection {data_collection_id}"
        )
        return reports, total_count

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve MultiQC reports: {str(e)}")


async def get_multiqc_report_by_id(report_id: str) -> MultiQCReport:
    """
    Get a specific MultiQC report by ID.

    Args:
        report_id: ID of the MultiQC report

    Returns:
        MultiQC report

    Raises:
        HTTPException: If report not found or database query fails
    """
    try:
        # Find the report by ID
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert ObjectId to string for proper serialization
        report_doc["id"] = str(report_doc["_id"])
        return MultiQCReport(**report_doc)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve MultiQC report: {str(e)}")


async def delete_multiqc_report_by_id(report_id: str, delete_s3_file: bool = False) -> dict:
    """
    Delete a MultiQC report and optionally its S3 file.

    Args:
        report_id: ID of the MultiQC report to delete
        delete_s3_file: Whether to also delete the associated S3 file

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If report not found or deletion fails
    """
    try:
        # Find the report first
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert and get the report object for potential S3 deletion
        report_doc["id"] = str(report_doc["_id"])
        report = MultiQCReport(**report_doc)

        # Delete S3 file if requested
        s3_file_deleted = False
        if delete_s3_file and report.s3_location:
            try:
                # Parse S3 location to get bucket and key
                # Format: s3://bucket/data_collection_id/timestamp_id/multiqc.parquet
                s3_path = report.s3_location.replace("s3://", "")
                bucket_name = settings.minio.bucket

                # Extract the prefix (everything after bucket name)
                if "/" in s3_path:
                    s3_key_prefix = s3_path.split("/", 1)[1]

                    # List all objects with this prefix and delete them
                    paginator = s3_client.get_paginator("list_objects_v2")
                    pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_key_prefix)

                    objects_to_delete = []
                    for page in pages:
                        if "Contents" in page:
                            for obj in page["Contents"]:
                                objects_to_delete.append({"Key": obj["Key"]})

                    if objects_to_delete:
                        # Delete in batches of 1000 (S3 limit)
                        batch_size = 1000
                        for i in range(0, len(objects_to_delete), batch_size):
                            batch = objects_to_delete[i : i + batch_size]
                            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": batch})

                        logger.info(
                            f"Deleted {len(objects_to_delete)} S3 objects from: {report.s3_location}"
                        )
                        s3_file_deleted = True
                    else:
                        logger.warning(f"No S3 objects found at: {report.s3_location}")
                        s3_file_deleted = False
                else:
                    logger.warning(f"Invalid S3 location format: {report.s3_location}")
                    s3_file_deleted = False

            except Exception as s3_error:
                logger.warning(f"Failed to delete S3 file: {s3_error}")
                s3_file_deleted = False

        # Delete the report from database
        result = multiqc_collection.delete_one({"_id": ObjectId(report_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        return {
            "deleted": True,
            "s3_file_deleted": s3_file_deleted,
            "message": f"MultiQC report {report_id} deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete MultiQC report: {str(e)}")


async def get_multiqc_report_metadata_by_id(report_id: str) -> dict:
    """
    Get the extracted metadata from a MultiQC report.

    Args:
        report_id: ID of the MultiQC report

    Returns:
        MultiQC metadata including samples, modules, and plots

    Raises:
        HTTPException: If report not found or query fails
    """
    try:
        # Find the report by ID
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert ObjectId to string for proper serialization
        report_doc["id"] = str(report_doc["_id"])
        report = MultiQCReport(**report_doc)
        return report.metadata.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve MultiQC metadata: {str(e)}"
        )


async def generate_multiqc_download_url(report_id: str, expiration_hours: int = 24) -> dict:
    """
    Generate a presigned URL to download the MultiQC parquet file from S3.

    Args:
        report_id: ID of the MultiQC report
        expiration_hours: How long the download URL should be valid (1-168 hours)

    Returns:
        Presigned download URL and metadata

    Raises:
        HTTPException: If report not found or URL generation fails
    """
    try:
        # Find the report by ID
        report_doc = multiqc_collection.find_one({"_id": ObjectId(report_id)})
        if not report_doc:
            raise HTTPException(status_code=404, detail="MultiQC report not found")

        # Convert ObjectId to string for proper serialization
        report_doc["id"] = str(report_doc["_id"])
        report = MultiQCReport(**report_doc)

        if not report.s3_location:
            raise HTTPException(status_code=400, detail="No S3 location available for this report")

        # TODO: Implement presigned URL generation when S3 utility functions are available
        # presigned_url = generate_presigned_url(
        #     report.s3_location,
        #     expiration_seconds=expiration_hours * 3600
        # )

        # For now, return the S3 location directly (in production, this would be a presigned URL)
        return {
            "download_url": report.s3_location,  # This should be a presigned URL in production
            "expires_in_hours": expiration_hours,
            "file_size_bytes": report.file_size_bytes,
            "s3_location": report.s3_location,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate download URL: {str(e)}")
