"""Aggregate ``results.jsonl`` into ``results.csv`` + ``REPORT.md`` + PNG plots.

Reads the JSONL emitted by :mod:`benchmark.runner`, writes a flat CSV of render
rows, a markdown summary with P50/P95 tables, and (if matplotlib is available)
scaling plots: latency vs DC size (inline vs offloaded — the offload crossover),
latency vs #components, latency vs #connected DCs, and per-visu-type comparison.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from benchmark.metrics import summarize

_RENDER_FIELDS = [
    "cell_slug",
    "size",
    "size_bytes",
    "n_components",
    "n_dcs",
    "connect",
    "component_type",
    "component_index",
    "visu",
    "dc_tag",
    "server_mode",
    "wall_ms",
    "celery_path",
    "http_status",
    "ok",
    "filtered",
    "task_duration_ms",
    "load_ms",
    "build_ms",
    "error",
]

_SIZE_ORDER = {"10mb": 0, "100mb": 1, "1gb": 2, "5gb": 3, "10gb": 4}


def _load(results_path: Path) -> tuple[list[dict], list[dict]]:
    renders: list[dict] = []
    ingests: list[dict] = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind") == "render":
            renders.append(row)
        elif row.get("kind") == "ingest":
            ingests.append(row)
    return renders, ingests


def _write_csv(renders: list[dict], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_RENDER_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in renders:
            w.writerow(r)


def _md_table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _group_summary(renders: list[dict], keys: tuple[str, ...]) -> list[tuple[tuple, dict]]:
    buckets: dict[tuple, list[float]] = defaultdict(list)
    for r in renders:
        if not r.get("ok"):
            continue
        buckets[tuple(r.get(k) for k in keys)].append(float(r.get("wall_ms") or 0.0))
    out = [(k, summarize(v)) for k, v in buckets.items()]
    out.sort(
        key=lambda kv: [_SIZE_ORDER.get(str(p), p) if isinstance(p, str) else p for p in kv[0]]
    )
    return out


def _plots(renders: list[dict], out_dir: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    made: list[str] = []
    ok = [r for r in renders if r.get("ok")]

    def _line_plot(name: str, xkey: str, xorder, title: str, xlabel: str) -> None:
        by_path: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        for r in ok:
            by_path[r.get("celery_path", "n/a")][r.get(xkey)].append(float(r["wall_ms"]))
        if not by_path:
            return
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for path, series in by_path.items():
            xs = sorted(series.keys(), key=lambda v: xorder.get(str(v), v) if xorder else v)
            ys = [summarize(series[x])["p50"] for x in xs]
            ax.plot([str(x) for x in xs], ys, marker="o", label=f"{path}")
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("render p50 (ms)")
        ax.legend()
        fig.tight_layout()
        path_out = out_dir / name
        fig.savefig(path_out, dpi=110)
        plt.close(fig)
        made.append(name)

    _line_plot("latency_vs_size.png", "size", _SIZE_ORDER, "Render latency vs DC size", "DC size")
    _line_plot(
        "latency_vs_components.png",
        "n_components",
        None,
        "Render latency vs #components",
        "#components",
    )
    _line_plot("latency_vs_dcs.png", "n_dcs", None, "Render latency vs #connected DCs", "#DCs")
    return made


def build_report(output_root: str | Path) -> Path:
    """Produce results.csv, REPORT.md and plots under ``output_root``."""
    output_root = Path(output_root)
    results_path = output_root / "results.jsonl"
    if not results_path.exists():
        raise FileNotFoundError(f"No results at {results_path} — run the matrix first.")

    renders, ingests = _load(results_path)
    _write_csv(renders, output_root / "results.csv")
    plot_names = _plots(renders, output_root)

    n_ok = sum(1 for r in renders if r.get("ok"))
    n_fail = len(renders) - n_ok

    lines: list[str] = ["# Depictio Benchmark Report", ""]
    lines.append(
        f"Rendered components: **{len(renders)}** "
        f"(ok: {n_ok}, failed: {n_fail}); ingests: **{len(ingests)}**."
    )
    lines.append("")

    # By size × celery path (the offload crossover)
    lines += ["## Render latency by DC size and Celery path", ""]
    rows = [
        [
            k[0],
            k[1],
            s["n"],
            f"{s['mean']:.0f}",
            f"{s['p50']:.0f}",
            f"{s['p95']:.0f}",
            f"{s['max']:.0f}",
        ]
        for k, s in _group_summary(renders, ("size", "celery_path"))
    ]
    lines.append(_md_table(["size", "celery_path", "n", "mean", "p50", "p95", "max"], rows))
    lines.append("")

    # By component type
    lines += ["## Render latency by component type", ""]
    rows = [
        [k[0], s["n"], f"{s['mean']:.0f}", f"{s['p50']:.0f}", f"{s['p95']:.0f}"]
        for k, s in _group_summary(renders, ("component_type",))
    ]
    lines.append(_md_table(["component_type", "n", "mean", "p50", "p95"], rows))
    lines.append("")

    # By connect mode × #DCs
    lines += ["## Render latency by connect mode and #DCs", ""]
    rows = [
        [k[0], k[1], s["n"], f"{s['mean']:.0f}", f"{s['p50']:.0f}", f"{s['p95']:.0f}"]
        for k, s in _group_summary(renders, ("connect", "n_dcs"))
    ]
    lines.append(_md_table(["connect", "n_dcs", "n", "mean", "p50", "p95"], rows))
    lines.append("")

    # Ingestion timings
    ok_ing = [i for i in ingests if i.get("ok")]
    if ok_ing:
        lines += ["## Ingestion time by cell", ""]
        rows = [
            [
                i["cell_slug"],
                f"{i.get('ingest_wall_ms', 0):.0f}",
                f"{i.get('import_wall_ms', 0):.0f}",
            ]
            for i in ok_ing
        ]
        lines.append(_md_table(["cell", "ingest_ms", "import_ms"], rows))
        lines.append("")

    if plot_names:
        lines += ["## Plots", ""]
        lines += [f"![{n}]({n})" for n in plot_names]
        lines.append("")

    report_path = output_root / "REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
