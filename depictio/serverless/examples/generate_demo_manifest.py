"""Regenerate the committed penguins demo manifest.

The per-phase demo site (depictio/viewer/scripts/build-demo.mjs) is built by
JS-only CI jobs, so the producer-B manifest for the penguins demo is committed
at depictio/viewer/demo/manifests/penguins.json rather than rebuilt on every
run. Regenerate it after changing the example spec, the producer, or the
companions/codebook logic:

    DEPICTIO_CONTEXT=cli ./venv/bin/python \
        depictio/serverless/examples/generate_demo_manifest.py

(The cli context skips the server Settings' secret validation, which an
offline build has no use for.)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import polars as pl

from depictio.serverless.inject import json_safe
from depictio.serverless.producer_b import build_manifest, load_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "depictio" / "serverless" / "examples"
SPEC = EXAMPLES / "penguins.yaml"
ISLAND_REGIONS_CSV = EXAMPLES / "data" / "island_regions.csv"
PENGUINS_DATA = REPO_ROOT / "depictio" / "projects" / "init" / "penguins" / "data"
OUT = REPO_ROOT / "depictio" / "viewer" / "demo" / "manifests" / "penguins.json"

WF_TAG = "penguin_species_analysis"
DC_TAG = "joined_penguins_complete"
LINKED_DC_TAG = "island_regions"


def penguins_frame() -> pl.DataFrame:
    """Join the repo's penguins CSV runs into the flat example table
    (same derivation as tests/unit/serverless/test_producer_b.py)."""
    runs = sorted(p for p in PENGUINS_DATA.iterdir() if p.is_dir())
    parts = []
    for run in runs:
        demo = pl.read_csv(run / "demographic_data.csv")
        phys = pl.read_csv(run / "physical_features.csv")
        parts.append(demo.join(phys, on="individual_id", how="inner"))
    return pl.concat(parts)


def island_regions_frame() -> pl.DataFrame:
    """The linked lookup DC: island → region, straight from the example CSV."""
    return pl.read_csv(ISLAND_REGIONS_CSV)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dc_dir = Path(tmp) / WF_TAG
        dc_dir.mkdir(parents=True)
        penguins_frame().write_parquet(dc_dir / f"{DC_TAG}.parquet")
        island_regions_frame().write_parquet(dc_dir / f"{LINKED_DC_TAG}.parquet")
        result = build_manifest(load_spec(SPEC), Path(tmp))
    manifest = json_safe(result.manifest.model_dump(mode="json"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    tiers = [f"{cid}:{t['tier']}" for cid, t in sorted(manifest["tiers"].items())]
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size / 1024:.0f} KiB)")
    print("tiers:", ", ".join(tiers))


if __name__ == "__main__":
    main()
