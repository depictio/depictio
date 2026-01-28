"""Reference dataset initialization with static ID management."""

import os
from typing import Any, cast

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase, UserBeanie
from depictio.models.utils import get_config

# Static ID mappings (hardcoded for K8s consistency)
STATIC_IDS = {
    "iris": {
        "project": "646b0f3c1e4a2d7f8e5b8c9a",
        "workflows": {"iris_workflow": "646b0f3c1e4a2d7f8e5b8c9b"},
        "data_collections": {
            "iris_table": "646b0f3c1e4a2d7f8e5b8c9c",
        },
    },
    "penguins": {
        "project": "646b0f3c1e4a2d7f8e5b8c9d",
        "workflows": {"penguin_species_analysis": "646b0f3c1e4a2d7f8e5b8c9e"},
        "data_collections": {
            "physical_features": "646b0f3c1e4a2d7f8e5b8c9f",
            "demographic_data": "646b0f3c1e4a2d7f8e5b8ca0",
            "penguins_complete": "646b0f3c1e4a2d7f8e5b8ca1",  # Join result
        },
    },
    "ampliseq": {
        "project": "646b0f3c1e4a2d7f8e5b8ca2",
        "workflows": {"ampliseq": "646b0f3c1e4a2d7f8e5b8ca3"},
        "data_collections": {
            "multiqc_data": "646b0f3c1e4a2d7f8e5b8ca4",
            "metadata": "646b0f3c1e4a2d7f8e5b8ca5",
            "alpha_rarefaction": "646b0f3c1e4a2d7f8e5b8ca8",
            "taxonomy_composition": "646b0f3c1e4a2d7f8e5b8ca9",
            "ancom_volcano": "646b0f3c1e4a2d7f8e5b8caa",
            # Join results (disabled temporarily for initial testing)
            # "alpha_rarefaction_enriched": "646b0f3c1e4a2d7f8e5b8cab",
            # "taxonomy_enriched": "646b0f3c1e4a2d7f8e5b8cac",
        },
    },
    "multiqc": {
        "project": "646b0f3c1e4a2d7f8e5b8cad",
        "workflows": {"test-workflow": "646b0f3c1e4a2d7f8e5b8cae"},
        "data_collections": {
            "multiqc_data": "646b0f3c1e4a2d7f8e5b8caf",
            "sample_metadata": "646b0f3c1e4a2d7f8e5b8cb0",
            "sample_qc_metrics": "646b0f3c1e4a2d7f8e5b8cb1",
            "qc_with_metadata": "646b0f3c1e4a2d7f8e5b8cb2",  # Join result
        },
    },
}


class ReferenceDatasetRegistry:
    """Central registry for reference datasets with static ID management."""

    @classmethod
    def inject_static_ids(cls, project_config: dict[str, Any], dataset_name: str) -> dict[str, Any]:
        """Inject static IDs into project configuration including join results."""
        static_ids = STATIC_IDS[dataset_name]

        # Set project ID
        project_config["id"] = static_ids["project"]

        # Set workflow and DC IDs
        for workflow in project_config["workflows"]:
            wf_name = workflow["name"]
            if wf_name in static_ids["workflows"]:
                workflow["id"] = static_ids["workflows"][wf_name]

            # Set base DC IDs
            for dc in workflow["data_collections"]:
                dc_tag = dc["data_collection_tag"]
                if dc_tag in static_ids["data_collections"]:
                    dc["id"] = static_ids["data_collections"][dc_tag]

        # Pre-allocate join result IDs
        if "joins" in project_config:
            for join_def in project_config["joins"]:
                join_name = join_def["name"]
                if join_name in static_ids["data_collections"]:
                    join_def["_static_dc_id"] = static_ids["data_collections"][join_name]

        return project_config

    @classmethod
    async def _register_links(cls, project, links_config: list[dict[str, Any]]) -> None:
        """Resolve DC tags/IDs and register links in project.

        Supports both formats:
        - Legacy: source_dc_id="metadata" (DC tag)
        - New: source_dc_id="646b0f3c1e4a2d7f8e5b8ca5" (DC ID)

        Args:
            project: Created ProjectBeanie instance
            links_config: List of link definitions from YAML with DC tags or IDs
        """
        from depictio.api.v1.db import projects_collection
        from depictio.models.models.base import PyObjectId
        from depictio.models.models.links import DCLink

        # Build DC tag -> ID mapping for legacy format support
        dc_tag_to_id = {}
        for workflow in project.workflows:
            for dc in workflow.data_collections:
                dc_tag_to_id[dc.data_collection_tag] = str(dc.id)

        # Helper: Resolve DC identifier (tag or ID) to actual ID
        def resolve_dc_id(dc_identifier: str | None) -> str | None:
            """Resolve DC tag or ID to actual ObjectId string.

            Args:
                dc_identifier: Either a DC tag (e.g., "metadata") or DC ID (24-char hex), or None

            Returns:
                Valid ObjectId string or None if not found
            """
            if dc_identifier is None:
                return None

            # Try as DC ID first (24-char hex string)
            if len(dc_identifier) == 24:
                try:
                    # Validate it's a valid ObjectId format
                    ObjectId(dc_identifier)
                    return dc_identifier  # Already a valid DC ID
                except Exception:
                    pass  # Not a valid ObjectId, try as tag

            # Try as DC tag
            return dc_tag_to_id.get(dc_identifier)

        # Convert links from tag/ID-based to ID-based
        resolved_links = []
        for link_config in links_config:
            source_identifier = link_config.get("source_dc_id")
            target_identifier = link_config.get("target_dc_id")

            source_id = resolve_dc_id(source_identifier)
            target_id = resolve_dc_id(target_identifier)

            if not source_id or not target_id:
                logger.warning(
                    f"Skipping link - could not resolve DC identifiers: "
                    f"source={source_identifier} (resolved={source_id}), "
                    f"target={target_identifier} (resolved={target_id}). "
                    f"Available DC tags: {list(dc_tag_to_id.keys())}"
                )
                continue

            # Create DCLink with resolved IDs
            link = DCLink(
                id=PyObjectId(),
                source_dc_id=source_id,
                source_column=link_config["source_column"],
                target_dc_id=target_id,
                target_type=link_config["target_type"],
                link_config=link_config.get("link_config", {}),
                description=link_config.get("description"),
                enabled=link_config.get("enabled", True),
            )
            resolved_links.append(link)

        # Update project document with resolved links
        if resolved_links:
            link_dicts = [link.model_dump() for link in resolved_links]
            # Convert PyObjectId to string for MongoDB
            for link_dict in link_dicts:
                link_dict["id"] = str(link_dict["id"])

            projects_collection.update_one(
                {"_id": ObjectId(str(project.id))},
                {"$set": {"links": link_dicts}},
            )
            logger.info(f"Registered {len(resolved_links)} links for project {project.name}")

    @classmethod
    async def create_reference_project(
        cls, dataset_name: str, admin_user: UserBeanie, token_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a reference project with proper static IDs."""
        # Load project.yaml
        project_yaml_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "projects",
            "init" if dataset_name == "iris" else "reference",
            dataset_name,
            "project.yaml",
        )
        project_config = get_config(project_yaml_path)

        # Inject static IDs
        project_config = cls.inject_static_ids(project_config, dataset_name)

        # Extract links early (needed for both new and existing projects)
        links_config = project_config.get("links", [])

        # Check if project already exists (idempotent initialization)
        from depictio.api.v1.db import projects_collection

        static_project_id = ObjectId(project_config["id"])
        existing_project = projects_collection.find_one({"_id": static_project_id})

        if existing_project:
            logger.info(
                f"Project {dataset_name} already exists with ID {static_project_id}, skipping creation"
            )
            from depictio.models.models.projects import ProjectBeanie

            project = ProjectBeanie.from_mongo(existing_project)

            # Ensure project is public for reference projects
            if not existing_project.get("is_public", False):
                logger.info(f"Setting existing project {dataset_name} to public")
                projects_collection.update_one(
                    {"_id": static_project_id},
                    {"$set": {"is_public": True}},
                )

            # Register links if not already present
            existing_links = existing_project.get("links", [])
            if not existing_links and links_config:
                logger.info(f"Registering links for existing project {dataset_name}")
                await cls._register_links(project, links_config)

            return {
                "success": True,
                "project": project,
                "has_joins": "joins" in project_config,
                "join_definitions": project_config.get("joins", []),
                "has_links": len(links_config) > 0,
                "link_definitions": links_config,
            }

        # Set permissions
        if not admin_user.id:
            raise ValueError("Admin user must have an ID")
        project_config["permissions"] = Permission(
            owners=[
                UserBase(id=cast(PyObjectId, admin_user.id), email=admin_user.email, is_admin=True)
            ],
            editors=[],
            viewers=[],
        )

        # Set reference projects as public by default for K8s demo environments
        project_config["is_public"] = True

        # Extract and remove _static_dc_id from join definitions (not allowed in ProjectBeanie)
        # These will be handled during join execution in the background processor
        if "joins" in project_config:
            for join_def in project_config["joins"]:
                join_def.pop("_static_dc_id", None)

        # Remove links from project_config - will be resolved and added after project creation
        # Links use DC tags which need to be converted to DC IDs
        # (already extracted earlier for use in both new and existing project paths)
        project_config.pop("links", None)

        # Create project (reuse existing _helper_create_project_beanie logic)
        from depictio.api.v1.endpoints.projects_endpoints.utils import _helper_create_project_beanie
        from depictio.models.models.projects import ProjectBeanie

        project = ProjectBeanie(**project_config)

        # Restore original IDs using integer indices (required by _helper_create_project_beanie)
        original_ids = {
            "project": ObjectId(project_config["id"]),
            "workflows": {
                wf_idx: {
                    "id": ObjectId(wf["id"]),
                    "data_collections": {
                        dc_idx: ObjectId(dc["id"])
                        for dc_idx, dc in enumerate(wf["data_collections"])
                    },
                }
                for wf_idx, wf in enumerate(project_config["workflows"])
            },
        }

        try:
            payload = await _helper_create_project_beanie(project, original_ids=original_ids)
            created_project = payload["project"]
        except Exception as e:
            # Handle race condition: another worker created the project between check and create
            # This can manifest as DuplicateKeyError (MongoDB) or HTTPException 400 (API layer)
            from fastapi import HTTPException
            from pymongo.errors import DuplicateKeyError

            is_duplicate_error = (
                isinstance(e.__cause__, DuplicateKeyError)
                or "duplicate key error" in str(e).lower()
                or "already exists" in str(e).lower()
                or (
                    isinstance(e, HTTPException)
                    and e.status_code == 400
                    and "already exists" in str(e.detail).lower()
                )
            )

            if is_duplicate_error:
                logger.warning(
                    f"Race condition detected: project {dataset_name} was created by another worker. "
                    f"Retrieving existing project."
                )
                # Retrieve the project that was created by the other worker (by name since ID might differ)
                existing_project = projects_collection.find_one({"name": project_config["name"]})
                if not existing_project:
                    # Try by ID as fallback
                    existing_project = projects_collection.find_one({"_id": static_project_id})

                if existing_project:
                    created_project = ProjectBeanie.from_mongo(existing_project)
                    payload = {
                        "success": True,
                        "project": created_project,
                    }  # Mark as success since project exists
                else:
                    # This shouldn't happen, but re-raise if we can't find the project
                    raise
            else:
                # Re-raise if it's a different error
                raise

        # Step 2: Resolve and register links if present in YAML
        if links_config:
            await cls._register_links(created_project, links_config)

        return {
            "success": payload["success"],
            "project": created_project,
            "has_joins": "joins" in project_config,
            "join_definitions": project_config.get("joins", []),
            "has_links": len(links_config) > 0,
            "link_definitions": links_config,
        }


async def create_reference_datasets(
    admin_user: UserBeanie, token_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Create all reference datasets (iris, penguins, ampliseq).

    Note: ampliseq dataset uses 16S rRNA microbiome data from nf-core/ampliseq.
    Data files are included:
    - depictio/projects/reference/ampliseq/multiqc.parquet
    - depictio/projects/reference/ampliseq/merged_metadata.tsv
    - depictio/projects/reference/ampliseq/faith_pd_long.tsv
    - depictio/projects/reference/ampliseq/taxonomy_long.tsv
    - depictio/projects/reference/ampliseq/ancom_volcano.tsv
    """
    created_projects = []

    # Create reference datasets (iris, penguins, ampliseq)
    for dataset_name in ["iris", "penguins", "ampliseq"]:
        logger.info(f"Creating reference dataset: {dataset_name}")

        result = await ReferenceDatasetRegistry.create_reference_project(
            dataset_name=dataset_name, admin_user=admin_user, token_payload=token_payload
        )

        if result["success"]:
            created_projects.append(
                {
                    "name": dataset_name,
                    "project_id": str(result["project"].id),
                    "workflow_id": str(result["project"].workflows[0].id),
                    "data_collections": [
                        {"id": str(dc.id), "tag": dc.data_collection_tag}
                        for dc in result["project"].workflows[0].data_collections
                    ],
                    "has_joins": result["has_joins"],
                    "join_definitions": result.get("join_definitions", []),
                    "has_links": result.get("has_links", False),
                    "link_definitions": result.get("link_definitions", []),
                }
            )
            logger.info(f"✅ Created {dataset_name} project")

    return created_projects
