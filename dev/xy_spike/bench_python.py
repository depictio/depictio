"""Phase 3 for the xy spike (issue #945): Python-side build + serialize bench.

Compares, on identical frames loaded through the real Depictio read path
(`load_deltatable_lite`, local Delta tables):

  plotly_10k   create_figure_from_data(..., max_points=10_000) + fig.to_json()
               — what production ships today (settings.performance default)
  plotly_50k   same at max_points=50_000 (the issue's FIGURE_MAX_POINTS cap)
  plotly_full  same with sampling disabled (max_points=-1) — the "ship
               everything" counterfactual (100k/1M only; 10M is not attempted)
  xy_auto      xy.chart(scatter) + Figure.build_payload() and to_html() on the
               FULL frame — density tier auto-engages above ~200k pts
  xy_50k       xy on a seed-0 50k sample — like-for-like fidelity row
  xy_direct    xy with density=False on the full frame (direct tier: exact
               points + browser-local selection; 100k/1M only)

Each (engine, N) cell runs in a fresh subprocess: cold numbers are honest and
peak RSS (ru_maxrss) is per-cell. 1 cold + 3 warm repeats inside the cell.

The Mongo aggregation-version lookup is monkeypatched to None: this container
has no Mongo, and without the patch every load pays a 30 s server-selection
timeout that a real deployment (Mongo answering in ms) never sees.

Run:  venv/bin/python dev/xy_spike/bench_python.py            # orchestrate
      venv/bin/python dev/xy_spike/bench_python.py CELL <engine> <n>
"""

from __future__ import annotations

import csv
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

SPIKE = Path(__file__).parent
REPO = SPIKE.parent.parent
DATA = SPIKE / "data"
RESULTS = SPIKE / "results"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SPIKE))

import _env  # noqa: E402, F401

DC_IDS = {
    100_000: "64b000000000000000000100",
    1_000_000: "64b000000000000000001000",
    10_000_000: "64b000000000000000010000",
}
X, Y, SEL = "bill_length_mm", "bill_depth_mm", "individual_id"
REPEATS = 3

MATRIX: list[tuple[str, int]] = []
for _n in (100_000, 1_000_000, 10_000_000):
    MATRIX.append(("plotly_10k", _n))
    MATRIX.append(("plotly_50k", _n))
    MATRIX.append(("xy_auto", _n))
    MATRIX.append(("xy_50k", _n))
for _n in (100_000, 1_000_000):
    MATRIX.append(("plotly_full", _n))
    MATRIX.append(("xy_direct", _n))


def _load_frame(n: int):
    """Real read path, projected to the columns the figure references."""
    from bson import ObjectId

    # Spike-only: no Mongo in this container; production pays ~ms here.
    from depictio.api.v1 import deltatables_utils

    deltatables_utils._get_aggregation_version = lambda _dc: None

    path = DATA / f"points_{n}"
    init_data = {
        DC_IDS[n]: {
            "delta_location": str(path),
            "dc_type": "Table",
            "size_bytes": sum(f.stat().st_size for f in path.rglob("*") if f.is_file()),
        }
    }
    t0 = time.perf_counter()
    df = deltatables_utils.load_deltatable_lite(
        ObjectId("64b0000000000000000000aa"),
        DC_IDS[n],
        init_data=init_data,
        select_columns=[X, Y, SEL],
    )
    return df, time.perf_counter() - t0


def _run_plotly(df, max_points: int):
    from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

    stats: dict = {}
    t0 = time.perf_counter()
    fig = create_figure_from_data(
        df,
        "scatter",
        {"x": X, "y": Y},
        theme="light",
        selection_enabled=True,
        selection_column=SEL,
        max_points=max_points,
        render_stats=stats,
    )
    build_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    payload = fig.to_json()
    ser_s = time.perf_counter() - t0
    shipped = stats.get("displayed", df.height)
    return build_s, ser_s, len(payload.encode()), shipped


def _run_xy(df, mode: str):
    import xy

    xs = df[X].to_numpy()
    ys = df[Y].to_numpy()
    t0 = time.perf_counter()
    scatter = xy.scatter(xs, ys, density=False) if mode == "direct" else xy.scatter(xs, ys)
    ch = xy.chart(
        scatter,
        xy.interaction_config(hover=True, click=True, select=True, brush=True),
    )
    spec, blob = ch.figure().build_payload()
    build_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    html = ch.to_html()
    html_s = time.perf_counter() - t0
    payload_bytes = len(json.dumps(spec).encode()) + len(blob)
    return build_s, html_s, payload_bytes, len(html.encode()), len(xs)


def run_cell(engine: str, n: int) -> dict:
    df, load_s = _load_frame(n)
    if engine in ("plotly_50k", "xy_50k") or engine == "xy_50k":
        pass  # sampling handled below / inside builder
    if engine == "xy_50k" and df.height > 50_000:
        df = df.sample(n=50_000, seed=0)  # same sampler figure_builder uses

    rows = []
    for rep in range(REPEATS + 1):  # rep 0 = cold
        if engine == "plotly_10k":
            build_s, ser_s, payload, shipped = _run_plotly(df, 10_000)
            extra = {}
        elif engine == "plotly_50k":
            build_s, ser_s, payload, shipped = _run_plotly(df, 50_000)
            extra = {}
        elif engine == "plotly_full":
            build_s, ser_s, payload, shipped = _run_plotly(df, -1)
            extra = {}
        elif engine == "xy_auto":
            build_s, ser_s, payload, html_bytes, shipped = _run_xy(df, "auto")
            extra = {"html_bytes": html_bytes}
        elif engine == "xy_50k":
            build_s, ser_s, payload, html_bytes, shipped = _run_xy(df, "auto")
            extra = {"html_bytes": html_bytes}
        elif engine == "xy_direct":
            build_s, ser_s, payload, html_bytes, shipped = _run_xy(df, "direct")
            extra = {"html_bytes": html_bytes}
        else:
            raise SystemExit(f"unknown engine {engine}")
        rows.append((build_s, ser_s, payload, shipped, extra))

    cold = rows[0]
    warm = rows[1:]
    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {
        "engine": engine,
        "n_source": n,
        "points_serialized": cold[3],
        "load_s": round(load_s, 3),
        "build_cold_s": round(cold[0], 4),
        "build_warm_s": round(sum(r[0] for r in warm) / len(warm), 4),
        "serialize_warm_s": round(sum(r[1] for r in warm) / len(warm), 4),
        "payload_bytes": cold[2],
        "html_bytes": cold[4].get("html_bytes"),
        "peak_rss_mb": round(peak_rss_mb, 1),
    }


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "CELL":
        print("CELL_RESULT " + json.dumps(run_cell(sys.argv[2], int(sys.argv[3]))))
        return

    results = []
    for engine, n in MATRIX:
        proc = subprocess.run(
            [sys.executable, str(SPIKE / "bench_python.py"), "CELL", engine, str(n)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        line = next(
            (
                ln.removeprefix("CELL_RESULT ")
                for ln in proc.stdout.splitlines()
                if ln.startswith("CELL_RESULT ")
            ),
            None,
        )
        if line is None:
            print(f"FAILED {engine} n={n}\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
            results.append({"engine": engine, "n_source": n, "error": "failed"})
            continue
        row = json.loads(line)
        results.append(row)
        print(row)

    out = RESULTS / "python_timings.csv"
    fields = [
        "engine",
        "n_source",
        "points_serialized",
        "load_s",
        "build_cold_s",
        "build_warm_s",
        "serialize_warm_s",
        "payload_bytes",
        "html_bytes",
        "peak_rss_mb",
        "error",
    ]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
