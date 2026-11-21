"""Regenerate fixtures/contact-map-expected.json (contactMapWindow parity).

Runs the server's own ``contact_map_window`` (depictio/api/v1/services/
contact_map.py, the post-load half of the ``compute_contact_map`` task) over a
slice of the advanced-viz showcase's contact table, for a set of requests, and
writes the inputs and the answers for ``test/contactMap.test.ts``:

    DEPICTIO_CONTEXT=cli uv run --extra dev python \\
        packages/depictio-static-core/scripts/generate_contact_map_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from depictio.api.v1.services.contact_map import contact_map_window

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "depictio/projects/init/advanced_viz_showcase/data/contact_map_demo.tsv"
OUT = ROOT / "packages/depictio-static-core/fixtures/contact-map-expected.json"

BASE = {
    "chrom1_col": "chrom",
    "start1_col": "start",
    "end1_col": "end",
    "chrom2_col": "chrom2",
    "start2_col": "start2",
    "end2_col": "end2",
    "count_col": "count",
    "resolution_col": "resolution",
}

CASES = [
    ("whole chromosome", {"chrom": "chr7"}, None),
    ("no chromosome", {}, None),
    (
        "window, picked level",
        {"chrom": "chr7", "start": 26_650_000, "end": 26_900_000, "pixels": 600},
        None,
    ),
    (
        "window, pinned level",
        {"chrom": "chr7", "start": 26_650_000, "end": 26_900_000, "resolution": 20_000},
        None,
    ),
    (
        "window without end columns",
        {
            "chrom": "chr7",
            "start": 26_655_000,
            "end": 26_800_000,
            "end1_col": None,
            "end2_col": None,
        },
        None,
    ),
    (
        "tight cell budget",
        {"chrom": "chr7", "start": 26_600_000, "end": 26_900_000, "max_cells": 50},
        None,
    ),
    ("whole chromosome, tight budget", {"chrom": "chr7", "max_cells": 100}, None),
    (
        "masked by a filter",
        {"chrom": "chr7", "start": 26_600_000, "end": 26_800_000},
        "count_gt_40",
    ),
    # A flat DC holds one level (no resolution column): the 10 kb rows. Polars'
    # sort is not stable, so a frame with tied (chrom, start1, start2) keys —
    # several levels mixed — has no single expected order; a real flat table
    # has none.
    ("flat table, truncated", {"chrom": "chr7", "max_cells": 100, "__flat__": True}, "res_10k"),
    (
        "a level that does not exist",
        {"chrom": "chr7", "start": 26_600_000, "end": 26_700_000, "resolution": 12345},
        None,
    ),
]


def main() -> None:
    df = pl.read_csv(SRC, separator="\t")
    # A slice keeps the fixture small while spanning every resolution.
    df = (
        df.filter(pl.col("chrom").is_in(["chr7", "chr8"]))
        .filter(pl.col("start") < 26_900_000)
        .filter(pl.col("start2") < 26_900_000)
    )
    masks = {
        "count_gt_40": [1 if c > 40 else 0 for c in df["count"].to_list()],
        "res_10k": [1 if r == 10_000 else 0 for r in df["resolution"].to_list()],
    }
    cases = []
    for name, extra, mask_name in CASES:
        flat = bool(extra.pop("__flat__", False))
        payload = {**BASE, **extra}
        frame = df if mask_name is None else df.filter(pl.Series(masks[mask_name]) == 1)
        resolution_col = None if flat else "resolution"
        if flat:
            frame = frame.drop("resolution")
        out = contact_map_window(frame, payload, resolution_col)
        out.pop("compute_ms")
        cases.append(
            {
                "name": name,
                "request": payload,
                "resolution_col": resolution_col,
                "mask": mask_name,
                "expected": out,
            }
        )
    OUT.write_text(
        json.dumps(
            {"columns": {c: df[c].to_list() for c in df.columns}, "masks": masks, "cases": cases},
            separators=(",", ":"),
        )
        + "\n"
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KiB, {df.height} rows)")


if __name__ == "__main__":
    main()
