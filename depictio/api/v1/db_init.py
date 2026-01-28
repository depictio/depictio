import json
import os
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import format_pydantic, logger
from depictio.api.v1.endpoints.dashboards_endpoints.routes import save_dashboard
from depictio.api.v1.endpoints.projects_endpoints.utils import _helper_create_project_beanie
from depictio.api.v1.endpoints.user_endpoints.core_functions import _create_user_in_db
from depictio.api.v1.endpoints.user_endpoints.token_utils import create_default_token
from depictio.api.v1.endpoints.user_endpoints.utils import (
    _ensure_mongodb_connection,
    create_group_helper_beanie,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import GroupBeanie, Permission, TokenBeanie, UserBase, UserBeanie
from depictio.models.utils import get_config


async def create_initial_project_legacy(
    admin_user: UserBeanie, token_payload: dict | None
) -> dict | None:
    """Create initial demo project with static IDs for K8s consistency."""
    project_yaml_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "projects", "init", "iris", "project.yaml"
    )
    project_config = get_config(project_yaml_path)
    project_config["yaml_config_path"] = project_yaml_path

    # CRITICAL: Force static IDs to ensure consistency across K8s instances
    # The YAML may be modified by init containers, so we hardcode the expected IDs
    STATIC_PROJECT_ID = "646b0f3c1e4a2d7f8e5b8c9a"
    STATIC_WORKFLOW_ID = "646b0f3c1e4a2d7f8e5b8c9b"
    STATIC_DC_ID = "646b0f3c1e4a2d7f8e5b8c9c"

    logger.info(
        f"Forcing static IDs for iris demo project: Project={STATIC_PROJECT_ID}, "
        f"Workflow={STATIC_WORKFLOW_ID}, DataCollection={STATIC_DC_ID}"
    )

    project_config["id"] = STATIC_PROJECT_ID
    if project_config.get("workflows") and len(project_config["workflows"]) > 0:
        project_config["workflows"][0]["id"] = STATIC_WORKFLOW_ID
        if (
            project_config["workflows"][0].get("data_collections")
            and len(project_config["workflows"][0]["data_collections"]) > 0
        ):
            project_config["workflows"][0]["data_collections"][0]["id"] = STATIC_DC_ID

    project_config["permissions"] = {
        "owners": [
            UserBase(
                id=admin_user.id,  # type: ignore[invalid-argument-type]
                email=admin_user.email,
                is_admin=True,
            )
        ],
        "editors": [],
        "viewers": [],
    }

    # IMPORTANT: Save the original IDs from YAML before Pydantic processing
    # This ensures static IDs are preserved across multiple K8s instances
    original_project_id = project_config.get("id")
    original_workflow_ids = {}
    original_dc_ids = {}

    for wf_idx, workflow in enumerate(project_config.get("workflows", [])):
        wf_id = workflow.get("id")
        if wf_id:
            original_workflow_ids[wf_idx] = wf_id

        for dc_idx, dc in enumerate(workflow.get("data_collections", [])):
            dc_id = dc.get("id")
            if dc_id:
                original_dc_ids[(wf_idx, dc_idx)] = dc_id

    logger.debug(
        f"Original IDs from YAML - Project: {original_project_id}, "
        f"Workflows: {original_workflow_ids}, DataCollections: {original_dc_ids}"
    )

    # Package original IDs in a structured format for passing to helper function
    workflows_dict: dict[int, dict[str, Any]] = {}
    for wf_idx, wf_id in original_workflow_ids.items():
        workflows_dict[wf_idx] = {
            "id": wf_id,
            "data_collections": {},
        }
    for (wf_idx, dc_idx), dc_id in original_dc_ids.items():
        if wf_idx not in workflows_dict:
            workflows_dict[wf_idx] = {"id": None, "data_collections": {}}
        workflows_dict[wf_idx]["data_collections"][dc_idx] = dc_id
    original_ids: dict[str, Any] = {
        "project": original_project_id,
        "workflows": workflows_dict,
    }
    logger.debug(f"Project config: {project_config}")
    project = ProjectBeanie(**project_config)  # type: ignore[missing-argument]

    # DEFENSIVE: Restore original IDs if they were lost during Pydantic instantiation
    if original_project_id and str(project.id) != original_project_id:
        logger.warning(
            f"Project ID changed from {original_project_id} to {project.id}, restoring original"
        )
        project.id = PyObjectId(original_project_id)

    for wf_idx, workflow in enumerate(project.workflows):
        if wf_idx in original_workflow_ids:
            original_wf_id = original_workflow_ids[wf_idx]
            if str(workflow.id) != original_wf_id:
                logger.warning(
                    f"Workflow[{wf_idx}] ID changed from {original_wf_id} to {workflow.id}, "
                    f"restoring original"
                )
                workflow.id = PyObjectId(original_wf_id)

        for dc_idx, dc in enumerate(workflow.data_collections):
            key = (wf_idx, dc_idx)
            if key in original_dc_ids:
                original_dc_id = original_dc_ids[key]
                if str(dc.id) != original_dc_id:
                    logger.warning(
                        f"DataCollection[{wf_idx},{dc_idx}] ID changed from {original_dc_id} "
                        f"to {dc.id}, restoring original"
                    )
                    dc.id = PyObjectId(original_dc_id)

    logger.debug(f"Project object after ID restoration: {format_pydantic(project)}")
    token = TokenBeanie(**token_payload["token"])  # type: ignore[missing-argument]
    logger.debug(f"Token: {format_pydantic(token)}")

    try:
        payload = await _helper_create_project_beanie(project, original_ids=original_ids)

        logger.debug(f"Project creation payload: {payload}")
        if payload["success"]:
            project_name = (
                payload["project"].name if hasattr(payload["project"], "name") else "unknown"
            )
            logger.info(f"Project created successfully: {project_name}")
            return {
                "success": True,
                "project": payload["project"],
                "message": "Project created successfully",
            }
    except HTTPException as e:
        logger.error(f"Error creating project: {e}")
        return {
            "success": False,
            "message": f"Error creating project: {e}",
        }


async def create_initial_dashboards(admin_user: UserBeanie) -> list[dict | None]:
    """Create all initial demo dashboards for reference datasets.

    Args:
        admin_user: Admin user to set as dashboard owner

    Returns:
        List of dashboard creation responses
    """
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    dashboards_config = [
        {
            "name": "iris",
            "json_path": os.path.join(
                os.path.dirname(__file__), "..", "..", "projects", "init", "iris", "dashboard.json"
            ),
            "static_dc_id": STATIC_IDS["iris"]["data_collections"]["iris_table"],
        },
        {
            "name": "penguins",
            "json_path": os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "projects",
                "reference",
                "penguins",
                "dashboard.json",
            ),
            "static_dc_id": STATIC_IDS["penguins"]["data_collections"]["penguins_complete"],
        },
        {
            "name": "ampliseq_multiqc",
            "json_path": os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "projects",
                "reference",
                "ampliseq",
                "dashboard_multiqc.json",
            ),
            # Use None for multi-DC dashboards to preserve DC IDs from JSON file
            "static_dc_id": None,
        },
        {
            "name": "ampliseq_analysis",
            "json_path": os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "projects",
                "reference",
                "ampliseq",
                "dashboard_analysis.json",
            ),
            # Child tab dashboard - preserve DC IDs from JSON file
            "static_dc_id": None,
        },
    ]

    results = []
    for dashboard_config in dashboards_config:
        logger.info(f"Creating dashboard: {dashboard_config['name']}")
        result = await create_dashboard_from_json(
            admin_user=admin_user,
            dashboard_json_path=dashboard_config["json_path"],
            static_dc_id=dashboard_config["static_dc_id"],
        )
        results.append(result)

    return results


async def create_dashboard_from_json(
    admin_user: UserBeanie,
    dashboard_json_path: str,
    static_dc_id: str,
) -> dict | None:
    """Create dashboard from JSON file with static dc_ids for K8s consistency.

    Args:
        admin_user: Admin user to set as dashboard owner
        dashboard_json_path: Path to dashboard JSON file
        static_dc_id: Static data collection ID to use for all components

    Returns:
        Dashboard creation response or None
    """
    # Load the dashboard configuration from the JSON file
    from bson import json_util

    from depictio.api.v1.db import dashboards_collection

    if not os.path.exists(dashboard_json_path):
        logger.warning(f"Dashboard JSON not found: {dashboard_json_path}")
        return None

    dashboard_data = json.load(open(dashboard_json_path, "r"), object_hook=json_util.object_hook)
    logger.debug(f"Dashboard data: {dashboard_data}")
    _check = dashboards_collection.find_one({"_id": ObjectId(dashboard_data["_id"])})

    if static_dc_id:
        logger.info(f"Forcing static data collection ID in dashboard: {static_dc_id}")
    else:
        logger.info("Multi-DC dashboard: preserving DC IDs from JSON file")

    # If dashboard already exists, verify and fix dc_ids in existing dashboard
    if _check:
        logger.info("Dashboard already exists, verifying/fixing dc_ids...")

        needs_update = False
        update_fields: dict = {}

        # Ensure dashboard is public for reference dashboards
        if not _check.get("is_public", False):
            logger.info("Setting existing dashboard to public")
            update_fields["is_public"] = True
            needs_update = True

        # Only force static DC ID if specified (for single-DC dashboards like Iris)
        if static_dc_id:
            if "stored_metadata" in _check:
                for component in _check["stored_metadata"]:
                    # Check and fix top-level dc_id
                    if "dc_id" in component:
                        current_dc_id = str(component["dc_id"])
                        if current_dc_id != static_dc_id:
                            logger.warning(
                                f"Component {component.get('index', 'unknown')} has wrong dc_id: "
                                f"{current_dc_id}, fixing to {static_dc_id}"
                            )
                            component["dc_id"] = ObjectId(static_dc_id)
                            update_fields["stored_metadata"] = _check["stored_metadata"]
                            needs_update = True

                    # Check and fix nested dc_config._id
                    if "dc_config" in component and isinstance(component["dc_config"], dict):
                        if "_id" in component["dc_config"]:
                            current_config_id = str(component["dc_config"]["_id"])
                            if current_config_id != static_dc_id:
                                logger.warning(
                                    f"Component {component.get('index', 'unknown')} has wrong dc_config._id: "
                                    f"{current_config_id}, fixing to {static_dc_id}"
                                )
                                component["dc_config"]["_id"] = ObjectId(static_dc_id)
                                update_fields["stored_metadata"] = _check["stored_metadata"]
                                needs_update = True
        else:
            logger.info("Multi-DC dashboard: using DC IDs from JSON file")

        if needs_update:
            # Update dashboard in database
            result = dashboards_collection.update_one(
                {"_id": ObjectId(dashboard_data["_id"])},
                {"$set": update_fields},
            )
            logger.info(
                f"Updated existing dashboard "
                f"(matched: {result.matched_count}, modified: {result.modified_count})"
            )
        else:
            logger.info("Dashboard is already correct")

        return {
            "success": True,
            "message": "Dashboard verified/updated",
        }

    # Only force static DC ID if specified (for single-DC dashboards like Iris)
    if static_dc_id and "stored_metadata" in dashboard_data:
        for component in dashboard_data["stored_metadata"]:
            # Force top-level dc_id
            # Note: json_util.object_hook converts {"$oid": "..."} to ObjectId objects
            if "dc_id" in component:
                current_dc_id = str(component.get("dc_id", ""))
                if current_dc_id != static_dc_id:
                    logger.debug(
                        f"Updating component {component.get('index', 'unknown')} dc_id "
                        f"from {current_dc_id} to {static_dc_id}"
                    )
                    component["dc_id"] = ObjectId(static_dc_id)

            # Force nested dc_config._id
            if "dc_config" in component and isinstance(component["dc_config"], dict):
                if "_id" in component["dc_config"]:
                    current_config_id = str(component["dc_config"].get("_id", ""))
                    if current_config_id != static_dc_id:
                        logger.debug(
                            f"Updating component {component.get('index', 'unknown')} dc_config._id "
                            f"from {current_config_id} to {static_dc_id}"
                        )
                        component["dc_config"]["_id"] = ObjectId(static_dc_id)

        logger.info(
            f"Updated {len(dashboard_data.get('stored_metadata', []))} dashboard components with static dc_id"
        )
    elif not static_dc_id:
        logger.info(
            f"Multi-DC dashboard: preserving {len(dashboard_data.get('stored_metadata', []))} "
            f"component DC IDs from JSON file"
        )

    # Convert dashboard data to the correct format
    dashboard_data = DashboardData.from_mongo(dashboard_data)
    dashboard_data.permissions = Permission(
        owners=[
            UserBase(
                id=admin_user.id,  # type: ignore[invalid-argument-type]
                email=admin_user.email,
                is_admin=True,
            )
        ],
        editors=[],
        viewers=[],
    )

    # Set reference dashboards as public by default for K8s demo environments
    dashboard_data.is_public = True

    # Create the dashboard object into the database
    response = await save_dashboard(
        dashboard_id=dashboard_data.id,
        data=dashboard_data,
        current_user=admin_user,
    )
    logger.debug(f"Dashboard response: {response}")
    return response


async def create_initial_dashboard(admin_user: UserBeanie) -> dict | None:
    """Legacy wrapper for backward compatibility - creates only Iris dashboard.

    For creating multiple dashboards, use create_initial_dashboards() instead.
    """
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    dashboard_json_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "projects", "init", "iris", "dashboard.json"
    )
    static_dc_id = STATIC_IDS["iris"]["data_collections"]["iris_table"]

    return await create_dashboard_from_json(
        admin_user=admin_user,
        dashboard_json_path=dashboard_json_path,
        static_dc_id=static_dc_id,
    )


async def initialize_db(wipe: bool = False) -> UserBeanie | None:
    """Initialize the database with default users and groups."""

    _ensure_mongodb_connection()

    if wipe:
        logger.info("Wipe is enabled. Deleting the database...")
        from depictio.api.v1.db import client, initialization_collection

        # Preserve the init_lock before wiping to prevent other workers from acquiring lock
        init_lock = initialization_collection.find_one({"_id": "init_lock"})

        client.drop_database(settings.mongodb.db_name)
        logger.info("Database deleted successfully.")

        # Restore the init_lock to prevent race conditions with other workers
        if init_lock:
            initialization_collection.insert_one(init_lock)
            logger.info("Restored initialization lock after database wipe")

    # Load and validate configuration for initial users and groups
    config_path = os.path.join(os.path.dirname(__file__), "configs", "initial_users.yaml")
    initial_config = get_config(config_path)

    logger.info("Running initial database setup...")

    # Create groups
    for group_config in initial_config.get("groups", []):
        group = GroupBeanie(**group_config)  # type: ignore[missing-argument]
        payload = await create_group_helper_beanie(group)
        logger.debug(f"Created group: {format_pydantic(payload['group'])}")

    admin_user = None
    token_payload = None

    # Create users
    for user_config in initial_config.get("users", []):
        # Validate user config
        logger.debug(user_config)

        user_payload = await _create_user_in_db(
            id=user_config["id"],
            email=user_config["email"],
            password=user_config["password"],
            is_admin=user_config.get("is_admin", False),
        )
        logger.debug(f"User payload: {user_payload}")

        # # Create default token if user was just created
        if user_payload["success"]:
            token_payload = await create_default_token(user_payload["user"])
            if token_payload:
                logger.info("Created default token")

            if user_payload["user"].is_admin:
                admin_user = user_payload["user"]
                logger.info(f"Admin user created: {admin_user.email}")
                logger.debug(f"Admin token created: {token_payload}")
        else:
            token_beanie = await TokenBeanie.find_one(
                {"user_id": user_payload["user"].id, "name": "default_token"}
            )
            logger.debug(f"Token beanie: {format_pydantic(token_beanie)}")
            if token_beanie:
                token_payload = {
                    "token": token_beanie.model_dump(),
                    "config_path": None,
                    "new_token_created": False,
                }
                logger.debug(f"Token payload: {format_pydantic(token_payload)}")  # type: ignore[invalid-argument-type]
                logger.info(f"Default token already exists for {user_payload['user'].email}")
            else:
                logger.warning(f"Failed to create default token for {user_payload['user'].email}")

    # If no admin user was created through the loop, try to find one
    if admin_user is None:
        logger.debug("No admin user created during initialization, checking if one exists...")
        admin_user = await UserBeanie.find_one({"is_admin": True})
        if admin_user:
            logger.info(f"Found existing admin user: {admin_user.email}")
            token_beanie = await TokenBeanie.find_one(
                {"user_id": admin_user.id, "name": "default_token"}
            )

            logger.debug(f"Token payload: {format_pydantic(token_beanie)}")

            token_payload = {
                "token": token_beanie.model_dump(),
                "config_path": None,
                "new_token_created": False,
            }
        else:
            logger.warning("No admin user found in the database")

    if admin_user is None or token_payload is None:
        logger.error("Cannot proceed with project creation: admin_user or token_payload is None")
        raise RuntimeError("Admin user and token are required for initialization")

    # Create all reference datasets (replaces hardcoded iris logic)
    from depictio.api.v1.db_init_reference_datasets import create_reference_datasets

    created_projects = await create_reference_datasets(
        admin_user=admin_user, token_payload=token_payload
    )

    # Store metadata for background processing (use replace_one for idempotency)
    from depictio.api.v1.db import initialization_collection

    initialization_collection.replace_one(
        {"_id": "reference_datasets_metadata"},
        {
            "_id": "reference_datasets_metadata",
            "projects": created_projects,
            "created_at": datetime.now(timezone.utc),
        },
        upsert=True,
    )

    logger.info(f"Created {len(created_projects)} reference datasets")

    # Create dashboards for all reference datasets
    dashboard_payloads = await create_initial_dashboards(admin_user=admin_user)
    logger.info(f"Created {len([p for p in dashboard_payloads if p])} dashboards")

    logger.info("Database initialization completed successfully.")

    return admin_user
