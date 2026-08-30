"""Generate the iris + penguins ``.db_seeds`` dashboards from their lite YAML.

Run after editing the YAML files so the seed JSON that
``create_initial_dashboards`` loads matches what a user would get from
``depictio dashboard import``.

Covers every tab, not just the main one: iris ships a child ``Petal Analysis``
tab that used to be dumped from Mongo by hand and so drifted from its YAML.

Two properties this script deliberately guarantees:

* **Stable component indices.** The index is derived from the component's
  ``tag`` (a UUID5), not minted fresh, so regenerating an unchanged YAML
  produces a byte-identical seed. Random UUIDs made every run a whole-file
  diff, which hid the changes that mattered.
* **A faithful envelope.** ``is_public``, ``icon`` and ``workflow_system``
  are declared per project rather than hardcoded, because iris and penguins
  genuinely differ and a shared default silently flipped iris's.

Usage:
    venv/bin/python -m depictio.dev_scripts.generate_iris_penguins_seeds
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml
from bson import json_util

from depictio.models.models.dashboards import DashboardDataLite

REPO_ROOT = Path(__file__).resolve().parents[2]

# Static identifiers from db_init_reference_datasets.STATIC_IDS.
# Hardcoded here so this script has no MongoDB dependency.
#
# One entry per SEED FILE, i.e. per tab — a child tab is a dashboard document
# of its own, with its own `_id`, and only `parent_dashboard_id` ties it to the
# family. Keys match `db_init.dashboards_config` names so the two lists can be
# read side by side.
PROJECTS: dict[str, dict[str, Any]] = {
    "iris": {
        "yaml": "depictio/projects/init/iris/dashboards/overview.yaml",
        "seed": "depictio/projects/init/iris/.db_seeds/dashboard.json",
        "dashboard_id": "6824cb3b89d2b72169309737",
        "project_id": "646b0f3c1e4a2d7f8e5b8c9a",
        "workflow_id": "646b0f3c1e4a2d7f8e5b8c9b",
        # The envelope the shipped seed carries. Per project because iris and
        # penguins really do differ: iris is private, penguins is public. The
        # icon names the dataset rather than the product — a generic dashboard
        # glyph or the Depictio favicon said nothing about which project this
        # is, and disagreed with the icon the same dashboard shows in the tab
        # strip. A tab that declares its own `tab_icon` overrides this anyway.
        "envelope": {
            "icon": "mdi:flower-outline",
            "icon_color": "violet",
            "workflow_system": "none",
            "notes_content": "<p></p>",
            "is_public": False,
            "main_tab_name": "Overview",
        },
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
        "envelope": {
            "icon": "mdi:penguin",
            "icon_color": "orange",
            "workflow_system": "python",
            "notes_content": "",
            "is_public": True,
        },
    },
}

# Child tabs. They reuse their parent's project, workflow and DC tables — only
# the YAML, the seed path and the identity differ — so they are declared as a
# delta rather than a copy, which is what keeps a DC id from being fixed in one
# place and stale in the other.
CHILD_TABS: dict[str, dict[str, Any]] = {
    "iris_petal": {
        "parent": "iris",
        "yaml": "depictio/projects/init/iris/dashboards/petal_analysis.yaml",
        "seed": "depictio/projects/init/iris/.db_seeds/dashboard_petal.json",
        "dashboard_id": "6a75a191f5e6ff34386c8f0b",
    },
    "penguins_island_season": {
        "parent": "penguins",
        "yaml": "depictio/projects/init/penguins/dashboards/island_season.yaml",
        "seed": "depictio/projects/init/penguins/.db_seeds/dashboard_island_season.json",
        "dashboard_id": "6a75a191f5e6ff34386c8f0c",
    },
}

for _key, _delta in CHILD_TABS.items():
    _spec = dict(PROJECTS[_delta["parent"]])
    _spec.update({k: v for k, v in _delta.items() if k != "parent"})
    _spec["parent_dashboard_id"] = PROJECTS[_delta["parent"]]["dashboard_id"]
    # A child tab has no main-tab label of its own.
    _spec["envelope"] = {**_spec["envelope"], "main_tab_name": None}
    PROJECTS[_key] = _spec

ADMIN_USER_ID = "67658ba033c8b59ad489d7c7"
ADMIN_EMAIL = "admin@example.com"


# Namespace for deriving a component's index from its tag. Any fixed UUID does;
# this one is arbitrary and must never change, or every seed rewrites at once.
_INDEX_NAMESPACE = uuid.UUID("6b3f9c1e-4a2d-4f7e-9b5c-0d1a2b3c4d5e")


def _build_oid(oid: str) -> dict[str, str]:
    return {"$oid": oid}


def _stable_index(seed_key: str, comp: dict[str, Any], position: int) -> str:
    """A component index that survives regeneration.

    Derived from the YAML `tag`, which is the author-facing identity and the
    only thing about a component that is meant to be stable. Falling back to
    the position keeps an untagged component working, at the cost of moving
    when a sibling is inserted above it — which is the argument for tagging
    every component in a shipped dashboard.
    """
    tag = comp.get("tag") or f"__position_{position}"
    return str(uuid.uuid5(_INDEX_NAMESPACE, f"{seed_key}:{tag}"))


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


# `to_full` stamps every component with `datetime.now()`. In a checked-in seed
# that is pure churn: it rewrites every component on every run and buries the
# one line that actually changed. Pinned to the same instant as `last_saved_ts`.
FROZEN_TIMESTAMP = "2026-05-20 00:00:00"
FROZEN_LAST_UPDATED = "2026-05-20T00:00:00"


def _build_seed_doc(project_key: str) -> dict[str, Any]:
    spec = PROJECTS[project_key]
    yaml_path = REPO_ROOT / spec["yaml"]
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)

    # Pin each component's index before the conversion: `to_full` mints a fresh
    # UUID only when one is absent, so supplying it here is what makes an
    # unchanged YAML regenerate byte-identically.
    for position, comp in enumerate(raw.get("components") or []):
        if isinstance(comp, dict):
            comp.setdefault("index", _stable_index(project_key, comp, position))

    lite = DashboardDataLite.model_validate(raw)
    full = lite.to_full()

    full["stored_metadata"] = _enrich_components(
        full["stored_metadata"],
        workflow_id=spec["workflow_id"],
        dc_ids=spec["dc_ids"],
        dc_configs=spec["dc_configs"],
        wf_tag=spec["wf_tag"],
    )

    envelope = spec["envelope"]
    full["_id"] = _build_oid(spec["dashboard_id"])
    full["dashboard_id"] = _build_oid(spec["dashboard_id"])
    full["project_id"] = _build_oid(spec["project_id"])
    full["is_public"] = envelope["is_public"]
    # A tab's own icon wins over the project envelope. The envelope is one
    # value for a whole project, so a dashboard that names itself in the tab
    # strip used to wear a different icon in its own header — a penguin in the
    # strip, the product favicon above it. The YAML is the single source of a
    # tab's identity; the envelope is only the fallback for one that names none.
    full["icon"] = full.get("tab_icon") or envelope["icon"]
    full["icon_color"] = full.get("tab_icon_color") or envelope["icon_color"]
    full["icon_variant"] = "filled"
    full["workflow_system"] = envelope["workflow_system"]
    full["notes_content"] = envelope["notes_content"]
    if "main_tab_name" in envelope:
        full["main_tab_name"] = envelope["main_tab_name"]
    # Only a child tab carries a parent. `_resolve_tab_family` matches on this
    # field, so a wrong or missing value leaves the tab a family of one.
    if spec.get("parent_dashboard_id"):
        full["parent_dashboard_id"] = _build_oid(spec["parent_dashboard_id"])
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
    full["last_saved_ts"] = FROZEN_TIMESTAMP
    for comp in full["stored_metadata"]:
        comp["last_updated"] = FROZEN_LAST_UPDATED

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
