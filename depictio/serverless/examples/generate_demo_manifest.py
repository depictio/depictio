"""Regenerate the committed demo manifests (penguins, protein, compute, map).

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
PROTEIN_SPEC = EXAMPLES / "protein.yaml"
PROTEIN_OUT = OUT.parent / "protein.json"
COMPUTE_SPEC = EXAMPLES / "compute.yaml"
COMPUTE_OUT = OUT.parent / "compute.json"
MAP_SPEC = EXAMPLES / "map.yaml"
MAP_OUT = OUT.parent / "map.json"
MAP_DATA = REPO_ROOT / "depictio" / "projects" / "test" / "map_demo" / "sampling_locations.csv"
SHOWCASE_DATA = REPO_ROOT / "depictio" / "projects" / "init" / "advanced_viz_showcase" / "data"

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


def _write(result, out: Path) -> None:
    manifest = json_safe(result.manifest.model_dump(mode="json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    tiers = [f"{cid}:{t['tier']}" for cid, t in sorted(manifest["tiers"].items())]
    print(f"wrote {out.relative_to(REPO_ROOT)} ({out.stat().st_size / 1024:.0f} KiB)")
    print("tiers:", ", ".join(tiers))


def protein_data_dir(root: Path) -> Path:
    """The protein example's data dir: the residue table + two indexed_file dirs."""
    wf = root / "protein_demo"
    (wf / "structures").mkdir(parents=True)
    (wf / "pae").mkdir()
    pl.read_csv(SHOWCASE_DATA / "protein_residues_demo.tsv", separator="\t").write_parquet(
        wf / "protein_residues_demo.parquet"
    )
    (wf / "structures" / "demo_protein.pdb").write_bytes(
        (SHOWCASE_DATA / "demo_protein.pdb").read_bytes()
    )
    (wf / "pae" / "demo_protein.pae.tsv").write_bytes(
        (SHOWCASE_DATA / "demo_protein.pae.tsv").read_bytes()
    )
    return root


def compute_data_dir(root: Path) -> Path:
    """The compute example's data dir: two showcase tables as Parquet."""
    wf = root / "compute_demo"
    wf.mkdir(parents=True)
    for tag in ("group_compare_demo", "contact_map_demo"):
        pl.read_csv(SHOWCASE_DATA / f"{tag}.tsv", separator="\t").write_parquet(
            wf / f"{tag}.parquet"
        )
    return root


def map_data_dir(root: Path) -> Path:
    """The map example's data dir: the map demo's sampling sites as Parquet."""
    wf = root / "map_demo"
    wf.mkdir(parents=True)
    pl.read_csv(MAP_DATA).write_parquet(wf / "sampling_locations.parquet")
    return root


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dc_dir = Path(tmp) / WF_TAG
        dc_dir.mkdir(parents=True)
        penguins_frame().write_parquet(dc_dir / f"{DC_TAG}.parquet")
        island_regions_frame().write_parquet(dc_dir / f"{LINKED_DC_TAG}.parquet")
        _write(build_manifest(load_spec(SPEC), Path(tmp), python_runtime="off"), OUT)
    with tempfile.TemporaryDirectory() as tmp:
        result = build_manifest(
            load_spec(PROTEIN_SPEC), protein_data_dir(Path(tmp)), python_runtime="off"
        )
        if not result.manifest.addons:
            raise SystemExit(
                "the 3dmol add-on is not built: run `pnpm run build:static` in depictio/viewer "
                "first, so the protein manifest records it"
            )
        _write(result, PROTEIN_OUT)
    with tempfile.TemporaryDirectory() as tmp:
        _write(
            build_manifest(
                load_spec(COMPUTE_SPEC), compute_data_dir(Path(tmp)), python_runtime="off"
            ),
            COMPUTE_OUT,
        )
    with tempfile.TemporaryDirectory() as tmp:
        _write(
            build_manifest(load_spec(MAP_SPEC), map_data_dir(Path(tmp)), python_runtime="off"),
            MAP_OUT,
        )


if __name__ == "__main__":
    main()
