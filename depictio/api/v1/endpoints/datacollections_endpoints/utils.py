from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection
from depictio.models.models.base import PyObjectId, convert_objectid_to_str


def symmetrize_join_details(join_details_map: dict[str, list[dict]]):
    """Ensure symmetric join details across all related data collections."""
    # Create a list of items to iterate over, so the original dict can be modified
    items = list(join_details_map.items())
    for dc_id, joins in items:
        for join in joins:
            for related_dc_id in join["with_dc"]:
                # Initialize related_dc_join list if not already present
                if related_dc_id not in join_details_map:
                    join_details_map[related_dc_id] = []

                # Check if related data collection already has symmetric join details with the current one
                related_joins = join_details_map[related_dc_id]
                symmetric_join_exists = any(
                    dc_id in join_detail["with_dc"] for join_detail in related_joins
                )

                if not symmetric_join_exists:
                    # Create symmetric join detail for related data collection
                    symmetric_join = {
                        "on_columns": join["on_columns"],
                        "how": join["how"],
                        "with_dc": [dc_id],  # Link back to the current data collection
                    }
                    join_details_map[related_dc_id].append(symmetric_join)


def generate_join_dict(workflow: dict, project: dict | None = None) -> dict[str, dict[str, dict]]:
    """
    Generate join dictionary from project-level joins (new approach).

    Args:
        workflow: Workflow dict with data_collections
        project: Project dict with joins[] array (optional for backward compatibility)

    Returns:
        {
            "workflow_id": {
                "result_dc_id": {
                    "how": "inner",
                    "on_columns": ["col1", "col2"],
                    "dc_tags": ["left_dc_tag", "right_dc_tag"],
                    "join_name": "penguins_complete",
                    "description": "Complete penguin dataset"
                }
            }
        }
    """
    workflow_id = str(workflow.get("_id", workflow.get("id", "")))
    join_details_map: dict[str, dict[str, dict]] = {workflow_id: {}}

    # If no project provided or no joins defined, return empty
    if not project or "joins" not in project:
        logger.debug(f"No project or joins found for workflow {workflow_id}")
        return join_details_map

    # Build DC tag to ID lookup for this workflow
    dc_tag_to_id: dict[str, str] = {}
    dc_id_to_tag: dict[str, str] = {}
    for dc in workflow.get("data_collections", []):
        dc_id = str(dc.get("_id", dc.get("id", "")))
        dc_tag = dc.get("data_collection_tag", "")
        if dc_tag:
            dc_tag_to_id[dc_tag] = dc_id
            dc_id_to_tag[dc_id] = dc_tag

    # Process project-level joins
    workflow_name = workflow.get("name", "")
    logger.info(
        f"Processing {len(project.get('joins', []))} joins from project for workflow '{workflow_name}'"
    )

    for join_def in project.get("joins", []):
        join_name = join_def.get("name", "unnamed")
        logger.debug(f"Checking join: {join_name}")
        logger.debug(f"  - result_dc_id: {join_def.get('result_dc_id')}")
        logger.debug(
            f"  - workflow_name: {join_def.get('workflow_name')} (current: {workflow_name})"
        )
        logger.debug(
            f"  - left_dc: {join_def.get('left_dc')}, right_dc: {join_def.get('right_dc')}"
        )

        # Skip if join is for a different workflow
        join_workflow_name = join_def.get("workflow_name", "")
        if join_workflow_name and join_workflow_name != workflow_name:
            logger.debug("  → Skipped: workflow mismatch")
            continue

        # Skip if join hasn't been executed yet (no result_dc_id)
        if not join_def.get("result_dc_id"):
            logger.warning("  → Skipped: no result_dc_id (join not executed)")
            continue

        logger.info(f"  → Added join '{join_name}' to result dict")

        # Get join metadata
        result_dc_id = str(join_def["result_dc_id"])
        left_dc_tag = join_def.get("left_dc", "")
        right_dc_tag = join_def.get("right_dc", "")

        # Create join entry with result_dc_id as the key
        # This allows dashboard to reference the joined table directly
        join_details_map[workflow_id][result_dc_id] = {
            "how": join_def.get("how", "inner"),
            "on_columns": join_def.get("on_columns", []),
            "dc_tags": [left_dc_tag, right_dc_tag],
            "join_name": join_def.get("name", ""),
            "description": join_def.get("description", ""),
        }
        logger.debug(
            f"Added join {join_def.get('name')} with result_dc_id {result_dc_id} for workflow {workflow_name}"
        )

    logger.info(
        f"Generated join dict with {len(join_details_map[workflow_id])} joins for workflow {workflow_id}"
    )
    return join_details_map


def normalize_join_details(join_details):
    normalized_details = {}

    # Initialize entries for all DCs
    for dc_id, joins in join_details.items():
        for join in joins:
            if dc_id not in normalized_details:
                normalized_details[dc_id] = {
                    "on_columns": join["on_columns"],
                    "how": join["how"],
                    "with_dc": set(join.get("with_dc", [])),  # Use set for unique elements
                    "with_dc_id": set(join.get("with_dc_id", [])),  # Use set for unique elements
                }

    # Update relationships
    for dc_id, joins in join_details.items():
        for join in joins:
            # Update related by ID
            for related_dc_id in join.get("with_dc_id", []):
                # Ensure reciprocal relationship exists
                normalized_details[dc_id]["with_dc_id"].add(related_dc_id)
                if related_dc_id not in normalized_details:
                    normalized_details[related_dc_id] = {
                        "on_columns": join["on_columns"],
                        "how": join["how"],
                        "with_dc": set(),
                        "with_dc_id": set(),
                    }
                normalized_details[related_dc_id]["with_dc_id"].add(dc_id)

            # Update related by Tag
            for related_dc_tag in join.get("with_dc", []):
                normalized_details[dc_id]["with_dc"].add(related_dc_tag)
                # This assumes tags to IDs resolution happens elsewhere or they're handled as equivalent identifiers
                # If 'related_dc_tag' could also appear in 'normalized_details', consider adding reciprocal logic here

    # Convert sets back to lists for the final output
    for dc_id in normalized_details:
        normalized_details[dc_id]["with_dc"] = list(normalized_details[dc_id]["with_dc"])
        normalized_details[dc_id]["with_dc_id"] = list(normalized_details[dc_id]["with_dc_id"])

    return normalized_details


async def _get_data_collection_specs(data_collection_id: PyObjectId, current_user) -> dict:
    """Core function to retrieve data collection specifications.

    Args:
        data_collection_id: ObjectId of the data collection
        current_user: User object with permissions

    Returns:
        dict: Data collection specifications

    Raises:
        HTTPException: If data collection not found or access denied
    """
    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use MongoDB aggregation to directly retrieve the specific data collection
    pipeline = [
        # Match projects containing this collection and with appropriate permissions
        {
            "$match": {
                "workflows.data_collections._id": data_collection_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},
                    {"permissions.viewers._id": current_user.id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Unwind the data_collections array
        {"$unwind": "$workflows.data_collections"},
        # Match the specific data collection ID
        {"$match": {"workflows.data_collections._id": data_collection_oid}},
        # Return only the data collection
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    return convert_objectid_to_str(result[0])


async def _delete_data_collection_by_id(data_collection_id: str, current_user) -> dict:
    """Core function to delete a data collection by its ID.

    Args:
        data_collection_id: String ID of the data collection
        current_user: User object with permissions

    Returns:
        dict: Success message

    Raises:
        HTTPException: If data collection not found or access denied
    """
    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find the project containing this data collection
    project = projects_collection.find_one(
        {
            "workflows.data_collections._id": data_collection_oid,
            "$or": [
                {"permissions.owners._id": current_user.id},
                {"permissions.viewers._id": current_user.id},
            ],
        }
    )

    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied")

    # Remove the data collection from the project
    result = projects_collection.update_one(
        {"_id": project["_id"]},
        {"$pull": {"workflows.$[].data_collections": {"_id": data_collection_oid}}},
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Data collection not found")

    # Cleanup associated S3 data and Delta tables
    await _cleanup_s3_delta_table(data_collection_id)

    return {"message": "Data collection deleted successfully"}


async def _update_data_collection_name(
    data_collection_id: str, new_name: str, current_user
) -> dict:
    """Core function to update data collection name.

    Args:
        data_collection_id: String ID of the data collection
        new_name: New name for the data collection
        current_user: User object with permissions

    Returns:
        dict: Success message

    Raises:
        HTTPException: If data collection not found or access denied
    """
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")

    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find the project containing this data collection
    project = projects_collection.find_one(
        {
            "workflows.data_collections._id": data_collection_oid,
            "$or": [
                {"permissions.owners._id": current_user.id},
                {"permissions.viewers._id": current_user.id},
            ],
        }
    )

    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied")

    # Update the data collection name in the project
    result = projects_collection.update_one(
        {"_id": project["_id"], "workflows.data_collections._id": data_collection_oid},
        {"$set": {"workflows.$[].data_collections.$[dc].data_collection_tag": new_name}},
        array_filters=[{"dc._id": data_collection_oid}],
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Data collection not found")

    return {"message": f"Data collection name updated to '{new_name}' successfully"}


async def _cleanup_s3_delta_table(data_collection_id: str) -> None:
    """Core function to cleanup S3 Delta table objects.

    Args:
        data_collection_id: String ID of the data collection
    """
    try:
        import boto3
        from botocore.exceptions import ClientError

        # Initialize S3 client for MinIO
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.minio.endpoint_url,
            aws_access_key_id=settings.minio.aws_access_key_id,
            aws_secret_access_key=settings.minio.aws_secret_access_key,
            region_name="us-east-1",
        )

        # Delta table is stored with data_collection_id as the key
        delta_table_prefix = data_collection_id
        bucket_name = settings.minio.bucket

        # Delete all objects in the Delta table directory
        logger.info(f"Deleting Delta table for data collection: {data_collection_id}")
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=delta_table_prefix)

        if "Contents" in response:
            objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
            if objects_to_delete:
                s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})
                logger.info(
                    f"Deleted {len(objects_to_delete)} Delta table objects for data collection {data_collection_id}"
                )
            else:
                logger.info(
                    f"No Delta table objects found for data collection {data_collection_id}"
                )
        else:
            logger.info(f"No Delta table found for data collection {data_collection_id}")

    except ClientError as e:
        logger.error(
            f"Failed to delete S3 Delta table objects for data collection {data_collection_id}: {e}"
        )
        # Don't fail the entire operation if S3 cleanup fails, just log the error
    except Exception as e:
        logger.error(
            f"Unexpected error during S3 cleanup for data collection {data_collection_id}: {e}"
        )
        # Don't fail the entire operation if S3 cleanup fails, just log the error
