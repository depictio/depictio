"""Phase 1 payload generator for the xy spike (issue #945).

Produces, under harness/:
  - standalone.js copied out of the installed xy wheel (proves the JS client is
    a separable asset, not something only to_html can emit)
  - spec_{N}.json + blob_{N}.bin from Figure.build_payload() for the mount test
  - ids_{N}.json — the selection-column values aligned to canonical row order
    (xy has no per-point customdata channel; identity is positional)
Under results/raw/:
  - xy_{N}.html full to_html() exports for the size-scaling measurement
Appends size rows to results/payload_sizes.csv.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import xy

SPIKE = Path(__file__).parent
HARNESS = SPIKE / "harness"
RAW = SPIKE / "results" / "raw"
RESULTS = SPIKE / "results"


def make_frame(n: int, seed: int = 0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {
        "x": rng.normal(size=n),
        "y": rng.normal(size=n),
        "individual_id": np.array([f"ind_{i}" for i in range(n)]),
    }


def build_chart(cols: dict[str, np.ndarray]) -> xy.Chart:
    return xy.chart(
        xy.scatter(cols["x"], cols["y"]),
        xy.interaction_config(hover=True, click=True, select=True, brush=True),
    )


def main() -> None:
    HARNESS.mkdir(exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    static_dir = Path(xy.__file__).parent / "static"
    shutil.copy(static_dir / "standalone.js", HARNESS / "standalone.js")
    print(f"copied standalone.js ({(HARNESS / 'standalone.js').stat().st_size} bytes)")

    sizes_csv = RESULTS / "payload_sizes.csv"
    rows = []
    for n in (20_000, 50_000, 100_000, 1_000_000):
        cols = make_frame(n)
        ch = build_chart(cols)
        fig = ch.figure()

        t0 = time.perf_counter()
        spec, blob = fig.build_payload()
        t_payload = time.perf_counter() - t0

        (HARNESS / f"spec_{n}.json").write_text(json.dumps(spec))
        (HARNESS / f"blob_{n}.bin").write_bytes(blob)
        # ids only needed for the mount/selection test at the two small sizes
        if n <= 100_000:
            (HARNESS / f"ids_{n}.json").write_text(json.dumps(list(cols["individual_id"])))

        t0 = time.perf_counter()
        html = ch.to_html()
        t_html = time.perf_counter() - t0
        out = RAW / f"xy_{n}.html"
        out.write_text(html)

        row = {
            "n": n,
            "spec_bytes": (HARNESS / f"spec_{n}.json").stat().st_size,
            "blob_bytes": len(blob),
            "html_bytes": out.stat().st_size,
            "build_payload_s": round(t_payload, 4),
            "to_html_s": round(t_html, 4),
        }
        rows.append(row)
        print(row)

    with sizes_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {sizes_csv}")


if __name__ == "__main__":
    sys.exit(main())
