from bson import ObjectId
from fastapi import APIRouter, HTTPException

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.projects import Project
from depictio.models.models.users import User

# Define the router
projects_endpoint_router = APIRouter()


# Core functions
def _async_get_all_projects(current_user: User, projects_collection) -> list[Project]:
    """Core function to get all projects for a user."""
    current_user_id = ObjectId(current_user.id)

    query = {
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }

    if current_user.is_admin:
        query = {}

    projects = list(projects_collection.find(query))
    if projects:
        projects = [Project.from_mongo(project) for project in projects]
        return projects
    else:
        return []


def _async_get_project_from_id(
    project_id: PyObjectId, current_user: User, projects_collection
) -> dict:
    """Core function to get a project by ID."""
    current_user_id = ObjectId(current_user.id)
    query = {
        "_id": ObjectId(project_id),
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }

    if current_user.is_admin:
        query = {"_id": ObjectId(project_id)}

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = convert_objectid_to_str(project)
    return project


def _async_get_project_from_name(
    project_name: str, current_user: User, projects_collection
) -> dict:
    """Core function to get a project by name."""
    # Find projects where current_user is either an owner or a viewer
    query = {
        "name": project_name,
        "$or": [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},  # This makes projects with "*" publicly accessible
        ],
    }

    if current_user.is_admin:
        query = {"name": project_name}

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = convert_objectid_to_str(Project.from_mongo(project).model_dump())
    return project


# @validate_call(validate_return=True)
async def _helper_create_project_beanie(project: Project, original_ids: dict | None = None) -> dict:
    """Helper function to create a project in the database.

    Args:
        project (ProjectBeanie): Project object containing project information
        original_ids (dict | None): Original IDs from YAML to preserve static IDs
            Format: {
                "project": str,
                "workflows": {
                    wf_idx: {"id": str, "data_collections": {dc_idx: str}}
                }
            }

    Raises:
        HTTPException: If the project already exists in the database

    Returns:
        dict: Project creation result with project details
    """

    # Check if the project already exists
    existing_project = projects_collection.find_one({"name": project.name})
    logger.debug(f"Existing project: {existing_project}")
    if existing_project:
        raise HTTPException(
            status_code=400,
            detail=f"Project with name '{project.name}' already exists.",
        )

    # Use project.mongo() to ensure all nested 'id' fields are converted to '_id'
    logger.debug(f"Project before conversion: {project}")
    mongo_project = project.mongo()
    logger.debug(f"Mongo project: {mongo_project}")

    # CRITICAL: Restore static IDs from YAML in the MongoDB document dict
    # This ensures IDs are preserved across multiple K8s instances sharing the same S3 bucket
    if original_ids:
        from bson import ObjectId

        # Restore project ID if provided
        if original_ids.get("project"):
            original_project_id = original_ids["project"]
            current_project_id = str(mongo_project.get("_id", ""))
            if current_project_id != original_project_id:
                logger.warning(
                    f"Restoring project ID in mongo_project dict: {current_project_id} -> {original_project_id}"
                )
                mongo_project["_id"] = ObjectId(original_project_id)
            else:
                logger.debug(f"Project ID already correct: {original_project_id}")

        # Restore workflow and data collection IDs
        if "workflows" in original_ids and "workflows" in mongo_project:
            for wf_idx, wf_ids in original_ids["workflows"].items():
                if wf_idx < len(mongo_project["workflows"]):
                    workflow = mongo_project["workflows"][wf_idx]

                    # Restore workflow ID
                    if wf_ids.get("id"):
                        original_wf_id = wf_ids["id"]
                        current_wf_id = str(workflow.get("_id", ""))
                        if current_wf_id != original_wf_id:
                            logger.warning(
                                f"Restoring workflow[{wf_idx}] ID in mongo_project dict: {current_wf_id} -> {original_wf_id}"
                            )
                            workflow["_id"] = ObjectId(original_wf_id)
                        else:
                            logger.debug(f"Workflow[{wf_idx}] ID already correct: {original_wf_id}")

                    # Restore data collection IDs
                    if "data_collections" in wf_ids and "data_collections" in workflow:
                        for dc_idx, dc_id in wf_ids["data_collections"].items():
                            if dc_idx < len(workflow["data_collections"]):
                                dc = workflow["data_collections"][dc_idx]
                                current_dc_id = str(dc.get("_id", ""))
                                if current_dc_id != dc_id:
                                    logger.warning(
                                        f"Restoring data_collection[{wf_idx},{dc_idx}] ID in mongo_project dict: {current_dc_id} -> {dc_id}"
                                    )
                                    dc["_id"] = ObjectId(dc_id)
                                else:
                                    logger.debug(
                                        f"DataCollection[{wf_idx},{dc_idx}] ID already correct: {dc_id}"
                                    )

        logger.info(
            "Static IDs successfully restored in mongo_project dict before database insertion"
        )

    # Save the project to the database using PyMongo's insert_one
    result = projects_collection.insert_one(mongo_project)

    # Only update the project's id if it wasn't already set (preserve static IDs from YAML)
    if project.id is None:
        project.id = result.inserted_id

    return {
        "project": project,
        "message": "Project created successfully.",
        "success": True,
    }


def validate_workflow_uniqueness_in_project(project: Project) -> None:
    """Validate that workflow_tag is unique within the project's workflows.

    Args:
        project (Project): Project object containing workflows to validate

    Raises:
        HTTPException: If duplicate workflow_tag is found within the project
    """
    workflow_tags = []
    duplicates = []

    for workflow in project.workflows:
        if workflow.workflow_tag in workflow_tags:
            duplicates.append(workflow.workflow_tag)
        else:
            workflow_tags.append(workflow.workflow_tag)

    if duplicates:
        duplicate_tags = ", ".join(set(duplicates))
        raise HTTPException(
            status_code=400,
            detail=f"Duplicate workflow_tag(s) found within project '{project.name}': {duplicate_tags}. "
            f"Each workflow_tag must be unique within a project.",
        )


async def get_project_with_delta_locations(project_id: PyObjectId, current_user: User) -> dict:
    """
    Fetch project with delta_location joined for all data collections.

    Uses MongoDB aggregation to JOIN Project → Workflow → DataCollection
    with DeltaTableAggregated collection at query time. This eliminates
    the need for caching delta_location in dashboard metadata.

    Benefits:
    - Always returns fresh delta_location data
    - Single optimized query vs N separate API calls
    - No stale cache issues when DCs are re-processed

    Args:
        project_id: Project ObjectId
        current_user: Current authenticated user (for permission check)

    Returns:
        dict: Project document with delta_location and last_aggregation
              added to each DataCollection

    Raises:
        HTTPException: If project not found or access denied
    """
    current_user_id = ObjectId(current_user.id)

    # Permission check query
    permission_query = {
        "_id": ObjectId(project_id),
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }

    if current_user.is_admin:
        permission_query = {"_id": ObjectId(project_id)}

    # MongoDB aggregation pipeline to join with DeltaTableAggregated
    pipeline = [
        # 1. Match the project (with permission check)
        {"$match": permission_query},
        # 2. Unwind workflows array (preserve empty arrays)
        {"$unwind": {"path": "$workflows", "preserveNullAndEmptyArrays": True}},
        # 3. Unwind data_collections array (preserve empty arrays)
        {
            "$unwind": {
                "path": "$workflows.data_collections",
                "preserveNullAndEmptyArrays": True,
            }
        },
        # 4. Lookup DeltaTableAggregated for each DC
        {
            "$lookup": {
                "from": "deltatables",
                "let": {"dc_id": "$workflows.data_collections._id"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$data_collection_id", "$$dc_id"]}}},
                    # Sort by aggregation time descending to get latest version
                    {"$sort": {"_id": -1}},  # Latest insert is latest version
                    {"$limit": 1},
                    {
                        "$project": {
                            "delta_table_location": 1,
                            # Get last aggregation (latest version)
                            "last_aggregation": {"$arrayElemAt": ["$aggregation", -1]},
                        }
                    },
                ],
                "as": "delta_info",
            }
        },
        # 5. Add delta info to DC object
        {
            "$addFields": {
                "workflows.data_collections.delta_location": {
                    "$arrayElemAt": ["$delta_info.delta_table_location", 0]
                },
                "workflows.data_collections.last_aggregation": {
                    "$arrayElemAt": ["$delta_info.last_aggregation", 0]
                },
            }
        },
        # 6. Remove temporary delta_info field
        {"$project": {"delta_info": 0}},
        # 7. Group back to reconstruct data_collections array per workflow
        {
            "$group": {
                "_id": {
                    "project_id": "$_id",
                    "project_name": "$name",
                    "workflow_id": "$workflows._id",
                },
                "project_doc": {"$first": "$$ROOT"},
                "data_collections": {"$push": "$workflows.data_collections"},
            }
        },
        # 8. Group back to reconstruct workflows array per project
        {
            "$group": {
                "_id": "$_id.project_id",
                "project_doc": {"$first": "$project_doc"},
                "workflows": {
                    "$push": {
                        "_id": "$_id.workflow_id",
                        "workflow_tag": "$project_doc.workflows.workflow_tag",
                        "data_collections": "$data_collections",
                    }
                },
            }
        },
        # 9. Final projection - merge workflows back into project document
        {
            "$replaceRoot": {
                "newRoot": {
                    "$mergeObjects": [
                        "$project_doc",
                        {"workflows": "$workflows"},
                    ]
                }
            }
        },
        # 10. Remove the redundant workflows field from nested structure
        {"$project": {"project_doc": 0}},
    ]

    logger.info(f"📡 Fetching project {project_id} with delta_locations (optimized query)")

    try:
        result = list(projects_collection.aggregate(pipeline))
    except Exception as e:
        logger.error(f"Aggregation pipeline error: {e}")
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Project not found or access denied.",
        )

    project = result[0]
    project = convert_objectid_to_str(project)

    logger.info(
        f"✅ Project {project_id} fetched with delta_locations for "
        f"{len(project.get('workflows', []))} workflows"
    )

    return project
