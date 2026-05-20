"""Generate iris + penguins .db_seeds/dashboard.json from their lite YAML.

Run once after editing the YAML files so the seed JSON used by
``create_initial_dashboards`` matches what users will import via
``depictio dashboard import``.

Usage:
    .venv/bin/python -m depictio.dev_scripts.generate_iris_penguins_seeds
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from bson import json_util

from depictio.models.models.dashboards import DashboardDataLite

REPO_ROOT = Path(__file__).resolve().parents[2]

# Static identifiers from db_init_reference_datasets.STATIC_IDS.
# Hardcoded here so this script has no MongoDB dependency.
PROJECTS: dict[str, dict[str, Any]] = {
    "iris": {
        "yaml": "depictio/projects/init/iris/dashboards/overview.yaml",
        "seed": "depictio/projects/init/iris/.db_seeds/dashboard.json",
        "dashboard_id": "6824cb3b89d2b72169309737",
        "project_id": "646b0f3c1e4a2d7f8e5b8c9a",
        "workflow_id": "646b0f3c1e4a2d7f8e5b8c9b",
        # Map data_collection_tag → static DC id.
        "dc_ids": {
            "iris_table": "646b0f3c1e4a2d7f8e5b8c9c",
        },
        # Per-DC config block embedded in each stored_metadata entry.
        "dc_configs": {
            "iris_table": {
                "type": "table",
                "metatype": "Metadata",
                "description": "Iris dataset in CSV format",
                "data_collection_tag": "iris_table",
                "dc_specific_properties": None,
            },
        },
        # Workflow tag carried on each component for the React viewer.
        "wf_tag": "python/iris_workflow",
        "icon": "/assets/images/icons/favicon.png",
        "icon_color": "orange",
    },
    "penguins": {
        "yaml": "depictio/projects/init/penguins/dashboards/species_analysis.yaml",
        "seed": "depictio/projects/init/penguins/.db_seeds/dashboard.json",
        "dashboard_id": "6824cb3b89d2b72169309738",
        "project_id": "646b0f3c1e4a2d7f8e5b8c9d",
        "workflow_id": "646b0f3c1e4a2d7f8e5b8c9e",
        # The YAML references the joined DC; map it to its static id.
        "dc_ids": {
            "joined_penguins_complete": "646b0f3c1e4a2d7f8e5b8ca1",
            "penguins_complete": "646b0f3c1e4a2d7f8e5b8ca1",
        },
        "dc_configs": {
            "joined_penguins_complete": {
                "type": "table",
                "metatype": "Aggregate",
                "description": "Complete penguin dataset with physical features and demographics",
                "data_collection_tag": "joined_penguins_complete",
                "dc_specific_properties": None,
            },
            "penguins_complete": {
                "type": "table",
                "metatype": "Aggregate",
                "description": "Complete penguin dataset with physical features and demographics",
                "data_collection_tag": "penguins_complete",
                "dc_specific_properties": None,
            },
        },
        "wf_tag": "python/penguin_species_analysis",
        "icon": "/assets/images/icons/favicon.png",
        "icon_color": "orange",
    },
}

ADMIN_USER_ID = "67658ba033c8b59ad489d7c7"
ADMIN_EMAIL = "admin@example.com"


def _build_oid(oid: str) -> dict[str, str]:
    return {"$oid": oid}


def _enrich_components(
    components: list[dict[str, Any]],
    workflow_id: str,
    dc_ids: dict[str, str],
    dc_configs: dict[str, dict[str, Any]],
    wf_tag: str,
) -> list[dict[str, Any]]:
    """Inject wf_id / dc_id / dc_config (with $oid wrappers) into each component."""
    enriched: list[dict[str, Any]] = []
    for comp in components:
        new_comp = dict(comp)
        comp_type = new_comp.get("component_type")
        dc_tag = new_comp.get("data_collection_tag") or ""

        # Text components: keep wf_tag but drop DC binding (dc_id stays null,
        # dc_config stays empty — the React TextRenderer ignores both).
        if comp_type == "text":
            new_comp["wf_id"] = _build_oid(workflow_id)
            new_comp["dc_id"] = None
            new_comp["dc_config"] = {}
            new_comp["wf_tag"] = wf_tag
            enriched.append(new_comp)
            continue

        # All other component types need a resolvable DC tag.
        dc_id = dc_ids.get(dc_tag)
        if dc_id is None:
            raise KeyError(
                f"Unknown data_collection_tag '{dc_tag}' for component "
                f"tag={new_comp.get('tag') or new_comp.get('index')!r}; "
                f"known tags: {sorted(dc_ids)}"
            )

        new_comp["wf_id"] = _build_oid(workflow_id)
        new_comp["dc_id"] = _build_oid(dc_id)
        cfg = dict(dc_configs[dc_tag])
        cfg["_id"] = _build_oid(dc_id)
        new_comp["dc_config"] = cfg
        new_comp["wf_tag"] = wf_tag
        enriched.append(new_comp)
    return enriched


def _build_seed_doc(project_key: str) -> dict[str, Any]:
    spec = PROJECTS[project_key]
    yaml_path = REPO_ROOT / spec["yaml"]
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)

    lite = DashboardDataLite.model_validate(raw)
    full = lite.to_full()

    full["stored_metadata"] = _enrich_components(
        full["stored_metadata"],
        workflow_id=spec["workflow_id"],
        dc_ids=spec["dc_ids"],
        dc_configs=spec["dc_configs"],
        wf_tag=spec["wf_tag"],
    )

    full["_id"] = _build_oid(spec["dashboard_id"])
    full["dashboard_id"] = _build_oid(spec["dashboard_id"])
    full["project_id"] = _build_oid(spec["project_id"])
    full["is_public"] = True
    full["icon"] = spec["icon"]
    full["icon_color"] = spec["icon_color"]
    full["icon_variant"] = "filled"
    full["workflow_system"] = "python"
    full["notes_content"] = ""
    full["permissions"] = {
        "owners": [
            {
                "_id": _build_oid(ADMIN_USER_ID),
                "email": ADMIN_EMAIL,
                "is_admin": True,
            }
        ],
        "editors": [],
        "viewers": [],
    }
    full["last_saved_ts"] = "2026-05-20 00:00:00"

    return full


def main() -> None:
    for key, spec in PROJECTS.items():
        doc = _build_seed_doc(key)
        seed_path = REPO_ROOT / spec["seed"]
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(json_util.dumps(doc, indent=2) + "\n")
        print(
            f"Wrote {seed_path.relative_to(REPO_ROOT)} "
            f"({len(doc.get('stored_metadata', []))} components)"
        )


if __name__ == "__main__":
    main()
