"""Phase 2 for the xy spike (issue #945): benchmark datasets + real read path.

Generates Depictio-shaped synthetic frames (reusing benchmark/datagen.py's
canonical `_make_batch` schema: `individual_id` join/selection key + penguin
measures) at 100k / 1M / 10M rows, writes them as local Delta tables, then
loads each back through the real production read path —
`load_deltatable_lite(..., init_data=...)` with `DEPICTIO_USE_LOCAL_FILES=true`
— which is the same function the figure Celery task calls (celery_tasks.py).

Also reports the row count of the largest real committed dataset
(viralrecon multiqc.parquet) for the real-data row of the results table.

Run:  DEPICTIO_USE_LOCAL_FILES=true venv/bin/python dev/xy_spike/gen_data.py
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

SPIKE = Path(__file__).parent
REPO = SPIKE.parent.parent
DATA = SPIKE / "data"
RESULTS = SPIKE / "results"

sys.path.insert(0, str(REPO))  # benchmark/ is not an installed package

import _env  # noqa: E402, F401  (must precede any depictio import)

from benchmark.datagen import _make_batch  # noqa: E402

SIZES = (100_000, 1_000_000, 10_000_000)
CHUNK = 1_000_000
# Stable fake ObjectIds, one per dataset size (Depictio DC ids are ObjectIds).
DC_IDS = {
    100_000: "64b000000000000000000100",
    1_000_000: "64b000000000000000001000",
    10_000_000: "64b000000000000000010000",
}


def generate(n: int) -> Path:
    path = DATA / f"points_{n}"
    if (path / "_delta_log").exists():
        print(f"points_{n}: already generated")
        return path
    t0 = time.perf_counter()
    written = 0
    chunk_idx = 0
    while written < n:
        take = min(CHUNK, n - written)
        ids = [f"IND_{i:08d}" for i in range(written, written + take)]
        df = _make_batch(ids, seed=chunk_idx)
        df.write_delta(str(path), mode="append" if written else "overwrite")
        written += take
        chunk_idx += 1
    print(f"points_{n}: wrote {written} rows in {time.perf_counter() - t0:.1f}s")
    return path


def dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> None:
    DATA.mkdir(exist_ok=True)
    for n in SIZES:
        generate(n)

    # Real production read path (needs depictio importable + settings defaults;
    # no Mongo/MinIO required thanks to init_data + DEPICTIO_USE_LOCAL_FILES).
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    rows = []
    wf_id = ObjectId("64b0000000000000000000aa")
    for n in SIZES:
        path = DATA / f"points_{n}"
        dc_id = DC_IDS[n]
        init_data = {
            dc_id: {
                "delta_location": str(path),
                "dc_type": "Table",
                "size_bytes": dir_bytes(path),
            }
        }
        t0 = time.perf_counter()
        df = load_deltatable_lite(wf_id, dc_id, init_data=init_data)
        full_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        df_proj = load_deltatable_lite(
            wf_id,
            dc_id,
            init_data=init_data,
            select_columns=["bill_length_mm", "bill_depth_mm", "individual_id"],
        )
        proj_s = time.perf_counter() - t0

        row = {
            "n": n,
            "loaded_rows": df.height,
            "cols": len(df.columns),
            "delta_bytes": init_data[dc_id]["size_bytes"],
            "full_load_s": round(full_s, 3),
            "projected_load_s": round(proj_s, 3),
            "projected_cols": len(df_proj.columns),
        }
        rows.append(row)
        print(row)
        assert df.height == n, f"expected {n} rows, got {df.height}"

    # Largest real committed dataset
    import polars as pl

    viral = (
        REPO
        / "depictio/projects/nf-core/viralrecon/3.0.0/run_1/multiqc/multiqc_data/multiqc.parquet"
    )
    vdf = pl.scan_parquet(str(viral))
    n_viral = vdf.select(pl.len()).collect().item()
    print(f"viralrecon multiqc.parquet: {n_viral} rows, {viral.stat().st_size / 2**20:.1f} MB")
    rows.append(
        {
            "n": n_viral,
            "loaded_rows": n_viral,
            "cols": len(vdf.collect_schema().names()),
            "delta_bytes": viral.stat().st_size,
            "full_load_s": None,
            "projected_load_s": None,
            "projected_cols": None,
        }
    )

    out = RESULTS / "dataset_loads.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
