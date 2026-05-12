"""Reference dataset initialization with static ID management."""

import copy
import os
import re as _re
from pathlib import Path
from typing import Any, cast

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.cli.cli.utils.templates import _apply_conditionals, substitute_template_variables
from depictio.models.models.base import PyObjectId
from depictio.models.models.templates import TemplateConditional
from depictio.models.models.users import Permission, UserBase, UserBeanie
from depictio.models.utils import get_config

_UNRESOLVED_VAR_RE = _re.compile(r"\{[A-Z0-9_]+\}")


def _has_unresolved_vars(obj: Any) -> bool:
    """Return True if any string in obj still contains a {VAR} placeholder."""
    if isinstance(obj, str):
        return bool(_UNRESOLVED_VAR_RE.search(obj))
    if isinstance(obj, dict):
        return any(_has_unresolved_vars(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_unresolved_vars(item) for item in obj)
    return False


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
            "samplesheet": "646b0f3c1e4a2d7f8e5b8cab",
            "metadata": "646b0f3c1e4a2d7f8e5b8ca5",
            "alpha_diversity": "646b0f3c1e4a2d7f8e5b8ca6",
            "alpha_rarefaction": "646b0f3c1e4a2d7f8e5b8ca7",
            "taxonomy_composition": "646b0f3c1e4a2d7f8e5b8ca8",
            "taxonomy_rel_abundance": "646b0f3c1e4a2d7f8e5b8ca9",
            "taxonomy_heatmap": "646b0f3c1e4a2d7f8e5b8caf",
            "ancombc_results": "646b0f3c1e4a2d7f8e5b8caa",
            # Canonical-schema DCs feeding the advanced_viz components — see
            # depictio/projects/nf-core/ampliseq/recipes/{volcano,stacked_
            # taxonomy,embedding_pcoa}_canonical.py.
            "volcano_canonical": "646b0f3c1e4a2d7f8e5b8cb0",
            "stacked_taxonomy_canonical": "646b0f3c1e4a2d7f8e5b8cb1",
            "embedding_pcoa": "646b0f3c1e4a2d7f8e5b8cb2",
        },
        "dashboards": {
            "ampliseq_multiqc": "646b0f3c1e4a2d7f8e5b8cb7",
            "ampliseq_community": "646b0f3c1e4a2d7f8e5b8cb3",
            "ampliseq_differential": "646b0f3c1e4a2d7f8e5b8cb4",
            "ampliseq_advanced_viz": "646b0f3c1e4a2d7f8e5b8cc2",
        },
    },
    "ampliseq_base": {
        # Separate project entry that shares DCs with the main ampliseq project
        # but presents only the base (no-metadata) dashboard variant.
        "project": "646b0f3c1e4a2d7f8e5b8cb6",
        "dashboards": {
            "ampliseq_base_multiqc": "646b0f3c1e4a2d7f8e5b8cb8",
            "ampliseq_base_community": "646b0f3c1e4a2d7f8e5b8cb5",
            "ampliseq_base_differential": "646b0f3c1e4a2d7f8e5b8cc1",
        },
    },
    # Dedicated showcase for the advanced_viz component family — one project
    # with four classical viz fixtures plus four clustering-method fixtures
    # (PCA / UMAP / t-SNE / PCoA) projected from a shared 90×200 feature
    # matrix. Eight dashboard tabs: overview + volcano + manhattan + stacked
    # taxonomy + one per clustering method.
    # See projects/init/advanced_viz_showcase/.
    "advanced_viz_showcase": {
        "project": "646b0f3c1e4a2d7f8e5b8d00",
        "workflows": {"advanced_viz_demo": "646b0f3c1e4a2d7f8e5b8d01"},
        "data_collections": {
            "volcano_demo": "646b0f3c1e4a2d7f8e5b8d02",
            # PCA reuses the old embedding_demo id (d03) so the seed JSON
            # doesn't churn an ObjectId; the other three methods are new.
            "embedding_pca": "646b0f3c1e4a2d7f8e5b8d03",
            "manhattan_demo": "646b0f3c1e4a2d7f8e5b8d04",
            "stacked_taxonomy_demo": "646b0f3c1e4a2d7f8e5b8d05",
            "embedding_umap": "646b0f3c1e4a2d7f8e5b8d06",
            "embedding_tsne": "646b0f3c1e4a2d7f8e5b8d07",
            "embedding_pcoa": "646b0f3c1e4a2d7f8e5b8d08",
            # Phylogenetic showcase: bacterial tree + tip metadata.
            "bacterial_tree": "646b0f3c1e4a2d7f8e5b8d09",
            "bacterial_metadata": "646b0f3c1e4a2d7f8e5b8d0a",
            # Raw sample × feature matrix — input for live Celery clustering.
            "embedding_features": "646b0f3c1e4a2d7f8e5b8d0b",
        },
        "dashboards": {
            # Main tab reuses the project_id so get_child_tabs(main_id) finds
            # the children (this is the same convention as ampliseq, whose
            # main dashboard _id equals project_id 5b8ca2).
            "advanced_viz_overview": "646b0f3c1e4a2d7f8e5b8d00",
            "advanced_viz_volcano": "646b0f3c1e4a2d7f8e5b8d11",
            # PCA reuses the old embedding-tab id (d12).
            "advanced_viz_clustering_pca": "646b0f3c1e4a2d7f8e5b8d12",
            "advanced_viz_manhattan": "646b0f3c1e4a2d7f8e5b8d13",
            "advanced_viz_stacked_taxonomy": "646b0f3c1e4a2d7f8e5b8d14",
            "advanced_viz_clustering_umap": "646b0f3c1e4a2d7f8e5b8d15",
            "advanced_viz_clustering_tsne": "646b0f3c1e4a2d7f8e5b8d16",
            "advanced_viz_clustering_pcoa": "646b0f3c1e4a2d7f8e5b8d17",
            "advanced_viz_phylogeny": "646b0f3c1e4a2d7f8e5b8d18",
            "advanced_viz_clustering_live": "646b0f3c1e4a2d7f8e5b8d19",
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
        # Support both formats: source_dc_id/target_dc_id (project.yaml) and
        # source_dc_tag/target_dc_tag (template.yaml)
        resolved_links = []
        for link_config in links_config:
            source_identifier = link_config.get("source_dc_id") or link_config.get("source_dc_tag")
            target_identifier = link_config.get("target_dc_id") or link_config.get("target_dc_tag")

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

    # Dataset name → relative path under depictio/projects/
    DATASET_PATHS: dict[str, str] = {
        "iris": os.path.join("init", "iris"),
        "penguins": os.path.join("init", "penguins"),
        "ampliseq": os.path.join("nf-core", "ampliseq", "2.16.0"),
        "advanced_viz_showcase": os.path.join("init", "advanced_viz_showcase"),
    }

    @classmethod
    def resolve_template_for_init(
        cls, template_config: dict[str, Any], data_root: str
    ) -> dict[str, Any]:
        """Resolve a template.yaml for init usage.

        1. Reads ``template:`` conditionals, then strips the section.
        2. Substitutes ``{DATA_ROOT}`` via the shared ``substitute_template_variables``.
        3. Applies conditional DC/link removal (e.g. removes metadata DC when METADATA_FILE absent).
        4. Skips DCs whose config still contains unresolved ``{VAR}`` placeholders
           (e.g. samplesheet DC with ``{SAMPLESHEET_FILE}`` — required in CLI runs but
           not applicable to the reference demo dataset).
        5. Converts recipe-based DCs (``source: "transformed"``) to file-scan DCs
           using the convention ``{DATA_ROOT}/{dc_tag}.tsv``.
        """
        config = copy.deepcopy(template_config)

        # 1. Read template metadata BEFORE popping — need conditionals + reference defaults
        template_section = config.get("template", {})
        raw_conditionals = template_section.get("conditional", [])
        conditionals = [TemplateConditional(**c) for c in raw_conditionals]
        reference_defaults: dict[str, str] = (template_section.get("reference") or {}).get(
            "vars", {}
        )
        config.pop("template", None)

        # 2. Build variables: DATA_ROOT + reference defaults (with DATA_ROOT substituted inside them)
        variables: dict[str, str] = {"DATA_ROOT": data_root}
        for var_name, var_default in reference_defaults.items():
            variables[var_name] = var_default.replace("{DATA_ROOT}", data_root)
        provided_vars: set[str] = set(variables.keys())
        config = substitute_template_variables(config, variables)

        # 3. Apply conditional DC/link removal (pass dummy template_dir — init ignores dashboards)
        config, _ = _apply_conditionals(config, conditionals, provided_vars, Path("."))

        # 4. Skip DCs whose config still has unresolved {VAR} placeholders and prune their links
        skipped_dc_tags: set[str] = set()
        for workflow in config.get("workflows", []):
            surviving = []
            for dc in workflow.get("data_collections", []):
                if _has_unresolved_vars(dc.get("config", {})):
                    skipped_dc_tags.add(dc["data_collection_tag"])
                    logger.debug(
                        f"Init resolver: skipping DC '{dc['data_collection_tag']}' "
                        "— config contains unresolved template variables"
                    )
                else:
                    surviving.append(dc)
            workflow["data_collections"] = surviving

        if skipped_dc_tags:
            config["links"] = [
                lnk
                for lnk in config.get("links", [])
                if lnk.get("source_dc_tag") not in skipped_dc_tags
                and lnk.get("target_dc_tag") not in skipped_dc_tags
            ]

        # 5. Convert recipe DCs → file-scan DCs (skipping any whose seed file is missing)
        missing_seed_dc_tags: set[str] = set()
        for workflow in config.get("workflows", []):
            surviving = []
            for dc in workflow.get("data_collections", []):
                dc_config = dc.get("config", {})
                if dc_config.get("source") == "transformed" and "transform" in dc_config:
                    dc_tag = dc["data_collection_tag"]
                    # Convention: pre-computed files are named {dc_tag}.tsv
                    pre_computed_path = os.path.join(data_root, f"{dc_tag}.tsv")
                    if not os.path.exists(pre_computed_path):
                        # Drop the DC rather than letting the workflow scan abort on a
                        # missing recipe seed (one missing file otherwise sinks every
                        # other DC in the workflow — see scan_files_for_data_collection).
                        missing_seed_dc_tags.add(dc_tag)
                        logger.warning(
                            f"Init resolver: skipping recipe DC '{dc_tag}' — "
                            f"pre-computed seed not found at {pre_computed_path}"
                        )
                        continue
                    dc_config.pop("source", None)
                    dc_config.pop("transform", None)
                    dc_config["scan"] = {
                        "mode": "single",
                        "scan_parameters": {"filename": pre_computed_path},
                    }
                    logger.debug(
                        f"Init resolver: converted recipe DC '{dc_tag}' → file scan: {pre_computed_path}"
                    )
                surviving.append(dc)
            workflow["data_collections"] = surviving

        if missing_seed_dc_tags:
            config["links"] = [
                lnk
                for lnk in config.get("links", [])
                if lnk.get("source_dc_tag") not in missing_seed_dc_tags
                and lnk.get("target_dc_tag") not in missing_seed_dc_tags
            ]

        return config

    @classmethod
    async def create_reference_project(
        cls, dataset_name: str, admin_user: UserBeanie, token_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a reference project with proper static IDs."""
        rel_path = cls.DATASET_PATHS[dataset_name]
        project_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "projects",
            rel_path,
        )

        # Prefer template.yaml (single source of truth), fall back to project.yaml
        template_path = os.path.join(project_dir, "template.yaml")
        project_yaml_path = os.path.join(project_dir, "project.yaml")

        if os.path.exists(template_path):
            raw_config = get_config(template_path)
            # Resolve for Docker init: /app/depictio/projects/<rel_path>
            data_root = f"/app/depictio/projects/{rel_path}"
            project_config = cls.resolve_template_for_init(raw_config, data_root)
        elif os.path.exists(project_yaml_path):
            project_config = get_config(project_yaml_path)
        else:
            raise FileNotFoundError(
                f"No template.yaml or project.yaml found for dataset '{dataset_name}' in {project_dir}"
            )

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

        # Add template_origin for template-based projects (ampliseq)
        if os.path.exists(template_path):
            from depictio.models.models.templates import TemplateOrigin

            raw_template = get_config(template_path)
            tmpl = raw_template.get("template", {})
            project_config["template_origin"] = TemplateOrigin(
                template_id=tmpl.get("template_id", dataset_name),
                template_version=tmpl.get("version", "1.0.0"),
                data_root=data_root,
                variables=tmpl.get("reference", {}).get("vars", {}),
            ).model_dump()

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
    Data files are included under depictio/projects/nf-core/ampliseq/2.16.0/.
    """
    created_projects = []

    # Create reference datasets (iris, penguins, ampliseq, advanced_viz_showcase)
    for dataset_name in ["iris", "penguins", "ampliseq", "advanced_viz_showcase"]:
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
