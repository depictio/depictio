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
- **The three render phases.** A sequential render has the server to itself, a
  cold open fires every component at once unfiltered, and a filter round fires
  them through the viewer's bounded queue with a filter applied. All three are
  reported apart (``phase``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.metrics import summarize
from benchmark.profile import describe, read_profile
from benchmark.report import _SIZE_ORDER, _load, _phase_of, _scope_to_profile, _size_of

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
    # A reused project ingested nothing this run; its 0 ms wall would report an
    # infinite throughput.
    ok = [i for i in ingests if i.get("ok") and not i.get("reused")]
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
        # Kept in bytes as well: the GB figure rounds to 0.001 for frames this
        # small, and anything derived from it inherits that error.
        "max_render_frame_bytes": max(frames) if frames else None,
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


def _duration(ms: float | None) -> str:
    """A duration a reader can hold in their head: ms below a second, else s."""
    if ms is None:
        return "—"
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def _dashboard_open(loads: list[dict]) -> list[dict[str, Any]]:
    """First-chart and full-load time per component count, cold and warm.

    A `cold (reused)` row is dropped rather than relabelled: its caches were
    populated by an earlier cell in the same run, so publishing it as a cold
    number would overstate how well a genuine first visit performs. Better to
    show fewer rows than a flattering wrong one.
    """
    out: list[dict[str, Any]] = []
    for load in sorted(loads, key=lambda r: (r.get("n_components") or 0,)):
        state = str(load.get("cache_state") or "")
        if state == "cold" and not load.get("dataset_first_open", True):
            continue
        if load.get("time_to_first_figure_ms") is None:
            continue
        out.append(
            {
                "n_components": load.get("n_components"),
                "cache": state or "—",
                "first_chart": _duration(load.get("time_to_first_figure_ms")),
                "all_components": _duration(load.get("wall_ms")),
                "n_rendered": load.get("n_rendered"),
                "n_requested": load.get("n_requested"),
            }
        )
    return out


def _filter_latency(filter_rounds: list[dict]) -> dict[str, Any]:
    """Time for a dashboard to catch up with one filter change, per scale.

    Grouped by ``(size, n_components, n_dcs)`` because the number a reader wants
    is meaningless without all three — "3 seconds" describes a dashboard, not a
    system. Only successful rounds are summarised: a round where a component
    errored finished early for the wrong reason.

    Rounds are kept individually as well as summarised. There are usually few of
    them (one per applied value), so a percentile would be the max of a tiny
    sample — the same guard the rest of this module applies.
    """
    ok_rounds = [f for f in filter_rounds if f.get("ok")]
    if not ok_rounds:
        return {}

    groups: dict[tuple, list[dict]] = {}
    for f in ok_rounds:
        key = (
            str(f.get("size")),
            int(f.get("n_components") or 0),
            int(f.get("n_dcs") or 0),
            str(f.get("server_mode") or ""),
            str(f.get("filter_dc_tag") or ""),
            int(f.get("hops") or 0),
        )
        groups.setdefault(key, []).append(f)

    by_scale: list[dict[str, Any]] = []
    for (size, n_comp, n_dcs, server_mode, filter_dc, hops), rounds in sorted(
        groups.items(), key=lambda kv: (_SIZE_ORDER.get(kv[0][0], 99), kv[0][1], kv[0][4])
    ):
        first = summarize([float(r.get("time_to_first_ms") or 0.0) for r in rounds])
        last = summarize([float(r.get("time_to_last_ms") or 0.0) for r in rounds])
        by_scale.append(
            {
                "size": size,
                "n_components": n_comp,
                "n_dcs": n_dcs,
                "server_mode": server_mode,
                "connect": rounds[0].get("connect", ""),
                # Where the filter started and how far it travelled. A filter on
                # the collection a component reads propagates for free; one that
                # crosses links pays a resolution per hop first.
                "filter_dc": filter_dc,
                "hops": hops,
                # Components this origin can actually narrow (links are directed).
                "components_affected": int(rounds[0].get("n_affected") or 0),
                "filter_column": rounds[0].get("filter_column", ""),
                "n_rounds": len(rounds),
                "components_per_round": int(rounds[0].get("n_fired") or 0),
                "client_concurrency": int(rounds[0].get("concurrency") or 0),
                "to_first_ms": {
                    "median": round(first["p50"], 1),
                    "max": round(first["max"], 1),
                },
                "to_last_ms": {
                    "median": round(last["p50"], 1),
                    "max": round(last["max"], 1),
                },
                # Every round applied a value none of the earlier ones used, so
                # none of these could be served by the filtered frame cache.
                "values_applied": [r.get("filter_values") for r in rounds],
            }
        )
    return {"by_scale": by_scale}


def _link_resolution(rows: list[dict]) -> dict[str, Any]:
    """How large each cross-DC translation was, per route.

    The number that decides whether a cross-filter measurement describes normal
    usage: a join key with hundreds of distinct values translates a filter into
    hundreds. Millions means the key is near-unique per row — a pathological
    topology, kept as an explicit adversarial case and labelled as one.
    """
    if not rows:
        return {}
    # One entry per route. The probe runs once per filter round and once per
    # server mode, so the raw rows repeat each route many times over.
    grouped: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (
            str(r.get("cell_slug", "")),
            f"{r.get('source_tag', '')} -> {r.get('target_tag', '')}",
            int(r.get("hops") or 0),
        )
        grouped.setdefault(key, []).append(r)

    routes: list[dict[str, Any]] = []
    for (cell, route, hops), probes in sorted(grouped.items()):
        out_values = [int(p.get("n_resolved_values") or 0) for p in probes]
        routes.append(
            {
                "cell": cell,
                "route": route,
                "hops": hops,
                "probes": len(probes),
                "filter_column": probes[0].get("filter_column", ""),
                "values_in": int(probes[0].get("n_source_values") or 0),
                "values_out_min": min(out_values) if out_values else 0,
                "values_out_max": max(out_values) if out_values else 0,
                "wall_ms_median": round(
                    summarize([float(p.get("wall_ms") or 0.0) for p in probes])["p50"], 1
                ),
                "ok": all(p.get("ok") for p in probes),
                "pathological": any(p.get("pathological") for p in probes),
            }
        )
    resolved = [r["values_out_max"] for r in routes if r["ok"]]
    return {
        "routes": routes,
        "max_values_resolved": max(resolved) if resolved else 0,
        "any_pathological": any(r["pathological"] for r in routes),
    }


def build_blog_metrics(output_root: str | Path) -> tuple[Path, Path]:
    """Write ``blog_metrics.json`` and ``BLOG_SNIPPET.md``. Returns both paths."""
    output_root = Path(output_root)
    results = output_root / "results.jsonl"
    if not results.exists():
        raise FileNotFoundError(f"No results at {results} — run the matrix first.")

    renders, ingests, loads, filter_rounds, link_resolutions = _load(results)
    profile = read_profile(output_root)
    # results.jsonl accumulates across runs; hardware_profile.json describes only
    # the latest. Numbers from other limits must not be published under it.
    (renders, ingests, loads, filter_rounds, link_resolutions), scope_note = _scope_to_profile(
        profile, (renders, ingests, loads, filter_rounds, link_resolutions)
    )
    ok_renders = [r for r in renders if r.get("ok")]

    sequential = [r for r in ok_renders if _phase_of(r) == "sequential"]
    cold = [r for r in sequential if r.get("dc_first_touch")]
    warm = [r for r in sequential if not r.get("dc_first_touch")]
    # Two distinct concurrent regimes: a cold open is unfiltered and unbounded,
    # a filter round is filtered and bounded by the viewer's queue.
    dashboard_load_cold = [r for r in ok_renders if _phase_of(r) == "dashboard_load_cold"]
    dashboard_load = [r for r in ok_renders if _phase_of(r) == "dashboard_load"]
    filter_round = [r for r in ok_renders if _phase_of(r) == "filter_round"]

    by_size: dict[str, Any] = {}
    for size in sorted(
        {str(r.get("size")) for r in ok_renders}, key=lambda s: _SIZE_ORDER.get(s, 99)
    ):
        rows = [r for r in ok_renders if str(r.get("size")) == size]
        seq = [r for r in rows if _phase_of(r) == "sequential"]
        by_size[size] = {
            "all": _stats(rows),
            "cold": _stats([r for r in seq if r.get("dc_first_touch")]),
            "warm": _stats([r for r in seq if not r.get("dc_first_touch")]),
        }

    metrics: dict[str, Any] = {
        # The machine, VM and container limits these numbers describe. Quoting a
        # latency without them makes it uncomparable to any other run.
        "hardware": profile,
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
                "dashboard_load_cold": _stats(dashboard_load_cold),
                "dashboard_load": _stats(dashboard_load),
                "filter_round": _stats(filter_round),
            },
        },
        "dashboard_open": _dashboard_open(loads),
        "filter_latency": _filter_latency(filter_rounds),
        "link_resolution": _link_resolution(link_resolutions),
        "aggregation": _aggregation_coverage(renders),
        "totals": {
            "renders": len(renders),
            "renders_ok": len(ok_renders),
            "ingests": len(ingests),
        },
        "caveats": ([scope_note] if scope_note else [])
        + [
            "Absolute numbers for this build; no baseline run, so no speedup figures.",
            "Cold (first touch of a data collection) and warm (frame-cache hit) are "
            "reported separately — their mean describes neither.",
            "peak_rss_api_mb is a process high-water mark, not per-render.",
            f"Percentiles from fewer than {_MIN_RENDERS} renders are marked "
            "sufficient=false and should not be quoted.",
            "Every figure describes one hardware profile (see the `hardware` key) — "
            "host, VM and per-container CPU limits. A number taken under other limits "
            "is a different measurement, not a comparable one.",
            "connect=links-adversarial is a deliberate worst case: its join key is "
            "unique per row, so a filter translates into millions of values. It is "
            "kept because it found real bugs; it does not describe normal usage, and "
            "its cross-filter numbers must not be quoted as the cost of cross-filtering.",
            "filter_latency is server-side: it ends when the last HTTP response lands, "
            "not when the browser has painted. JSON parsing and the Plotly/AG-Grid "
            "build happen after that, on a single main thread, and are not counted "
            "here — the in-browser number is larger.",
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

    hardware = m.get("hardware") or {}
    if hardware:
        lines += ["Measured on:", "", *describe(hardware), ""]

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
    if memory.get("max_render_frame_bytes") is not None:
        # Rounded to GB this reads "0.001", which throws away the point: the
        # frame is three orders of magnitude smaller than the collection. Show
        # it in the unit that carries the meaning, from the raw byte count.
        frame_bytes = float(memory["max_render_frame_bytes"])
        frame = (
            f"{frame_bytes / 1024**2:.1f} MB"
            if frame_bytes < 1024**3
            else f"{frame_bytes / 1024**3:.2f} GB"
        )
        lines.append(f"- **Largest frame held in memory for any render** — {frame}")
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

    opens = m.get("dashboard_open") or []
    if opens:
        lines += [
            "### Opening a dashboard",
            "",
            "Every component is fetched at once, the way the page does it. `first chart` "
            "is when a plot is on screen — the moment the dashboard stops looking empty; "
            "`all components` is when the last one lands. They are far apart, and quoting "
            "only the second describes a wait the user never spends staring at nothing.",
            "",
            "`cold` is the first ever open of the dashboard, with every server-side cache "
            "empty. `warm` is a revisit.",
            "",
            "| components | cache | first chart | all components |",
            "| --- | --- | --- | --- |",
        ]
        for entry in opens:
            lines.append(
                f"| {entry['n_components']} | {entry['cache']} | "
                f"{entry['first_chart']} | {entry['all_components']} |"
            )
        lines.append("")

    filt = (m.get("filter_latency") or {}).get("by_scale") or []
    if filt:
        lines += [
            "### Changing a filter on an open dashboard",
            "",
            "Every component re-renders when a filter changes. `to first` is when the "
            "dashboard starts responding, `to last` is when it has fully caught up — "
            "the number the user actually waits for. Each round applies a value none of "
            "the previous rounds used, so none of these are cache hits. Requests are "
            "issued through the same bounded queue the viewer uses.",
            "",
            "`filter on` is the collection the filter is applied to and `hops` how many "
            "links it has to cross to reach the components — a filter on the collection "
            "being rendered propagates for free, one across links pays a resolution per "
            "hop first.",
            "",
            "| dataset | filter on | hops | components | affected | to first | to last |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for entry in filt:
            scale = f"{entry['size']} × {entry['n_dcs']} DC"
            comps = f"{entry['components_per_round']} (≤{entry['client_concurrency']} in flight)"
            origin = f"{entry.get('filter_dc') or '—'}.{entry.get('filter_column', '')}"
            lines.append(
                f"| {scale} | {origin} | {entry.get('hops', 0)} | {comps} "
                f"| {entry.get('components_affected', '?')} "
                f"| {entry['to_first_ms']['median']:.0f} ms "
                f"| {entry['to_last_ms']['median'] / 1000:.1f} s |"
            )
        lines.append("")

    links = m.get("link_resolution") or {}
    if links.get("routes"):
        lines += [
            "### What a cross-DC filter has to translate",
            "",
            "Before a linked component can be narrowed, the filter is translated into "
            "the join key of the target collection. The size of that translation — not "
            "the size of the collection — is what makes cross-filtering cheap or "
            "impossible.",
            "",
            "| route | hops | values in | values out | median ms |",
            "| --- | --- | --- | --- | --- |",
        ]
        for route in links["routes"]:
            flag = " ⚠️" if route["pathological"] else ""
            span = (
                f"{route['values_out_min']:,}"
                if route["values_out_min"] == route["values_out_max"]
                else f"{route['values_out_min']:,}–{route['values_out_max']:,}"
            )
            lines.append(
                f"| {route['route']}{flag} | {route['hops']} | {route['values_in']} "
                f"| {span} | {route['wall_ms_median']:.0f} |"
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
