"""Remap auto-generated DC IDs in viralrecon seed dashboards to static IDs.

When `generate_seeds.sh` exports the dashboards via `python -m depictio.cli run`,
the CLI ingest path creates DCs with fresh auto-generated ObjectIds — not the
static IDs from `db_init_reference_datasets.STATIC_IDS`. The reference-init
flow on a fresh deploy uses static IDs, so dashboards baked with auto-IDs
404 at render time.

This script walks every `.db_seeds/dashboard_*.json`, looks up each component's
`data_collection_tag`, and rewrites `dc_id` / `dc_config._id` with the static
ID from STATIC_IDS. Text components (no DC backing) get `dc_id: null`.

Run via:
    python -m depictio.projects.nf-core.viralrecon.3_0_0.remap_seeds_to_static_ids

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

PROJECT_KEY = "viralrecon"
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
        # Text tiles aren't bound to a DC; null the field to match ampliseq.
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


def remap_file(path: Path, dc_tag_to_id: dict[str, str]) -> int:
    """Remap one dashboard JSON. Return number of components changed."""
    doc = json.loads(path.read_text())
    n = 0
    for sm in doc.get("stored_metadata", []) or []:
        if _remap_dc_id(sm, dc_tag_to_id):
            n += 1
    if n:
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
