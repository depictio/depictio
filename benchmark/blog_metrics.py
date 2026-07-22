"""Blog-post metrics export: ``blog_metrics.json`` + a paste-ready snippet.

``report.py`` is the engineering artefact — every dimension of the matrix, in
tables meant for someone deciding what to optimise next. This is the other
audience: a handful of numbers that describe what the system does, in a form
that can be dropped into a post without re-deriving anything.

**These are absolute numbers for the current build.** There is no baseline run to
compare against, so nothing here is expressed as a speedup and no "N× faster"
phrasing is generated. Describing the mechanism and stating what it costs at
1 GB is the honest claim; "N× faster than before" would need a before.

Two things this deliberately does *not* average over:

- **Cold vs warm.** The first read of a data collection pays the Delta read; every
  later one hits the frame cache. Their mean describes neither, so they are
  reported separately (``dc_first_touch``).
- **Sequential vs concurrent.** A dashboard-load render competes with its
  siblings; a lone render doesn't. Also separated (``concurrent``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.metrics import summarize
from benchmark.report import _SIZE_ORDER, _load, _size_of

# A percentile over a handful of renders is the max of a tiny sample, not a tail.
# Mirrors report.py's guard so the two artefacts can't disagree about whether a
# size has enough data to be described.
_MIN_RENDERS = 20


def _bytes_to_gb(value: float | int | None) -> float | None:
    return round(float(value) / 1024**3, 3) if value else None


def _stats(rows: list[dict], key: str = "wall_ms") -> dict[str, Any]:
    vals = [float(r[key]) for r in rows if r.get(key) is not None and r.get("ok")]
    s = summarize(vals)
    return {
        "n": int(s["n"]),
        "p50_ms": None if s["n"] == 0 else round(s["p50"], 1),
        "p95_ms": None if s["n"] == 0 else round(s["p95"], 1),
        "mean_ms": None if s["n"] == 0 else round(s["mean"], 1),
        # Callers must not quote a percentile computed from a handful of points.
        "sufficient": int(s["n"]) >= _MIN_RENDERS,
    }


def _scale(ingests: list[dict]) -> dict[str, Any]:
    """Dataset scale, taken from the largest cell that actually ingested."""
    ok = [i for i in ingests if i.get("ok")]
    if not ok:
        return {}
    biggest = max(ok, key=lambda i: int(i.get("rows_total") or 0))
    return {
        "size": _size_of(biggest),
        "rows_total": int(biggest.get("rows_total") or 0),
        "rows_per_dc": int(biggest.get("rows_per_dc") or 0),
        "n_dcs": int(biggest.get("n_dcs") or 0),
        "input_gb": _bytes_to_gb(biggest.get("input_bytes")),
        "delta_gb": _bytes_to_gb(biggest.get("delta_bytes")),
        "compression_ratio": (
            round(float(biggest["input_bytes"]) / float(biggest["delta_bytes"]), 2)
            if biggest.get("input_bytes") and biggest.get("delta_bytes")
            else None
        ),
    }


def _ingest(ingests: list[dict]) -> dict[str, Any]:
    ok = [i for i in ingests if i.get("ok")]
    if not ok:
        return {}
    biggest = max(ok, key=lambda i: int(i.get("rows_total") or 0))
    wall_s = float(biggest.get("ingest_wall_ms") or 0) / 1000.0
    rows = int(biggest.get("rows_total") or 0)
    in_mb = float(biggest.get("input_bytes") or 0) / 1024**2
    return {
        "size": _size_of(biggest),
        "wall_s": round(wall_s, 1),
        "rows_per_s": int(rows / wall_s) if wall_s > 0 else None,
        "mb_per_s": round(in_mb / wall_s, 1) if wall_s > 0 else None,
        "phase_ms": biggest.get("phase_ms") or {},
        "peak_rss_mb": biggest.get("peak_rss_mb"),
    }


def _memory(renders: list[dict], ingests: list[dict]) -> dict[str, Any]:
    frames = [int(r["frame_bytes"]) for r in renders if r.get("frame_bytes")]
    rss_render = [float(r["peak_rss_mb"]) for r in renders if r.get("peak_rss_mb")]
    rss_ingest = [float(i["peak_rss_mb"]) for i in ingests if i.get("peak_rss_mb")]
    return {
        "max_render_frame_gb": _bytes_to_gb(max(frames)) if frames else None,
        "peak_rss_ingest_mb": round(max(rss_ingest), 1) if rss_ingest else None,
        # Process high-water mark, not a per-render figure: RSS never comes back
        # down, so this is an upper bound on the API process across the whole run.
        "peak_rss_api_mb": round(max(rss_render), 1) if rss_render else None,
    }


def _by(renders: list[dict], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict]] = {}
    for r in renders:
        groups.setdefault(str(r.get(key) or "unknown"), []).append(r)
    return {k: _stats(v) for k, v in sorted(groups.items())}


def _aggregation_coverage(renders: list[dict]) -> dict[str, Any]:
    """How much of the render work avoided materialising rows at all."""
    figures = [r for r in renders if r.get("component_type") == "figure" and r.get("ok")]
    if not figures:
        return {}
    aggregated = [r for r in figures if r.get("aggregated")]
    by_visu: dict[str, Any] = {}
    for r in figures:
        visu = str(r.get("visu") or "unknown")
        entry = by_visu.setdefault(visu, {"n": 0, "aggregated": 0, "rows_loaded": []})
        entry["n"] += 1
        entry["aggregated"] += bool(r.get("aggregated"))
        if r.get("rows_loaded") is not None:
            entry["rows_loaded"].append(int(r["rows_loaded"]))
    for visu, entry in by_visu.items():
        loaded = entry.pop("rows_loaded")
        entry["median_rows_loaded"] = sorted(loaded)[len(loaded) // 2] if loaded else None
        entry["always_aggregated"] = entry["aggregated"] == entry["n"]
    return {
        "figures": len(figures),
        "served_by_aggregation": len(aggregated),
        "by_visu": dict(sorted(by_visu.items())),
    }


def build_blog_metrics(output_root: str | Path) -> tuple[Path, Path]:
    """Write ``blog_metrics.json`` and ``BLOG_SNIPPET.md``. Returns both paths."""
    output_root = Path(output_root)
    results = output_root / "results.jsonl"
    if not results.exists():
        raise FileNotFoundError(f"No results at {results} — run the matrix first.")

    renders, ingests, _loads = _load(results)
    ok_renders = [r for r in renders if r.get("ok")]

    cold = [r for r in ok_renders if r.get("dc_first_touch")]
    warm = [r for r in ok_renders if not r.get("dc_first_touch") and not r.get("concurrent")]
    concurrent = [r for r in ok_renders if r.get("concurrent")]

    by_size: dict[str, Any] = {}
    for size in sorted(
        {str(r.get("size")) for r in ok_renders}, key=lambda s: _SIZE_ORDER.get(s, 99)
    ):
        rows = [r for r in ok_renders if str(r.get("size")) == size]
        by_size[size] = {
            "all": _stats(rows),
            "cold": _stats([r for r in rows if r.get("dc_first_touch")]),
            "warm": _stats(
                [r for r in rows if not r.get("dc_first_touch") and not r.get("concurrent")]
            ),
        }

    metrics: dict[str, Any] = {
        "scale": _scale(ingests),
        "ingest": _ingest(ingests),
        "memory": _memory(renders, ingests),
        "render": {
            "by_size": by_size,
            "by_component": _by(ok_renders, "component_type"),
            "by_visu": _by([r for r in ok_renders if r.get("visu")], "visu"),
            "cache_regime": {
                "cold": _stats(cold),
                "warm": _stats(warm),
                "concurrent": _stats(concurrent),
            },
        },
        "aggregation": _aggregation_coverage(renders),
        "totals": {
            "renders": len(renders),
            "renders_ok": len(ok_renders),
            "ingests": len(ingests),
        },
        "caveats": [
            "Absolute numbers for this build; no baseline run, so no speedup figures.",
            "Cold (first touch of a data collection) and warm (frame-cache hit) are "
            "reported separately — their mean describes neither.",
            "peak_rss_api_mb is a process high-water mark, not per-render.",
            f"Percentiles from fewer than {_MIN_RENDERS} renders are marked "
            "sufficient=false and should not be quoted.",
        ],
    }

    json_path = output_root / "blog_metrics.json"
    json_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    snippet_path = output_root / "BLOG_SNIPPET.md"
    snippet_path.write_text(_render_snippet(metrics), encoding="utf-8")
    return json_path, snippet_path


def _fmt_ms(entry: dict | None) -> str:
    if not entry or entry.get("p50_ms") is None:
        return "—"
    suffix = "" if entry.get("sufficient") else f" *(n={entry['n']})*"
    return f"{entry['p50_ms']:.0f} ms{suffix}"


def _render_snippet(m: dict) -> str:
    scale = m.get("scale") or {}
    ingest = m.get("ingest") or {}
    memory = m.get("memory") or {}
    lines: list[str] = ["## By the numbers", ""]

    if scale:
        bits = [f"**{scale['rows_total']:,} rows**"]
        if scale.get("n_dcs"):
            bits.append(f"across **{scale['n_dcs']} data collections**")
        if scale.get("input_gb"):
            delta = f" / {scale['delta_gb']} GB Delta" if scale.get("delta_gb") else ""
            bits.append(f"({scale['input_gb']} GB raw{delta})")
        lines += [" ".join(bits), ""]

    if ingest:
        lines += [
            f"- **Ingest** — {ingest['wall_s']}s for the {ingest.get('size', '')} dataset"
            + (f", {ingest['rows_per_s']:,} rows/s" if ingest.get("rows_per_s") else "")
            + (f" ({ingest['mb_per_s']} MB/s)" if ingest.get("mb_per_s") else ""),
        ]
    if memory.get("max_render_frame_gb") is not None:
        lines.append(
            f"- **Largest frame held in memory for a render** — {memory['max_render_frame_gb']} GB"
        )
    if memory.get("peak_rss_api_mb"):
        lines.append(
            f"- **API process peak RSS** — {memory['peak_rss_api_mb']:.0f} MB "
            "(high-water mark across the whole run, not per render)"
        )

    agg = m.get("aggregation") or {}
    if agg.get("figures"):
        lines.append(
            f"- **{agg['served_by_aggregation']} of {agg['figures']} figure renders** were "
            "answered by a Polars aggregation over the Delta scan — no rows materialised"
        )
    lines.append("")

    by_component = (m.get("render") or {}).get("by_component") or {}
    if by_component:
        lines += ["### Render latency by component type", ""]
        lines += ["| component | renders | p50 | p95 |", "| --- | --- | --- | --- |"]
        for name, entry in by_component.items():
            p95 = f"{entry['p95_ms']:.0f} ms" if entry.get("p95_ms") is not None else "—"
            lines.append(f"| {name} | {entry['n']} | {_fmt_ms(entry)} | {p95} |")
        lines.append("")

    by_size = (m.get("render") or {}).get("by_size") or {}
    if by_size:
        lines += [
            "### Cold vs warm, by dataset size",
            "",
            "Cold is the first read of a data collection; warm is a frame-cache hit. "
            "They're kept apart because averaging them describes neither.",
            "",
            "| size | cold p50 | warm p50 | renders |",
            "| --- | --- | --- | --- |",
        ]
        for size, entry in by_size.items():
            lines.append(
                f"| {size} | {_fmt_ms(entry.get('cold'))} | {_fmt_ms(entry.get('warm'))} "
                f"| {entry['all']['n']} |"
            )
        lines.append("")

    visu = (agg.get("by_visu") or {}) if agg else {}
    if visu:
        lines += [
            "### Rows read per figure type",
            "",
            "`0` means the figure was computed as an aggregation over the scan — the "
            "reduction is exact, it just never materialises the rows.",
            "",
            "| visualisation | renders | median rows read | aggregated |",
            "| --- | --- | --- | --- |",
        ]
        for name, entry in visu.items():
            rows = entry.get("median_rows_loaded")
            rows_s = f"{rows:,}" if rows is not None else "—"
            mark = (
                "yes"
                if entry.get("always_aggregated")
                else ("some" if entry["aggregated"] else "no")
            )
            lines.append(f"| {name} | {entry['n']} | {rows_s} | {mark} |")
        lines.append("")

    lines += [
        "---",
        "",
        "*Figures are absolute measurements of the current build. No baseline run was "
        "made, so no before/after comparison is claimed.*",
        "",
    ]
    return "\n".join(lines)
