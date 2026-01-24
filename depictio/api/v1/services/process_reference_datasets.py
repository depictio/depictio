"""Background processing for reference datasets with join execution."""

import asyncio
import threading
import time
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging import logger
from depictio.api.v1.configs.config import settings


class ReferenceDatasetProcessor:
    """Orchestrates processing of reference datasets including joins."""

    def __init__(self, CLI_config: dict[str, Any]):
        self.CLI_config = CLI_config

    async def process_dataset(self, dataset_metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Process a single dataset: scan → process → execute joins.

        Args:
            dataset_metadata: Dict with keys: name, project_id, workflow_id,
                              data_collections, has_joins, join_definitions

        Returns:
            Result dict with success status
        """
        dataset_name = dataset_metadata["name"]
        project_id = dataset_metadata["project_id"]

        logger.info(f"Processing reference dataset: {dataset_name}")

        # Fetch project from MongoDB
        from depictio.api.v1.db import projects_collection
        from depictio.api.v1.models.mongo_models import ProjectBeanie

        project_doc = await projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project_doc:
            logger.error(f"Project {project_id} not found")
            return {"success": False, "dataset": dataset_name, "error": "Project not found"}

        project = ProjectBeanie.from_mongo(project_doc)
        workflow = project.workflows[0]

        # Step 1: Process base data collections (not join results)
        base_dcs = [
            dc
            for dc in dataset_metadata["data_collections"]
            if not self._is_join_result(dc["tag"], dataset_metadata)
        ]

        for dc_info in base_dcs:
            dc_id = dc_info["id"]

            # Check if already processed (multi-instance safety)
            if await self._already_processed(dc_id):
                logger.info(f"DC {dc_info['tag']} already processed, skipping")
                continue

            # SCAN and PROCESS phases
            from depictio.cli.cli.utils.helpers import process_data_collection_helper

            logger.info(f"Scanning DC: {dc_info['tag']}")
            try:
                process_data_collection_helper(
                    CLI_config=self.CLI_config,
                    wf=workflow,
                    dc_id=dc_id,
                    mode="scan",
                )
            except Exception as e:
                logger.error(f"Failed to scan DC {dc_info['tag']}: {e}")
                continue

            logger.info(f"Processing DC: {dc_info['tag']}")
            try:
                process_data_collection_helper(
                    CLI_config=self.CLI_config,
                    wf=workflow,
                    dc_id=dc_id,
                    mode="process",
                    command_parameters={"overwrite": True},
                )
            except Exception as e:
                logger.error(f"Failed to process DC {dc_info['tag']}: {e}")
                continue

        # Step 2: Execute joins if dataset has them
        if dataset_metadata.get("has_joins"):
            await self._execute_joins(project, dataset_metadata)

        return {"success": True, "dataset": dataset_name}

    def _is_join_result(self, dc_tag: str, dataset_metadata: dict[str, Any]) -> bool:
        """Check if DC tag is a join result."""
        join_defs = dataset_metadata.get("join_definitions", [])
        join_names = [j["name"] for j in join_defs]
        return dc_tag in join_names

    async def _already_processed(self, dc_id: str) -> bool:
        """Check if DC already processed (MongoDB + S3)."""
        from depictio.api.v1.db import deltatables_collection
        from depictio.api.v1.services.background_tasks import check_s3_delta_table_exists

        # Check local MongoDB
        if await deltatables_collection.find_one({"data_collection_id": dc_id}):
            return True

        # Check S3
        if check_s3_delta_table_exists(settings.minio.bucket, dc_id):
            return True

        return False

    async def _execute_joins(self, project: Any, dataset_metadata: dict[str, Any]) -> dict[str, Any]:
        """Execute joins using existing CLI infrastructure."""
        logger.info(f"Executing joins for {dataset_metadata['name']}")

        # Use existing join system from CLI
        from depictio.cli.cli.utils.joins import process_project_joins
        from depictio.models.models.projects import Project

        # Convert to Project model (not ProjectBeanie)
        project_model = Project.model_validate(project.model_dump())

        try:
            result = process_project_joins(
                project=project_model,
                CLI_config=self.CLI_config,
                join_name=None,  # Process all joins
                preview_only=False,
                overwrite=True,
                auto_process_dependencies=True,
            )

            logger.info(f"Join execution completed for {dataset_metadata['name']}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute joins for {dataset_metadata['name']}: {e}")
            return {"success": False, "error": str(e)}


async def process_all_reference_datasets() -> None:
    """Main entry point for background processing."""
    from depictio.api.v1.db import initialization_collection, users_collection, tokens_collection
    from depictio.models.models.cli import CLIConfig, UserBaseCLIConfig

    # Retrieve metadata
    metadata_doc = await initialization_collection.find_one({"_id": "reference_datasets_metadata"})

    if not metadata_doc:
        logger.warning("No reference datasets metadata found")
        return

    # Get admin user credentials
    admin_user = await users_collection.find_one({"is_admin": True})
    if not admin_user:
        logger.error("No admin user found")
        return

    token = await tokens_collection.find_one({"user_id": admin_user["_id"]})
    if not token:
        logger.error("No token found for admin user")
        return

    # Build CLI config
    cli_config_dict = {
        "user": {
            "id": str(admin_user["_id"]),
            "email": admin_user["email"],
            "is_admin": admin_user["is_admin"],
            "token": token["token"],
        },
        "api_base_url": settings.fastapi.url,
        "s3_storage": settings.minio.model_dump(),
    }

    processor = ReferenceDatasetProcessor(cli_config_dict)

    # Process each dataset
    for dataset_metadata in metadata_doc["projects"]:
        try:
            result = await processor.process_dataset(dataset_metadata)
            logger.info(f"✅ Successfully processed {result['dataset']}")
        except Exception as e:
            logger.error(f"❌ Failed to process {dataset_metadata['name']}: {e}")
