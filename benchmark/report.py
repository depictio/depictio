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
from benchmark.profile import describe, read_profile

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
    "server_total_ms",
    "dc_first_touch",
    "iteration",
    "concurrent",
    "phase",
    "filter_dc_tag",
    "hops",
    "rows_loaded",
    "rows_displayed",
    "frame_bytes",
    "aggregated",
    "cache",
    "peak_rss_mb",
    "link_values",
    "link_hops",
    "profile_label",
    "error",
]

_SIZE_ORDER = {"10mb": 0, "100mb": 1, "1gb": 2, "5gb": 3, "10gb": 4}

# Usability thresholds on render p95 wall-clock (ms). Answers "up to what size
# does Depictio stay usable?": snappy < 1s, tolerable < 3s, sluggish beyond.
_USABLE_MS = 1000.0
_TOLERABLE_MS = 3000.0

# A p95 over a handful of renders is the max of a tiny sample, not a tail. Sizes
# whose cells aborted early would otherwise score *better* than sizes that ran to
# completion (survivor bias), so below this count we report the sample instead of
# a verdict.
_MIN_RENDERS_FOR_VERDICT = 20


def _avg(rows: list[dict], key: str) -> float | None:
    """Mean of a numeric field over rows where it is present (else None)."""
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def _fmt(v: float | None) -> str:
    return f"{v:.0f}" if v is not None else "—"


def _size_of(ingest_row: dict) -> str:
    """Size token for an ingest row — parsed from the ``bench_<size>_...`` slug."""
    if ingest_row.get("size"):
        return str(ingest_row["size"])
    parts = str(ingest_row.get("cell_slug", "")).split("_")
    return parts[1] if len(parts) > 1 else ""


def _load(
    results_path: Path,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    renders: list[dict] = []
    ingests: list[dict] = []
    loads: list[dict] = []
    filter_rounds: list[dict] = []
    link_resolutions: list[dict] = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind") == "render":
            renders.append(row)
        elif row.get("kind") == "ingest":
            ingests.append(row)
        elif row.get("kind") == "dashboard_load":
            loads.append(row)
        elif row.get("kind") == "filter_round":
            filter_rounds.append(row)
        elif row.get("kind") == "link_resolution":
            link_resolutions.append(row)
    return renders, ingests, loads, filter_rounds, link_resolutions


def _phase_of(row: dict) -> str:
    """Which render phase a row came from, tolerating rows written before ``phase``.

    Older rows only carry ``concurrent``, which conflated the cold open with the
    filter rounds; ``filtered`` separates them well enough to keep those runs
    readable instead of dropping them.
    """
    phase = row.get("phase")
    if phase:
        return str(phase)
    if not row.get("concurrent"):
        return "sequential"
    return "filter_round" if row.get("filtered") else "dashboard_load"


def _ms(value: object) -> str:
    """A millisecond cell, or ``—`` for runs predating the measurement."""
    return "—" if value is None else f"{float(value):.0f}"


def _cache_cell(load: dict) -> str:
    """The cache column: state, and whether a cold row is a true first visit."""
    state = str(load.get("cache_state") or "—")
    if state != "cold":
        return state
    return "cold (1st)" if load.get("dataset_first_open", True) else "cold (reused)"


def _scope_to_profile(
    profile: dict, groups: tuple[list[dict], ...]
) -> tuple[tuple[list[dict], ...], str]:
    """Keep only the rows measured under ``profile``; return them plus a note.

    ``results.jsonl`` accumulates across runs while ``hardware_profile.json``
    describes only the latest, so printing everything under one profile header
    would attribute other machines' — or other CPU limits' — numbers to this
    one. Rows predating profile stamping carry no label; when *no* row matches,
    they are kept and the report says the profile is not attributable to them.
    """
    label = str((profile or {}).get("label") or "")
    if not label:
        return groups, ""
    if not any(str(r.get("profile_label") or "") == label for group in groups for r in group):
        return groups, (
            f"⚠️ No result row carries the profile label `{label}` — these numbers "
            "predate profile stamping and are **not** attributable to the profile above."
        )
    kept = tuple(
        [r for r in group if str(r.get("profile_label") or "") == label] for group in groups
    )
    dropped = sum(len(g) for g in groups) - sum(len(g) for g in kept)
    note = ""
    if dropped:
        note = (
            f"_{dropped} row(s) from other profiles or earlier runs are present in "
            f"`results.jsonl` and excluded here; only `{label}` is reported._"
        )
    return kept, note


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

    renders, ingests, loads, filter_rounds, link_resolutions = _load(results_path)
    profile = read_profile(output_root)
    # ``results.jsonl`` is appended to, and ``hardware_profile.json`` describes
    # only the latest run — so rows measured under other limits must be dropped
    # rather than printed under this profile's header.
    (renders, ingests, loads, filter_rounds, link_resolutions), scope_note = _scope_to_profile(
        profile, (renders, ingests, loads, filter_rounds, link_resolutions)
    )
    _write_csv(renders, output_root / "results.csv")
    # Each phase is its own regime and they must not be pooled: a cold open
    # fires every component at once *unfiltered*, a filter round fires them
    # through the viewer's bounded queue *filtered*, and a sequential render has
    # the server to itself.
    # Every phase present must land in one of the buckets below; one that
    # doesn't would silently vanish from the report.
    _unbucketed = {_phase_of(r) for r in renders} - {
        "dashboard_load_cold",
        "dashboard_load",
        "filter_round",
        "sequential",
    }
    if _unbucketed:
        raise AssertionError(f"render rows in unreported phases: {sorted(_unbucketed)}")
    cold_concurrent = [r for r in renders if _phase_of(r) == "dashboard_load_cold"]
    concurrent = [r for r in renders if _phase_of(r) == "dashboard_load"]
    filtered_concurrent = [r for r in renders if _phase_of(r) == "filter_round"]
    renders = [r for r in renders if _phase_of(r) == "sequential"]
    plot_names = _plots(renders, output_root)

    n_ok = sum(1 for r in renders if r.get("ok"))
    n_fail = len(renders) - n_ok

    lines: list[str] = ["# Depictio Benchmark Report", ""]
    # The machine and the container limits are part of the result: a latency
    # without them cannot be compared to anything, including a later run.
    lines += ["## Hardware profile", "", *describe(profile), ""]
    if scope_note:
        lines += [scope_note, ""]
    lines.append(
        f"Sequential renders: **{len(renders)}** "
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

    # Cold vs warm. The cold read is what a user actually waits for when opening
    # a dashboard; the warm one is what the cache serves afterwards. Reporting
    # them together hides both.
    cold = [r for r in renders if r.get("dc_first_touch")]
    warm = [r for r in renders if not r.get("dc_first_touch")]
    if cold and warm:
        lines += [
            "## Cold vs warm frame cache",
            "",
            "`cold` = first render touching a DC in its cell (pays the Delta read); "
            "`warm` = every later render on that DC.",
            "",
        ]
        rows = []
        for label, subset in (("cold", cold), ("warm", warm)):
            for k, s in _group_summary(subset, ("size",)):
                rows.append(
                    [k[0], label, s["n"], f"{s['mean']:.0f}", f"{s['p50']:.0f}", f"{s['p95']:.0f}"]
                )
        rows.sort(key=lambda r: (_SIZE_ORDER.get(str(r[0]), 99), r[1]))
        lines.append(_md_table(["size", "cache", "n", "mean", "p50", "p95"], rows))
        lines.append("")

    # Where the render time goes: Delta load vs build vs transport/queue.
    # server_total = load + build + server-side glue (templates, JSON);
    # overhead = wall - server_total = network + (de)serialization + Celery queue.
    lines += [
        "## Render compute breakdown (bottleneck attribution)",
        "",
        "Mean ms per stage, by DC size and component type. "
        "`load`=Delta read, `build`=plot/table build, "
        "`server_total`=whole endpoint server-side, "
        "`overhead`=wall−server_total (network + serialization + Celery queue).",
        "",
    ]
    brk_buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in renders:
        if r.get("ok"):
            brk_buckets[(r.get("size"), r.get("component_type"))].append(r)
    brk_rows = []
    for key in sorted(brk_buckets, key=lambda k: (_SIZE_ORDER.get(str(k[0]), 99), str(k[1]))):
        rs = brk_buckets[key]
        wall = _avg(rs, "wall_ms")
        stot = _avg(rs, "server_total_ms")
        overhead = (wall - stot) if (wall is not None and stot is not None) else None
        brk_rows.append(
            [
                key[0],
                key[1],
                len(rs),
                _fmt(_avg(rs, "load_ms")),
                _fmt(_avg(rs, "build_ms")),
                _fmt(stot),
                _fmt(overhead),
                _fmt(wall),
            ]
        )
    lines.append(
        _md_table(
            ["size", "type", "n", "load", "build", "server_total", "overhead", "wall"],
            brk_rows,
        )
    )
    lines.append("")

    # By connect mode × #DCs
    lines += ["## Render latency by connect mode and #DCs", ""]
    rows = [
        [k[0], k[1], s["n"], f"{s['mean']:.0f}", f"{s['p50']:.0f}", f"{s['p95']:.0f}"]
        for k, s in _group_summary(renders, ("connect", "n_dcs"))
    ]
    lines.append(_md_table(["connect", "n_dcs", "n", "mean", "p50", "p95"], rows))
    lines.append("")

    # Ingestion throughput (the dominant cost at 1 GB+).
    ok_ing = [i for i in ingests if i.get("ok")]
    if ok_ing:
        lines += [
            "## Ingestion throughput by cell",
            "",
            "`rows/s` and `MB/s` are raw-CSV input ÷ ingest wall. "
            "`compress` = input ÷ Delta (>1 = Delta smaller); — if size unknown.",
            "",
        ]
        rows = []
        for i in sorted(ok_ing, key=lambda x: _SIZE_ORDER.get(_size_of(x), 99)):
            secs = (i.get("ingest_wall_ms") or 0) / 1000.0
            rows_total = i.get("rows_total") or 0
            input_bytes = i.get("input_bytes") or 0
            delta_bytes = i.get("delta_bytes") or 0
            rps = rows_total / secs if secs > 0 else 0
            mbps = (input_bytes / 1024**2) / secs if secs > 0 else 0
            comp = input_bytes / delta_bytes if delta_bytes > 0 else 0
            rows.append(
                [
                    i["cell_slug"],
                    f"{i.get('ingest_wall_ms', 0) / 1000:.1f}",
                    f"{rows_total:,}",
                    f"{input_bytes / 1024**2:.0f}",
                    f"{rps:,.0f}",
                    f"{mbps:.1f}",
                    f"{comp:.2f}" if comp else "—",
                ]
            )
        lines.append(
            _md_table(
                ["cell", "ingest_s", "rows", "in_MB", "rows/s", "MB/s", "compress"],
                rows,
            )
        )
        lines.append("")

    # Ingestion by DC type & phase — the per-type breakdown (table / multiqc /
    # images) with where the ingest wall goes (parse/collect/write/upsert/upload)
    # and process peak RSS. This is the headline of the ingestion-optimization work.
    typed_ing = [i for i in ok_ing if i.get("dc_kind")]
    if typed_ing:
        lines += [
            "## Ingestion by DC type & phase",
            "",
            "Per cell: ingest wall, per-phase ms from the CLI timing markers "
            "(`parse`/`collect`/`write`/`upsert`/`upload`), peak RSS, and unit "
            "throughput (`units` = rows for table, files for multiqc, images for "
            "images). `stream` shows the table write path when recorded.",
            "",
        ]
        _kind_order = {"table": 0, "multiqc": 1, "images": 2}
        rows = []
        for i in sorted(
            typed_ing,
            key=lambda x: (
                _kind_order.get(x.get("dc_kind"), 9),
                _SIZE_ORDER.get(x.get("magnitude"), 99),
                str(x.get("magnitude")),
            ),
        ):
            ph = i.get("phase_ms") or {}
            secs = (i.get("ingest_wall_ms") or 0) / 1000.0
            units = i.get("n_units") or 0
            ups = units / secs if secs > 0 else 0
            rss = i.get("peak_rss_mb")
            stream = i.get("streaming")
            rows.append(
                [
                    i.get("dc_kind"),
                    i.get("magnitude"),
                    i.get("n_dcs") or 1,
                    f"{i.get('ingest_wall_ms', 0) / 1000:.1f}",
                    _fmt(ph.get("parse")),
                    _fmt(ph.get("collect")),
                    _fmt(ph.get("write")),
                    _fmt(ph.get("upsert")),
                    _fmt(ph.get("upload")),
                    f"{rss:.0f}" if rss is not None else "—",
                    f"{units:,}",
                    f"{ups:,.0f}",
                    "—" if stream is None else ("stream" if stream else "collect"),
                ]
            )
        lines.append(
            _md_table(
                [
                    "kind",
                    "mag",
                    "dcs",
                    "wall_s",
                    "parse",
                    "collect",
                    "write",
                    "upsert",
                    "upload",
                    "rss_mb",
                    "units",
                    "units/s",
                    "path",
                ],
                rows,
            )
        )
        lines.append("")

    # Dashboard cold open: all components in flight at once, which is what a
    # user triggers by opening the page. The gap against the sequential p95 is
    # the contention cost (worker pool, connection pool, concurrent Delta reads).
    if loads:
        lines += [
            "## Dashboard open (all components at once)",
            "",
            "`to_first` = the page stops being empty (first data-bearing component). "
            "`to_1st_fig` = the first *chart* is there (figure or advanced viz; cards and "
            "tables land sooner and aren't what a reader pictures). "
            "`wall_ms` = time until the **last** component lands — what the user waits for. "
            "`seq_p95` is the same cell rendered one component at a time, for contrast.",
            "",
            "`cache` is **cold** for the first open of the dashboard, before anything has "
            "touched its data collections, and **warm** once every server-side cache "
            "(row counts, aggregates, link resolution) has been populated. Cold here means "
            "the *server process* caches are empty — the Delta files may still be in the OS "
            "or object-store page cache, so a cold number is a lower bound on a cold machine. "
            "Rows written before this split are reported as `—`.",
            "",
            "A cold row marked `reused` shares its ingested project with an earlier cell in the "
            "same run — cells that differ only in component count do — so its caches were "
            "already populated and the number is warm in all but name. Only `cold`+`1st` is a "
            "true first visit.",
            "",
        ]
        rows = []
        for load in sorted(
            loads,
            key=lambda r: (
                _SIZE_ORDER.get(str(r.get("size")), 99),
                r.get("n_components", 0),
                # cold before warm, so a cell reads first-visit → revisit.
                {"cold": 0, "warm": 1}.get(str(r.get("cache_state")), 2),
            ),
        ):
            seq = [
                float(r["wall_ms"])
                for r in renders
                if r.get("cell_slug") == load.get("cell_slug") and r.get("ok") and r.get("wall_ms")
            ]
            rows.append(
                [
                    load.get("size", ""),
                    load.get("n_components", ""),
                    load.get("connect", ""),
                    _cache_cell(load),
                    f"{load.get('n_rendered', 0)}/{load.get('n_requested', 0)}",
                    _ms(load.get("time_to_first_ms")),
                    _ms(load.get("time_to_first_figure_ms")),
                    f"{float(load.get('wall_ms') or 0):.0f}",
                    f"{summarize(seq)['p95']:.0f}" if seq else "—",
                ]
            )
        lines.append(
            _md_table(
                [
                    "size",
                    "#comp",
                    "connect",
                    "cache",
                    "rendered",
                    "to_first",
                    "to_1st_fig",
                    "wall_ms",
                    "seq_p95",
                ],
                rows,
            )
        )
        lines.append("")

    # A filter change on an already-open dashboard. Distinct from both sections
    # above: the cold open pays the first Delta read but applies no filter, and
    # the sequential filtered pass never exposes the queueing that makes a filter
    # change feel slow. Each round applies a value not used before, so the
    # filtered frame cache cannot answer it.
    if filter_rounds:
        lines += [
            "## Filter change on a warm dashboard",
            "",
            "`to_last` = every component has caught up — what the user waits for after "
            "moving a filter. `to_first` = the dashboard started responding. The spread "
            "between them is the catch-up window. Fired through a pool of "
            f"{filter_rounds[0].get('concurrency', '?')}, matching the viewer's "
            "`fetchQueue` limit.",
            "",
            "Rows are grouped by the collection the filter **originates** on and how "
            "many links it has to travel: a filter applied to the collection a "
            "component reads costs nothing to propagate, one that must be translated "
            "across a link costs a resolution per hop before any data is touched. "
            "`affected` is how many timed components the filter can actually narrow: "
            "links are directed, so a filter on the leaf collection leaves the rest of "
            "the dashboard rendering unfiltered, and the two origins are not doing the "
            "same amount of work.",
            "",
        ]
        rows = []
        for fr in sorted(
            filter_rounds,
            key=lambda r: (
                _SIZE_ORDER.get(str(r.get("size")), 99),
                r.get("n_components", 0),
                str(r.get("filter_dc_tag") or ""),
                r.get("round_index", 0),
            ),
        ):
            rows.append(
                [
                    fr.get("size", ""),
                    fr.get("n_components", ""),
                    fr.get("n_dcs", ""),
                    fr.get("connect", ""),
                    fr.get("filter_dc_tag", "") or "—",
                    fr.get("hops", 0),
                    fr.get("n_affected", "?"),
                    fr.get("round_index", ""),
                    ",".join(fr.get("filter_values") or []),
                    f"{fr.get('n_ok', 0)}/{fr.get('n_fired', 0)}",
                    f"{float(fr.get('time_to_first_ms') or 0):.0f}",
                    f"{float(fr.get('time_to_last_ms') or 0):.0f}",
                ]
            )
        lines.append(
            _md_table(
                [
                    "size",
                    "#comp",
                    "#dc",
                    "connect",
                    "filter on",
                    "hops",
                    "affected",
                    "round",
                    "value",
                    "ok",
                    "to_first",
                    "to_last",
                ],
                rows,
            )
        )
        lines.append("")

        # Aggregate per origin — the comparison the table above supports but
        # doesn't state.
        # Rounds recorded before filter origins were tracked carry neither key,
        # so they normalise to ("—", 0) rather than dropping out or crashing the
        # mixed-type sort.
        by_origin = _group_summary(
            [
                {
                    **fr,
                    "wall_ms": fr.get("time_to_last_ms"),
                    "filter_dc_tag": str(fr.get("filter_dc_tag") or "—"),
                    "hops": int(fr.get("hops") or 0),
                }
                for fr in filter_rounds
                if fr.get("ok")
            ],
            ("size", "server_mode", "connect", "filter_dc_tag", "hops"),
        )
        if by_origin:
            lines += ["### Catch-up time by filter origin", ""]
            lines.append(
                _md_table(
                    [
                        "size",
                        "server",
                        "connect",
                        "filter on",
                        "hops",
                        "rounds",
                        "mean",
                        "p50",
                        "max",
                    ],
                    [
                        [*k, s["n"], f"{s['mean']:.0f}", f"{s['p50']:.0f}", f"{s['max']:.0f}"]
                        for k, s in by_origin
                    ],
                )
            )
            lines.append("")

    if link_resolutions:
        lines += [
            "## Link resolution size",
            "",
            "How many values each cross-DC translation produces, measured directly "
            "against `POST /links/{project}/resolve`. This is what makes a "
            "cross-filter number interpretable: on a realistic topology the join key "
            "has hundreds of distinct values, so a filter translates into hundreds. A "
            "translation returning millions means the join key is near-unique per row "
            "— the dataset is the pathology, not the code — and is flagged below.",
            "",
        ]
        # One row per route, not per probe: the probe runs once per filter round
        # (and once per server mode), so listing them raw repeats the same route
        # a dozen times and buries the number the section exists for.
        by_route: dict[tuple, list[dict]] = defaultdict(list)
        for lr in link_resolutions:
            key = (
                str(lr.get("cell_slug", "")),
                str(lr.get("source_tag", "")),
                str(lr.get("target_tag", "")),
                int(lr.get("hops") or 0),
            )
            by_route[key].append(lr)
        rows = []
        for (cell_slug, source, target, hops), probes in sorted(by_route.items()):
            out_values = [int(p.get("n_resolved_values") or 0) for p in probes]
            walls = [float(p.get("wall_ms") or 0.0) for p in probes]
            failed = [p for p in probes if not p.get("ok")]
            status = "ok"
            if any(p.get("pathological") for p in probes):
                status = "⚠️ pathological"
            elif failed:
                status = f"✗ {len(failed)}/{len(probes)} failed"
            rows.append(
                [
                    cell_slug,
                    f"{source} → {target}",
                    hops,
                    len(probes),
                    f"{min(out_values)}–{max(out_values)}" if out_values else "—",
                    f"{summarize(walls)['p50']:.0f}",
                    status,
                ]
            )
        lines.append(
            _md_table(
                ["cell", "route", "hops", "probes", "values out", "p50 ms", "status"],
                rows,
            )
        )
        lines.append("")

    for bucket, heading in (
        (cold_concurrent, "cold open"),
        (concurrent, "warm open"),
    ):
        if not bucket:
            continue
        lines += [
            f"### Per-component latency during a {heading} (concurrent, unfiltered)",
            "",
        ]
        rows = [
            [k[0], k[1], s["n"], f"{s['mean']:.0f}", f"{s['p50']:.0f}", f"{s['p95']:.0f}"]
            for k, s in _group_summary(bucket, ("size", "component_type"))
        ]
        lines.append(_md_table(["size", "type", "n", "mean", "p50", "p95"], rows))
        lines.append("")

    if filtered_concurrent:
        # Same components, also concurrent — but filtered and through the
        # viewer's bounded queue. Pooling the two would blend a cold unfiltered
        # open with a warm filtered change at two different client concurrencies.
        lines += [
            "### Per-component latency during a filter round (concurrent, filtered)",
            "",
        ]
        rows = [
            [
                k[0],
                k[1] or "—",
                k[2],
                k[3],
                s["n"],
                f"{s['mean']:.0f}",
                f"{s['p50']:.0f}",
                f"{s['p95']:.0f}",
            ]
            for k, s in _group_summary(
                [
                    {
                        **r,
                        "filter_dc_tag": str(r.get("filter_dc_tag") or "—"),
                        "hops": int(r.get("hops") or 0),
                    }
                    for r in filtered_concurrent
                ],
                ("size", "filter_dc_tag", "hops", "component_type"),
            )
        ]
        lines.append(
            _md_table(["size", "filter on", "hops", "type", "n", "mean", "p50", "p95"], rows)
        )
        lines.append("")

    # Usability ceiling: the direct answer to "up to what size is Depictio
    # usable?". Per size: worst render p95, any failures, and a verdict.
    lines += [
        "## Usability ceiling by DC size",
        "",
        f"Verdict on render p95 wall: **snappy** < {_USABLE_MS:.0f}ms, "
        f"**tolerable** < {_TOLERABLE_MS:.0f}ms, else **sluggish**; "
        "any render/ingest failure at a size ⇒ **FAIL**; "
        f"fewer than {_MIN_RENDERS_FOR_VERDICT} successful renders ⇒ no verdict.",
        "",
    ]
    sizes = sorted(
        {r.get("size") for r in renders} | {_size_of(i) for i in ingests},
        key=lambda s: _SIZE_ORDER.get(str(s), 99),
    )
    verdict_rows = []
    for size in sizes:
        srenders = [r for r in renders if r.get("size") == size]
        singests = [i for i in ingests if _size_of(i) == size]
        n_fail_r = sum(1 for r in srenders if not r.get("ok"))
        n_fail_i = sum(1 for i in singests if not i.get("ok"))
        walls = [float(r["wall_ms"]) for r in srenders if r.get("ok") and r.get("wall_ms")]
        p95 = summarize(walls)["p95"] if walls else float("nan")
        if n_fail_r or n_fail_i:
            verdict = "❌ FAIL"
        elif not walls:
            verdict = "—"
        elif len(walls) < _MIN_RENDERS_FOR_VERDICT:
            verdict = f"⚠️ n={len(walls)}, insufficient"
        elif p95 < _USABLE_MS:
            verdict = "✅ snappy"
        elif p95 < _TOLERABLE_MS:
            verdict = "🟡 tolerable"
        else:
            verdict = "🔴 sluggish"
        verdict_rows.append(
            [
                size,
                len(srenders),
                f"{n_fail_r + n_fail_i}",
                f"{p95:.0f}" if walls else "—",
                verdict,
            ]
        )
    lines.append(_md_table(["size", "renders", "failures", "p95_wall_ms", "verdict"], verdict_rows))
    lines.append("")

    if plot_names:
        lines += ["## Plots", ""]
        lines += [f"![{n}]({n})" for n in plot_names]
        lines.append("")

    report_path = output_root / "REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
