"""Generate the four benchmarking `.db_seeds/dashboard_benchmark_*.json`.

The advanced-viz showcase's other tabs exist only as seed JSON — the YAML they
were once built from is not committed. These four arrived the other way round:
their YAML landed with the benchmarking viz kinds, but no seed, and `db_init`
reads *only* the seeds. So on a fresh deployment the four dashboards simply did
not exist, and anything addressing them by title (the component-export showcase
resolves `bench_pr`, `bench_roc`, …) failed against a perfectly healthy API.

Run this after editing any of the four YAMLs, then commit the regenerated JSON:

    .venv/bin/python -m depictio.dev_scripts.generate_benchmark_seeds

Mirrors ``generate_iris_penguins_seeds`` — same offline YAML → full-document
conversion, same static-id injection, no MongoDB required. The extra work here
is that these are child tabs, so the tab fields have to be carried across too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from bson import json_util

from depictio.models.models.dashboards import DashboardDataLite

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = REPO_ROOT / "depictio" / "projects" / "init" / "advanced_viz_showcase"

# Static identifiers, duplicated from db_init_reference_datasets.STATIC_IDS
# ["advanced_viz_showcase"] so this script has no settings/MongoDB dependency.
# `test_benchmark_seed_ids_match_static_ids` pins them to that table, so drift
# fails a test rather than producing seeds that 404 at render time.
PROJECT_ID = "646b0f3c1e4a2d7f8e5b8d00"
WORKFLOW_ID = "646b0f3c1e4a2d7f8e5b8d01"
# The showcase's main tab reuses the project id (see STATIC_IDS), and every
# benchmarking tab is a child of it.
PARENT_DASHBOARD_ID = PROJECT_ID
WF_TAG = "advanced_viz_demo"

DC_IDS: dict[str, str] = {
    "benchmark_demo": "646b0f3c1e4a2d7f8e5b8d52",
    "roc_curve_demo": "646b0f3c1e4a2d7f8e5b8d53",
}

# The per-DC block each component carries for the React viewer. Kept in step
# with project.yaml's data_collections entries.
DC_CONFIGS: dict[str, dict[str, Any]] = {
    "benchmark_demo": {
        "type": "table",
        "metatype": "Aggregate",
        "description": (
            "Synthetic per-caller benchmark summary (precision/recall/F1 + counts + CIs)"
        ),
        "data_collection_tag": "benchmark_demo",
        "dc_specific_properties": None,
    },
    "roc_curve_demo": {
        "type": "table",
        "metatype": "Aggregate",
        "description": (
            "Synthetic threshold sweep (3 tools × ~13 quality thresholds) for the PR/ROC curve"
        ),
        "data_collection_tag": "roc_curve_demo",
        "dc_specific_properties": None,
    },
}

DASHBOARDS: dict[str, str] = {
    # yaml stem -> static dashboard id
    "benchmark_pr": "646b0f3c1e4a2d7f8e5b8d48",
    "benchmark_roc": "646b0f3c1e4a2d7f8e5b8d49",
    "benchmark_confusion": "646b0f3c1e4a2d7f8e5b8d4a",
    "benchmark_ci": "646b0f3c1e4a2d7f8e5b8d4b",
}

ADMIN_USER_ID = "67658ba033c8b59ad489d7c7"
ADMIN_EMAIL = "admin@example.com"
# Fixed so regenerating an unchanged YAML produces an unchanged file — a
# wall-clock timestamp would churn all four seeds on every run.
LAST_SAVED_TS = "2026-07-29 00:00:00"


def _oid(value: str) -> dict[str, str]:
    return {"$oid": value}


def _enrich_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject wf_id / dc_id / dc_config into each component."""
    enriched: list[dict[str, Any]] = []
    for comp in components:
        new_comp = dict(comp)
        new_comp["wf_id"] = _oid(WORKFLOW_ID)
        new_comp["wf_tag"] = WF_TAG

        # Text components carry no DC binding; the React TextRenderer ignores
        # both fields, and the YAML still names a DC for authoring convenience.
        if new_comp.get("component_type") == "text":
            new_comp["dc_id"] = None
            new_comp["dc_config"] = {}
            enriched.append(new_comp)
            continue

        dc_tag = new_comp.get("data_collection_tag") or ""
        dc_id = DC_IDS.get(dc_tag)
        if dc_id is None:
            raise KeyError(
                f"Unknown data_collection_tag {dc_tag!r} on component "
                f"{new_comp.get('tag') or new_comp.get('index')!r}; "
                f"known tags: {sorted(DC_IDS)}"
            )
        new_comp["dc_id"] = _oid(dc_id)
        cfg = dict(DC_CONFIGS[dc_tag])
        cfg["_id"] = _oid(dc_id)
        new_comp["dc_config"] = cfg
        enriched.append(new_comp)
    return enriched


def build_seed_doc(stem: str) -> dict[str, Any]:
    """Full dashboard document for one benchmarking YAML."""
    raw = yaml.safe_load((PROJECT_DIR / "dashboards" / f"{stem}.yaml").read_text())
    lite = DashboardDataLite.model_validate(raw)
    full = lite.to_full()

    full["stored_metadata"] = _enrich_components(full["stored_metadata"])

    dashboard_id = DASHBOARDS[stem]
    full["_id"] = _oid(dashboard_id)
    full["dashboard_id"] = _oid(dashboard_id)
    full["project_id"] = _oid(PROJECT_ID)

    # Child-tab wiring. `parent_dashboard_tag` in the YAML is a title; the
    # document keys on the id, and get_child_tabs() finds nothing without it.
    full["is_main_tab"] = False
    full["parent_dashboard_id"] = _oid(PARENT_DASHBOARD_ID)
    full["tab_icon"] = raw.get("icon")
    full["tab_icon_color"] = raw.get("icon_color")

    full["is_public"] = True
    full["icon"] = raw.get("icon")
    full["icon_color"] = raw.get("icon_color")
    full["icon_variant"] = "filled"
    full["workflow_system"] = "python"
    full["notes_content"] = ""
    full["permissions"] = {
        "owners": [{"_id": _oid(ADMIN_USER_ID), "email": ADMIN_EMAIL, "is_admin": True}],
        "editors": [],
        "viewers": [],
    }
    full["last_saved_ts"] = LAST_SAVED_TS
    return full


def main() -> None:
    seeds_dir = PROJECT_DIR / ".db_seeds"
    seeds_dir.mkdir(parents=True, exist_ok=True)
    for stem in DASHBOARDS:
        doc = build_seed_doc(stem)
        path = seeds_dir / f"dashboard_{stem}.json"
        path.write_text(json_util.dumps(doc, indent=2) + "\n")
        print(
            f"Wrote {path.relative_to(REPO_ROOT)} "
            f"({len(doc.get('stored_metadata', []))} components)"
        )


if __name__ == "__main__":
    main()
