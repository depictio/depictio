"""Invariants on bundled reference-dataset seed dashboards.

Every `dc_id` baked into a `.db_seeds/dashboard_*.json` must resolve to a
static ID declared in
`depictio.api.v1.db_init_reference_datasets.STATIC_IDS[project][data_collections]`
— otherwise the dashboard 404s at render time on every fresh deploy (the
auto-generated IDs from the source-of-truth instance don't reproduce).

This test fired because viralrecon's seeds shipped with 46 auto-generated
ObjectIds (prefix `6a0e2739...`) instead of the static `746b0f...` IDs. See
`depictio/projects/nf-core/viralrecon/3.0.0/remap_seeds_to_static_ids.py`
for the one-shot remap.

The same invariant covers ampliseq (already compliant) and any future
reference project bundled under `depictio/projects/nf-core/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from depictio.api.v1.db_init_reference_datasets import (
    STATIC_IDS,
    ReferenceDatasetRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _seed_files() -> list[tuple[str, Path]]:
    """Discover the `.db_seeds/dashboard_*.json` that init actually loads.

    Only walks the directory `ReferenceDatasetRegistry.DATASET_PATHS[project]`
    points at — legacy template versions sitting next to the active one
    (e.g. ampliseq/2.14.0/) are intentionally skipped because db_init never
    reads them.
    """
    out: list[tuple[str, Path]] = []
    for project_key, rel_path in ReferenceDatasetRegistry.DATASET_PATHS.items():
        if project_key not in STATIC_IDS:
            continue
        seeds_dir = REPO_ROOT / "depictio" / "projects" / rel_path / ".db_seeds"
        if not seeds_dir.is_dir():
            continue
        for seed in sorted(seeds_dir.glob("dashboard_*.json")):
            out.append((project_key, seed))
    return out


@pytest.mark.parametrize(
    "project_key,seed_path",
    _seed_files(),
    ids=lambda v: v.name if isinstance(v, Path) else str(v),
)
def test_seed_dc_ids_are_static(project_key: str, seed_path: Path) -> None:
    """Every dc_id in a seed dashboard must be a known static DC ID for that project."""
    dc_tag_to_id = STATIC_IDS[project_key].get("data_collections", {})
    valid_ids = set(dc_tag_to_id.values())

    doc = json.loads(seed_path.read_text())
    offenders: list[str] = []

    for component in doc.get("stored_metadata", []) or []:
        dc_id = component.get("dc_id")
        if dc_id is None:
            # Text tiles + similar UI-only components don't bind to a DC.
            continue

        # dc_id can serialise as either a bare string or `{"$oid": "..."}`.
        oid = dc_id.get("$oid") if isinstance(dc_id, dict) else str(dc_id)
        if oid not in valid_ids:
            tag = component.get("data_collection_tag") or "<no tag>"
            label = component.get("title") or component.get("index") or "<no label>"
            offenders.append(f"dc_id={oid} tag={tag} component={label!r}")

    assert not offenders, (
        f"{seed_path.relative_to(REPO_ROOT)} references DC IDs that aren't in "
        f"STATIC_IDS[{project_key!r}].data_collections — fresh deploys will 404 "
        f"on these components.\n  " + "\n  ".join(offenders)
    )
