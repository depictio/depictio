"""Remap auto-generated DC IDs in ampliseq seed dashboards to static IDs.

When `generate_seeds.sh` exports the dashboards via `python -m depictio.cli run`,
the CLI ingest path creates DCs with fresh auto-generated ObjectIds — not the
static IDs from `db_init_reference_datasets.STATIC_IDS`. The reference-init
flow on a fresh deploy uses static IDs, so dashboards baked with auto-IDs
404 at render time.

This script walks every `.db_seeds/dashboard_*.json`, looks up each component's
`data_collection_tag`, and rewrites `dc_id` / `dc_config._id` with the static
ID from STATIC_IDS. Text components (no DC backing) get `dc_id: null`.

It also pins each seed's own identity — `_id`, `dashboard_id`, `project_id` and
`parent_dashboard_id` — for the same reason: the dashboard import ignores the
`dashboard_id` written in the YAML and mints a fresh ObjectId for any tab it
cannot match by title, so without this a re-export quietly renumbers the family.

Run via (neither `nf-core` nor `2.18.0` is a valid module path component, so
invoke by file):
    python depictio/projects/nf-core/ampliseq/2.18.0/remap_seeds_to_static_ids.py

Idempotent — running on already-static seeds is a no-op.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Import STATIC_IDS directly to keep this script self-validating.
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from depictio.api.v1.db_init_reference_datasets import STATIC_IDS  # noqa: E402

PROJECT_KEY = "ampliseq"
SEEDS_DIR = Path(__file__).resolve().parent / ".db_seeds"


def _tag_to_static_id() -> dict[str, str]:
    return STATIC_IDS[PROJECT_KEY]["data_collections"]


def _is_oid_field(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {"$oid"}


def _remap_dc_id(component: dict[str, Any], dc_tag_to_id: dict[str, str]) -> bool:
    """Mutate component in place. Return True iff anything changed."""
    tag = component.get("data_collection_tag")
    comp_type = component.get("component_type")
    changed = False

    if comp_type == "text" or not tag:
        # Text tiles aren't bound to a DC; null the field.
        if component.get("dc_id") is not None:
            component["dc_id"] = None
            changed = True
        if isinstance(component.get("dc_config"), dict) and component["dc_config"].get("_id"):
            component["dc_config"]["_id"] = None
            changed = True
        return changed

    static_id = dc_tag_to_id.get(tag)
    if not static_id:
        print(
            f"  ⚠️  tag '{tag}' has no STATIC_IDS entry — left untouched "
            f"(component: {component.get('title') or component.get('index')})"
        )
        return False

    current = component.get("dc_id")
    current_oid = current.get("$oid") if _is_oid_field(current) else current
    if current_oid != static_id:
        component["dc_id"] = {"$oid": static_id}
        changed = True

    dc_config = component.get("dc_config")
    if isinstance(dc_config, dict):
        current_cfg = dc_config.get("_id")
        current_cfg_oid = current_cfg.get("$oid") if _is_oid_field(current_cfg) else current_cfg
        if current_cfg_oid != static_id:
            dc_config["_id"] = {"$oid": static_id}
            changed = True

    return changed


# --- dashboard identity ------------------------------------------------------
# `_import_multi_tab_dashboard` does NOT honour the `dashboard_id` written in the
# YAML: it reuses the id of an existing dashboard found by (title, project) and
# mints a fresh ObjectId otherwise. The ids in the shipped seeds therefore
# survive only by accident — until a tab is renamed, or a new tab is added, at
# which point `db_init.dashboards_config`, `STATIC_IDS` and the hard-coded ids
# in the e2e specs all point at documents that no longer exist. Pinning them
# here is what makes the export reproducible.
SEED_TO_DASHBOARD_KEY: dict[str, str] = {
    "dashboard_multiqc.json": "ampliseq_multiqc",
    "dashboard_alpha_diversity.json": "ampliseq_alpha_diversity",
    "dashboard_community.json": "ampliseq_community",
    "dashboard_differential.json": "ampliseq_differential",
    "dashboard_ordination.json": "ampliseq_ordination",
    "dashboard_phylogeny.json": "ampliseq_phylogeny",
    # From the reference-only demo layer (build_reference_dashboard.py), not
    # from the nf-core template.
    "dashboard_sampling_campaign.json": "ampliseq_sampling_campaign",
    "dashboard_environment.json": "ampliseq_environment",
}
MAIN_SEED = "dashboard_multiqc.json"


def _pin_dashboard_ids(path: Path, doc: dict[str, Any]) -> bool:
    """Force one seed's identity fields to the static ids. True iff changed."""
    dashboards = STATIC_IDS[PROJECT_KEY].get("dashboards", {})
    key = SEED_TO_DASHBOARD_KEY.get(path.name)
    if key is None:
        print(f"  ⚠️  {path.name} has no SEED_TO_DASHBOARD_KEY entry — ids left untouched")
        return False
    static_id = dashboards.get(key)
    if not static_id:
        print(f"  ⚠️  '{key}' has no STATIC_IDS['{PROJECT_KEY}']['dashboards'] entry")
        return False

    main_id = dashboards[SEED_TO_DASHBOARD_KEY[MAIN_SEED]]
    is_main = path.name == MAIN_SEED
    wanted: dict[str, Any] = {
        "_id": {"$oid": static_id},
        "dashboard_id": {"$oid": static_id},
        "project_id": {"$oid": STATIC_IDS[PROJECT_KEY]["project"]},
        # A child tab points at the main tab; the main tab points at nothing.
        # Getting this wrong orphans the whole family: `_resolve_tab_family`
        # matches on parent_dashboard_id, so a parent id no document carries
        # leaves every tab a family of one.
        "parent_dashboard_id": None if is_main else {"$oid": main_id},
    }
    changed = False
    for field, value in wanted.items():
        if doc.get(field) != value:
            doc[field] = value
            changed = True
    return changed


# --- reproducibility ---------------------------------------------------------
# A re-export carries the ingest's wall clock: `version` climbs on every import
# and every component gets a fresh `last_updated`, so an unchanged dashboard
# still rewrites its whole seed. Pinning them makes `git diff` on a regenerated
# seed show only what actually changed.
SEED_VERSION = 1
FROZEN_LAST_SAVED_TS = "2026-08-29 00:00:00"
FROZEN_LAST_UPDATED = "2026-08-29T00:00:00.000000"


def _freeze_timestamps(doc: dict[str, Any]) -> bool:
    """Pin version and timestamps. True iff anything changed."""
    changed = False
    if doc.get("version") != SEED_VERSION:
        doc["version"] = SEED_VERSION
        changed = True
    if doc.get("last_saved_ts") != FROZEN_LAST_SAVED_TS:
        # Must stay a string: `get_dashboard` 500s on a BSON date here.
        doc["last_saved_ts"] = FROZEN_LAST_SAVED_TS
        changed = True
    for sm in doc.get("stored_metadata", []) or []:
        if sm.get("last_updated") != FROZEN_LAST_UPDATED:
            sm["last_updated"] = FROZEN_LAST_UPDATED
            changed = True
    return changed


def remap_file(path: Path, dc_tag_to_id: dict[str, str]) -> int:
    """Remap one dashboard JSON. Return number of components changed."""
    doc = json.loads(path.read_text())
    n = 0
    for sm in doc.get("stored_metadata", []) or []:
        if _remap_dc_id(sm, dc_tag_to_id):
            n += 1
    ids_pinned = _pin_dashboard_ids(path, doc)
    frozen = _freeze_timestamps(doc)
    if n or ids_pinned or frozen:
        # Preserve original 2-space indentation used by the rest of the seeds.
        path.write_text(json.dumps(doc, indent=2) + "\n")
    return n


def main() -> int:
    if not SEEDS_DIR.is_dir():
        print(f"ERROR: seeds directory not found: {SEEDS_DIR}", file=sys.stderr)
        return 1

    dc_tag_to_id = _tag_to_static_id()
    total = 0
    for path in sorted(SEEDS_DIR.glob("dashboard_*.json")):
        n = remap_file(path, dc_tag_to_id)
        print(f"{path.name}: {n} component(s) remapped")
        total += n
    print(f"\nTotal: {total} component(s) updated across {PROJECT_KEY} dashboards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
