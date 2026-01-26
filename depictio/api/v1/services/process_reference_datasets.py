"""Background processing for reference datasets with join execution."""

from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


class ReferenceDatasetProcessor:
    """Orchestrates processing of reference datasets including joins."""

    def __init__(self, CLI_config):
        """Initialize with CLIConfig instance (from depictio.models.models.cli)."""
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
        from depictio.models.models.projects import ProjectBeanie

        project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project_doc:
            logger.error(f"Project {project_id} not found")
            return {"success": False, "dataset": dataset_name, "error": "Project not found"}

        project_beanie = ProjectBeanie.from_mongo(project_doc)
        workflow = project_beanie.workflows[0]

        # Convert to Project model for CLI functions
        from depictio.models.models.projects import Project

        project = Project.model_validate(project_beanie.model_dump())

        # Step 1: Scan and process base data collections (not join results)
        base_dcs = [
            dc
            for dc in dataset_metadata["data_collections"]
            if not self._is_join_result(dc["tag"], dataset_metadata)
        ]

        # Use project-level helper for scan/process (handles both single and aggregate modes)
        from depictio.cli.cli.utils.helpers import process_project_helper

        # SCAN ALL DCs in workflow at once (they share the same runs)
        # Scanning one DC at a time would skip existing runs for subsequent DCs
        any_unprocessed = any(not self._already_processed(dc["id"]) for dc in base_dcs)

        if any_unprocessed:
            logger.info(f"Scanning workflow {workflow.name} for all data collections")
            try:
                process_project_helper(
                    CLI_config=self.CLI_config,
                    project_config=project,
                    mode="scan",
                    workflow_name=workflow.name,
                    data_collection_tag=None,  # Scan all DCs in workflow
                )
            except Exception as e:
                logger.error(f"Failed to scan workflow {workflow.name}: {e}")
                return {"success": False, "dataset": dataset_name, "error": str(e)}

        # PROCESS each DC individually
        for dc_info in base_dcs:
            dc_id = dc_info["id"]
            dc_tag = dc_info["tag"]

            # Check if already processed (multi-instance safety)
            if self._already_processed(dc_id):
                logger.info(f"DC {dc_tag} already processed, skipping")
                continue

            # PROCESS phase
            logger.info(f"Processing DC: {dc_tag}")
            try:
                process_project_helper(
                    CLI_config=self.CLI_config,
                    project_config=project,
                    mode="process",
                    workflow_name=workflow.name,
                    data_collection_tag=dc_tag,
                    command_parameters={"overwrite": True},
                )
            except Exception as e:
                logger.error(f"Failed to process DC {dc_tag}: {e}")
                continue

        # Step 2: Execute joins if dataset has them
        if dataset_metadata.get("has_joins"):
            await self._execute_joins(project, dataset_metadata)

        # Step 3: Log link registration status
        if dataset_metadata.get("has_links"):
            link_count = len(dataset_metadata.get("link_definitions", []))
            logger.info(
                f"Dataset {dataset_name} has {link_count} links registered "
                f"(registered during project creation)"
            )

        return {"success": True, "dataset": dataset_name}

    def _is_join_result(self, dc_tag: str, dataset_metadata: dict[str, Any]) -> bool:
        """Check if DC tag is a join result."""
        join_defs = dataset_metadata.get("join_definitions", [])
        join_names = [j["name"] for j in join_defs]
        return dc_tag in join_names

    def _already_processed(self, dc_id: str) -> bool:
        """Check if DC already processed (MongoDB + S3)."""
        from depictio.api.v1.db import deltatables_collection
        from depictio.api.v1.services.background_tasks import check_s3_delta_table_exists

        # Check local MongoDB
        if deltatables_collection.find_one({"data_collection_id": dc_id}):
            return True

        # Check S3
        if check_s3_delta_table_exists(settings.minio.bucket, dc_id):
            return True

        return False

    async def _execute_joins(
        self, project: Any, dataset_metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute joins using existing CLI infrastructure.

        Args:
            project: Project model instance (already converted from ProjectBeanie)
            dataset_metadata: Dataset metadata dict
        """
        logger.info(f"Executing joins for {dataset_metadata['name']}")

        # Pre-check: Verify all join dependencies are registered
        join_definitions = dataset_metadata.get("join_definitions", [])
        if not join_definitions:
            logger.info(f"No joins defined for {dataset_metadata['name']}")
            return {"success": True, "joins_processed": 0}

        # Build DC tag -> ID mapping
        dc_tag_to_id = {}
        for workflow in project.workflows:
            for dc in workflow.data_collections:
                dc_tag_to_id[dc.data_collection_tag] = str(dc.id)

        # Check which joins can be executed
        executable_joins = []
        skipped_joins = []

        for join_def in join_definitions:
            left_dc_tag = join_def["left_dc"]
            right_dc_tag = join_def["right_dc"]
            join_name = join_def["name"]

            left_dc_id = dc_tag_to_id.get(left_dc_tag)
            right_dc_id = dc_tag_to_id.get(right_dc_tag)

            if not left_dc_id or not right_dc_id:
                logger.warning(
                    f"Skipping join '{join_name}': DC tags not found in project "
                    f"(left: {left_dc_tag}, right: {right_dc_tag})"
                )
                skipped_joins.append(join_name)
                continue

            # Check if both DCs are registered in deltatables
            left_registered = self._already_processed(left_dc_id)
            right_registered = self._already_processed(right_dc_id)

            if not left_registered or not right_registered:
                logger.warning(
                    f"Skipping join '{join_name}': dependencies not registered "
                    f"({left_dc_tag}={left_registered}, {right_dc_tag}={right_registered})"
                )
                skipped_joins.append(join_name)
                continue

            # Check for known problematic join combinations
            # Skip metadata+aggregate joins (different depictio_run_id granularities)
            left_dc = next(
                (
                    dc
                    for dc in project.workflows[0].data_collections
                    if dc.data_collection_tag == left_dc_tag
                ),
                None,
            )
            right_dc = next(
                (
                    dc
                    for dc in project.workflows[0].data_collections
                    if dc.data_collection_tag == right_dc_tag
                ),
                None,
            )

            if left_dc and right_dc:
                left_metatype = (
                    left_dc.config.metatype if hasattr(left_dc.config, "metatype") else None
                )
                right_metatype = (
                    right_dc.config.metatype if hasattr(right_dc.config, "metatype") else None
                )

                # Skip joins between Metadata and Aggregate (incompatible run_id granularities)
                if (left_metatype == "Metadata" and right_metatype == "Aggregate") or (
                    left_metatype == "Aggregate" and right_metatype == "Metadata"
                ):
                    logger.warning(
                        f"Skipping join '{join_name}': incompatible metatypes "
                        f"({left_dc_tag}={left_metatype}, {right_dc_tag}={right_metatype}). "
                        f"Metadata and Aggregate have different depictio_run_id granularities."
                    )
                    skipped_joins.append(join_name)
                    continue

            executable_joins.append(join_name)

        if not executable_joins:
            logger.warning(
                f"No executable joins for {dataset_metadata['name']} "
                f"(all {len(join_definitions)} joins skipped due to missing dependencies)"
            )
            return {"success": True, "joins_processed": 0, "joins_skipped": skipped_joins}

        logger.info(
            f"Executing {len(executable_joins)} joins for {dataset_metadata['name']} "
            f"({len(skipped_joins)} skipped)"
        )

        # Use existing join system from CLI
        from depictio.cli.cli.utils.joins import process_project_joins

        try:
            result = process_project_joins(
                project=project,
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
    from datetime import datetime, timezone

    logger.info("🚀 Starting background processing for reference datasets")

    from depictio.api.v1.db import initialization_collection, tokens_collection, users_collection

    try:
        # Retrieve metadata
        metadata_doc = initialization_collection.find_one({"_id": "reference_datasets_metadata"})

        if not metadata_doc:
            logger.warning("⚠️  No reference datasets metadata found in initialization_collection")
            return

        logger.info(
            f"📋 Found metadata for {len(metadata_doc.get('projects', []))} reference datasets"
        )

        # Get admin user credentials
        admin_user = users_collection.find_one({"is_admin": True})
        if not admin_user:
            logger.error("No admin user found")
            return

        token = tokens_collection.find_one({"user_id": admin_user["_id"]})
        if not token:
            logger.error("No token found for admin user")
            return

        # Build CLI config matching CLIConfig model structure
        from depictio.models.models.cli import CLIConfig

        cli_config_dict = {
            "user": {
                "id": str(admin_user["_id"]),
                "email": admin_user["email"],
                "is_admin": admin_user["is_admin"],
                # Token as dict matching TokenBase structure (token doc already has all fields)
                "token": {
                    "user_id": token["user_id"],
                    "access_token": token["access_token"],
                    "refresh_token": token["refresh_token"],
                    "token_type": token.get("token_type", "bearer"),
                    "token_lifetime": token.get("token_lifetime", "short-lived"),
                    "expire_datetime": token["expire_datetime"],
                    "refresh_expire_datetime": token["refresh_expire_datetime"],
                    "name": token.get("name"),
                    "created_at": token.get("created_at"),
                },
            },
            "api_base_url": settings.fastapi.url,
            # Use settings.minio directly - it's already an S3DepictioCLIConfig instance
            "s3_storage": settings.minio,
        }

        # Convert dict to CLIConfig instance (some functions don't have @validate_call)
        cli_config = CLIConfig(**cli_config_dict)
        processor = ReferenceDatasetProcessor(cli_config)

        # Process each dataset
        for dataset_metadata in metadata_doc["projects"]:
            try:
                logger.info(f"📦 Processing dataset: {dataset_metadata['name']}")
                result = await processor.process_dataset(dataset_metadata)
                logger.info(f"✅ Successfully processed {result['dataset']}")
            except Exception as e:
                logger.error(f"❌ Failed to process {dataset_metadata['name']}: {e}")
                import traceback

                logger.error(f"Traceback: {traceback.format_exc()}")

        # Mark background processing as complete
        initialization_collection.update_one(
            {"_id": "reference_datasets_metadata"},
            {"$set": {"background_processing_complete": True}},
            upsert=False,
        )
        logger.info("✅ Background processing completed successfully")

    except Exception as e:
        logger.error(f"❌ CRITICAL: Background processing failed with exception: {e}")
        import traceback

        logger.error(f"Full traceback:\n{traceback.format_exc()}")

        # Store failure state for health check
        initialization_collection.update_one(
            {"_id": "reference_datasets_metadata"},
            {
                "$set": {
                    "background_processing_failed": True,
                    "last_error": str(e),
                    "last_error_time": datetime.now(timezone.utc),
                }
            },
            upsert=False,
        )

        # Re-raise to ensure the error is visible
        raise
