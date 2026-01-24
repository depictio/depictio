"""Reference dataset initialization with static ID management."""

import os
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import Permission, UserBase, UserBeanie
from depictio.models.utils import get_config


class ReferenceDatasetRegistry:
    """Central registry for reference datasets with static ID management."""

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
        "multiqc": {
            "project": "646b0f3c1e4a2d7f8e5b8ca2",
            "workflows": {"test-workflow": "646b0f3c1e4a2d7f8e5b8ca3"},
            "data_collections": {
                "multiqc_data": "646b0f3c1e4a2d7f8e5b8ca4",
                "sample_metadata": "646b0f3c1e4a2d7f8e5b8ca5",
                "sample_qc_metrics": "646b0f3c1e4a2d7f8e5b8ca6",
                "qc_with_metadata": "646b0f3c1e4a2d7f8e5b8ca7",  # Join result
            },
        },
    }

    @classmethod
    def inject_static_ids(cls, project_config: dict[str, Any], dataset_name: str) -> dict[str, Any]:
        """Inject static IDs into project configuration including join results."""
        static_ids = cls.STATIC_IDS[dataset_name]

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

        # Set permissions
        project_config["permissions"] = Permission(
            owners=[UserBase(id=admin_user.id, email=admin_user.email, is_admin=True)],
            editors=[],
            viewers=[],
        )

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

        payload = await _helper_create_project_beanie(project, original_ids=original_ids)

        return {
            "success": payload["success"],
            "project": payload["project"],
            "has_joins": "joins" in project_config,
            "join_definitions": project_config.get("joins", []),
        }


async def create_reference_datasets(
    admin_user: UserBeanie, token_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Create all reference datasets (iris, penguins, multiqc)."""
    created_projects = []

    # Always create all three datasets
    for dataset_name in ["iris", "penguins", "multiqc"]:
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
                }
            )
            logger.info(f"✅ Created {dataset_name} project")

    return created_projects
