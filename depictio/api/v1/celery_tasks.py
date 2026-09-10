"""FastAPI-side Celery tasks.

Each task wraps the heavy body of a preview / render endpoint so it executes
on the Celery worker process instead of pinning a FastAPI worker.

Tasks intentionally take and return JSON-serializable dicts only — Celery is
configured for the JSON serializer by default. Endpoints stay thin: they
validate input cheaply, then `await offload_or_run(...)` to dispatch the task
and unwrap its result.

Tasks are auto-discovered when this module is imported by the Celery worker
(see `depictio.api.celery_worker`).
"""

from __future__ import annotations

import json
import time
from typing import Any

from bson import ObjectId

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# For point plots we random-sample down to the plotted-point target, but we only
# need to *load* a modest multiple of it for that sample to be representative —
# scanning the whole table just to discard most rows is the dominant render cost.
_POINT_LOAD_OVERSAMPLE = 4


def _load_uniform_sample(
    wf_oid,
    dc_id: str,
    filter_metadata: list | None,
    init_data: dict,
    cap: int,
    render_stats: dict,
):
    """Load at most ``cap`` rows drawn uniformly from the whole (filtered) table.

    Used for code-mode figures, where we can't know which columns the user's code
    reads (so no projection) or whether it aggregates (so no reduction) — but we
    still must bound how much lands in the worker. The one thing we *can* fix is
    which rows: a uniform sample instead of the leading N.

    Returns ``None`` if the scan can't be opened, so the caller falls back to the
    ordinary loader. Records the pre-sample total in ``render_stats`` so the
    viewer's badge can say "N of M" instead of silently showing a slice.
    """
    import polars as _pl

    from depictio.api.v1.deltatables_utils import open_deltatable_scan

    scan = open_deltatable_scan(
        workflow_id=wf_oid,
        data_collection_id=dc_id,
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    if scan is None:
        return None
    try:
        total = int(scan.select(_pl.len()).collect().item())
        if total <= cap:
            return scan.collect()
        # Hash the whole row rather than one column: hashing a single column
        # would keep or drop every row sharing a value, which biases exactly the
        # grouped comparisons code-mode figures usually make.
        stride = -(-total // cap)  # ceil
        sampled = scan.filter(_pl.struct(_pl.all()).hash(seed=0) % stride == 0).collect()
        render_stats["sampled"] = True
        render_stats["total_rows"] = total
        logger.info(
            f"_load_uniform_sample: dc={dc_id} sampled {sampled.height} of {total} rows "
            f"(cap {cap}) — uniform, not a prefix"
        )
        return sampled
    except Exception as e:
        logger.warning(f"_load_uniform_sample: failed for dc={dc_id}: {e} — using the plain loader")
        return None


def _ensure_mantine_templates() -> None:
    """Worker-side Plotly template registration. Mirrors the helper in
    `figure_endpoints.routes`. Without this, plotly express raises
    ``KeyError: 'mantine_light'`` when Depictio's theme template lookup runs."""
    from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates

    ensure_mantine_templates()


@celery_app.task(name="depictio.figure.build_preview", soft_time_limit=120, time_limit=180)
def build_figure_preview(payload: dict) -> dict:
    """Heavy body of figure preview AND figure render — same code path.

    Input shape (validated by caller):
        {
          "metadata": {                 # full figure stored_metadata or component dict
            "wf_id", "dc_id",
            "dc_config",                # optional, with delta_location fallback
            "visu_type", "dict_kwargs",
            "mode" ("ui" | "code"), "code_content",
            "selection_enabled" (optional, render only),
            "selection_column"  (optional, render only),
          },
          "filter_metadata": [...],     # cleaned filters list
          "theme": "light" | "dark"
        }

    Returns:
        {"figure": <plotly fig dict>, "metadata": {"visu_type": str, "filter_applied": bool}}
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import count_deltatable_lite, load_deltatable_lite

    metadata = payload.get("metadata") or {}
    filter_metadata = payload.get("filter_metadata") or []
    theme = payload.get("theme") or "light"
    full_load = bool(payload.get("full_load", False))

    wf_id = metadata.get("wf_id")
    dc_id = metadata.get("dc_id")
    wf_oid = ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id

    dc_config = metadata.get("dc_config") or {}
    init_data: dict[str, dict] = {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if delta_loc:
        init_data[str(dc_id)] = {
            "delta_location": delta_loc,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }

    visu_type = metadata.get("visu_type", "scatter")
    dict_kwargs = metadata.get("dict_kwargs") or {}
    mode = metadata.get("mode", "ui")
    code_content = metadata.get("code_content", "")
    selection_enabled = bool(metadata.get("selection_enabled", False))
    selection_column = metadata.get("selection_column")

    # Color-by-selection-groups (issue #89): the viewer may ask for the figure
    # to be colored by the user's saved selection groups. Sanitized at the
    # endpoint; re-checked here because preview callers build payloads too.
    # Code mode is excluded (arbitrary user code owns its own figure) and so
    # are whole-frame visus, whose column sets we can't reason about.
    import polars as pl

    from depictio.api.v1.services.figure.figure_builder import _WHOLE_FRAME_VISU
    from depictio.api.v1.services.figure.groups import (
        CODE_GROUP_BY,
        CODE_GROUP_KWARGS,
        GROUP_COLUMN,
        MAX_FACET_CATEGORIES,
        OTHER_LABEL,
        apply_column_coloring_kwargs,
        apply_facet_kwargs,
        apply_group_coloring_kwargs,
        group_annotation_expr,
        group_source_columns,
        sanitize_color_by_column,
        sanitize_group_defs,
        sanitize_grouping_display,
        tidy_facet_layout,
    )

    coloring_allowed = mode != "code" and (visu_type or "").lower() not in _WHOLE_FRAME_VISU
    # Code mode owns the figure it builds, so the server must never rewrite its
    # kwargs. What it can do is hand over the very kwargs UI mode gets and let
    # the author spread them: `**depictio_group_kwargs`. Those come out of
    # `_grouped_kwargs` below, the single place that turns the saved groups plus
    # the Colour/Split toggle into px arguments, so a code figure and a UI figure
    # cannot end up disagreeing about what "Split" means.
    #
    # Opt-in by naming it: a code figure that ignores groups pays no annotation
    # pass over its frame and keeps reporting no override, exactly as before.
    code_group_optin = mode == "code" and (
        CODE_GROUP_KWARGS in code_content
        or CODE_GROUP_BY in code_content
        or GROUP_COLUMN in code_content
    )
    group_defs = sanitize_group_defs(payload.get("groups"))
    color_by_group = (
        bool(payload.get("color_by_group"))
        and bool(group_defs)
        and (coloring_allowed or code_group_optin)
    )
    group_colored = False
    # What code mode is handed. Empty whenever grouping is off, or the frame
    # turned out not to carry any group's source column, so a figure that always
    # spreads it simply renders ungrouped instead of failing.
    code_group_kwargs: dict = {}
    # The grouping keys an aggregating code figure spreads into its `group_by`.
    # Empty for the same reasons `code_group_kwargs` is.
    code_group_by: list[str] = []
    # False drops rows outside every group instead of drawing them gray. Since
    # "Other" is its own category, dropping it never changes the group traces —
    # it only removes the gray context (and its facet panel in Split mode).
    include_other = payload.get("include_other") is not False

    # Global "color by <real column>" override (issue #89): same gates and the
    # same revert-if-absent contract as group coloring, but the column is real
    # so no synthetic annotation is needed. Groups win when both are requested
    # (the endpoint enforces the same precedence).
    color_by_column = None
    if (coloring_allowed or code_group_optin) and not color_by_group:
        # Code mode reaches this too, by the same handover as groups: "Colour by
        # Phylum, split" is the same request whether the figure was authored in
        # the UI or in Python, and answering it only on one path would make the
        # dashboard-wide control lie about half its tiles.
        color_by_column = sanitize_color_by_column(payload.get("color_by_column"))
    column_colored: str | None = None

    # Display mode for either override: "color" overlays series in one panel,
    # "facet" splits into small multiples (px facet_col on the same column the
    # coloring uses). Faceting stays color-aware — each panel keeps its
    # category color — and degrades to color-only when there would be too many
    # panels to read. Applied via ``_apply_display`` wherever the coloring
    # kwargs land so revert/re-apply paths can't disagree with it.
    grouping_display = sanitize_grouping_display(payload.get("grouping_display"))

    def _apply_display(kwargs: dict, facet_column: str, n_categories: int | None) -> dict:
        if grouping_display != "facet":
            return kwargs
        # Unknown cardinality (column mode before the client's palette
        # resolved, or a mapless request) degrades to overlay rather than
        # faceting an unbounded category set — refuse rather than guess.
        if n_categories is None or n_categories > MAX_FACET_CATEGORIES:
            return kwargs
        return apply_facet_kwargs(kwargs, facet_column)

    def _grouped_kwargs(base: dict) -> dict:
        # +1 when "Other" is shown: the synthetic column then carries the
        # fallback label as its own category (and facet panel in Split mode).
        return _apply_display(
            apply_group_coloring_kwargs(base, group_defs, include_other=include_other),
            GROUP_COLUMN,
            len(group_defs) + (1 if include_other else 0),
        )

    def _column_kwargs(base: dict) -> dict:
        assert color_by_column is not None
        column = color_by_column["column_name"]
        color_map = color_by_column["color_map"]
        return _apply_display(
            apply_column_coloring_kwargs(base, column, color_map),
            column,
            len(color_map) if color_map else None,
        )

    # Column projection (#7): in UI mode the figure spec tells us exactly which
    # columns Plotly Express will read, so load only those — the loader folds in
    # filter columns and schema-guards the set. Code mode can reference any
    # column via arbitrary user code, so it always loads the full frame.
    select_columns: list[str] | None = None
    from depictio.api.v1.services.figure.figure_builder import (
        _SAMPLABLE_PLOT_TYPES,
        referenced_columns,
    )

    if mode != "code":
        cols = referenced_columns(visu_type, dict_kwargs)
        if cols is not None:
            if selection_enabled and selection_column:
                cols = cols | {selection_column}
            # The group annotation reads real source columns, so project them
            # in. The synthetic GROUP_COLUMN itself must never enter the
            # projection — `_project_scan` intersects with the Delta schema and
            # would silently drop it.
            if color_by_group:
                cols = cols | group_source_columns(group_defs)
            if color_by_column:
                cols = cols | {color_by_column["column_name"]}
            select_columns = sorted(cols)

    # Only after the projection is computed from the ORIGINAL kwargs may the
    # color override land: `referenced_columns` on the grouped kwargs would
    # collect the synthetic column (dropped by the schema guard) and miss the
    # real source column. Keep the originals so the paths below can revert if
    # the group column turns out not to exist in this frame.
    original_dict_kwargs = dict_kwargs
    if color_by_group:
        dict_kwargs = _grouped_kwargs(dict_kwargs)
    elif color_by_column:
        dict_kwargs = _column_kwargs(dict_kwargs)

    # Plot-level point cap: component override or global default, unless the
    # client explicitly asked for a full load (-1 disables sampling entirely).
    if full_load:
        effective_max_points = -1
    else:
        effective_max_points = metadata.get("max_points") or settings.performance.figure_max_points

    # Row ceiling: for mark-per-row plots (scatter family, line/area/ecdf) and
    # code-mode figures, bound how many rows we pull from Delta so a 10 GB table
    # doesn't fully materialise just to be downsampled/plotted. We only need a
    # modest multiple of the plotted-point target for the sample to stay
    # representative — loading the whole table just to throw ~95% away is the
    # main render-latency cost, so cap the scan near the sample size.
    # Reducing plots (box/histogram/density/bar) don't reach here at all: they're
    # served by the scan-level aggregation below, which reads every row without
    # materialising any. ``full_load`` bypasses the cap entirely.
    limit_rows: int | None = None
    is_samplable = visu_type in _SAMPLABLE_PLOT_TYPES
    if not full_load:
        if is_samplable and effective_max_points > 0:
            limit_rows = min(
                effective_max_points * _POINT_LOAD_OVERSAMPLE,
                settings.performance.figure_max_load_rows,
            )
        elif is_samplable:
            limit_rows = settings.performance.figure_max_load_rows

    # Code mode: cap the rows the user's code receives, but draw them uniformly.
    # This used to ride on ``limit_rows``, i.e. a prefix — and since parquet row
    # order follows ingest order, "the first 500k rows" is typically just the
    # first few files/samples. That is a biased view presented as if it were the
    # data. A uniform sample of the same size is strictly better at the same
    # cost; it is still approximate, which is why it's surfaced as sampled below.
    # The cap is per-component (``max_points``) so a user whose code aggregates
    # can raise it, or take Load-All for the exact frame.
    code_sample_cap: int | None = None
    if mode == "code" and not full_load:
        code_sample_cap = int(
            metadata.get("max_points") or settings.performance.figure_max_load_rows
        )

    render_stats: dict[str, Any] = {}

    # Scan-level aggregation fast path. Reducing visualisations (box, histogram,
    # density_*, bar) are a handful of numbers per group, which Polars computes
    # as a pushdown over parquet — no frame is ever materialised. Without this a
    # 1 GB box plot collects ~28 M rows and then ships every raw value inside the
    # trace. `plan_aggregation` returns None for anything it can't reproduce
    # exactly, and `build_aggregated_figure` returns None if the reduction turns
    # out not to be viable, so both fall through to the load below.
    #
    # Code mode is excluded (arbitrary user code can reference any column) and so
    # is `full_load`, which is the user explicitly asking for the exact px render.
    agg_fig = None
    started = time.monotonic()
    if mode != "code" and not full_load:
        from depictio.api.v1.deltatables_utils import open_deltatable_scan
        from depictio.api.v1.services.figure.aggregate import (
            build_aggregated_figure,
            plan_aggregation,
        )

        agg_plan = plan_aggregation(visu_type, dict_kwargs)
        if agg_plan is not None:
            scan = open_deltatable_scan(
                workflow_id=wf_oid,
                data_collection_id=str(dc_id),
                metadata=filter_metadata or None,
                init_data=init_data,
                select_columns=select_columns,
            )
            if scan is not None:
                from depictio.api.v1.services.figure.figure_builder import (
                    resolve_template_override,
                )

                if color_by_group:
                    # Annotate on the LazyFrame so "split box/histogram by
                    # group" stays a scan-level pushdown — no rows materialise.
                    scan_schema = scan.collect_schema()
                    group_expr = group_annotation_expr(
                        group_defs, scan_schema.names(), dict(scan_schema)
                    )
                    if group_expr is not None:
                        scan = scan.with_columns(group_expr)
                        if not include_other:
                            scan = scan.filter(pl.col(GROUP_COLUMN) != OTHER_LABEL)
                        group_colored = True
                    else:
                        # No group column in this frame: render ungrouped, and
                        # replan without the color override (the grouped plan
                        # groups by a column the scan doesn't have).
                        dict_kwargs = original_dict_kwargs
                        agg_plan = plan_aggregation(visu_type, dict_kwargs)
                elif color_by_column:
                    # The color-by column is a real column, so the scan needs no
                    # annotation — just a schema check with the same
                    # revert-and-replan contract as groups.
                    if color_by_column["column_name"] in scan.collect_schema().names():
                        column_colored = color_by_column["column_name"]
                    else:
                        dict_kwargs = original_dict_kwargs
                        agg_plan = plan_aggregation(visu_type, dict_kwargs)
                if agg_plan is not None:
                    agg_fig = build_aggregated_figure(
                        scan,
                        agg_plan,
                        theme,
                        render_stats,
                        template_override=resolve_template_override(dict_kwargs.get("template")),
                    )
                if agg_fig is None:
                    # The reduction fell through to the row loader below, which
                    # re-checks/re-applies the override itself — reset so it does.
                    group_colored = False
                    column_colored = None

    df = None
    if agg_fig is None and code_sample_cap:
        df = _load_uniform_sample(
            wf_oid, str(dc_id), filter_metadata, init_data, code_sample_cap, render_stats
        )
    if agg_fig is None and df is None:
        df = load_deltatable_lite(
            workflow_id=wf_oid,
            data_collection_id=str(dc_id),
            metadata=filter_metadata or None,
            select_columns=select_columns,
            limit_rows=limit_rows,
            init_data=init_data,
        )
    # Row-loader path: the overrides are (re-)applied here when the scan-level
    # aggregation didn't run or didn't take them. The two modes are mutually
    # exclusive by construction (``color_by_column`` is only sanitized when
    # ``color_by_group`` is off), so one elif covers both.
    if agg_fig is None and df is not None:
        if color_by_group and not group_colored:
            # Annotate AFTER the load, never inside it — the frame caches key on
            # filter metadata only, and this keeps grouped/ungrouped requests
            # sharing one cached frame (see services/figure/groups.py). Sampling
            # happens later inside `create_figure_from_data`, so the sampled
            # subset keeps its labels.
            group_expr = group_annotation_expr(group_defs, df.columns, dict(df.schema))
            if group_expr is not None:
                df = df.with_columns(group_expr)
                if not include_other:
                    df = df.filter(pl.col(GROUP_COLUMN) != OTHER_LABEL)
                if code_group_optin:
                    # Same kwargs, handed over rather than applied: the author's
                    # code decides which px call they land in.
                    code_group_kwargs = _grouped_kwargs({})
                    code_group_by = [GROUP_COLUMN]
                else:
                    # The agg path may have reverted dict_kwargs (scan lacked the
                    # group column) before falling through to this loader; re-apply
                    # so the kwargs and the flag can't disagree.
                    dict_kwargs = _grouped_kwargs(original_dict_kwargs)
                group_colored = True
            else:
                dict_kwargs = original_dict_kwargs
        elif color_by_column and column_colored is None:
            # Same contract as groups on the row path: apply only when the
            # loaded frame really carries the column, re-applying from the
            # originals in case the agg path reverted (kwargs and flag must
            # agree).
            if color_by_column["column_name"] in df.columns:
                if code_group_optin:
                    # Handed over, not applied. Same two names the group path
                    # uses, so an author writes one idiom and it answers both
                    # halves of the "Colour by" control.
                    code_group_kwargs = _column_kwargs({})
                    code_group_by = [color_by_column["column_name"]]
                else:
                    dict_kwargs = _column_kwargs(original_dict_kwargs)
                column_colored = color_by_column["column_name"]
            else:
                dict_kwargs = original_dict_kwargs
    load_ms = int((time.monotonic() - started) * 1000)

    _ensure_mantine_templates()

    from depictio.api.v1.services.figure.figure_builder import (
        create_figure_from_data,
        process_code_mode_figure,
    )

    build_started = time.monotonic()
    code_error: str | None = None
    if agg_fig is not None:
        # Already built by the aggregation path above; nothing left to do.
        fig = agg_fig
    elif mode == "code":
        ok, fig, detected = process_code_mode_figure(
            code_content,
            df,
            theme,
            "viewer",
            extra_globals={
                CODE_GROUP_KWARGS: code_group_kwargs,
                CODE_GROUP_BY: code_group_by,
            },
        )
        if not ok:
            # `process_code_mode_figure` returns `(False, error_fig, None)` when
            # the user code raises (e.g. unknown column name). The error_fig
            # carries a user-facing annotation with the actual Plotly error.
            # Surface that to the preview rather than masking it as a generic
            # 500 — the React side will render the annotation just like a
            # normal figure, so the user sees what went wrong.
            if fig is None:
                raise RuntimeError("Code-mode figure failed: no code provided.")
            # Pull the human-readable error out of the annotation the helper
            # embedded so the React Code-mode Status alert can flip to red
            # with the actual message instead of falsely claiming success.
            try:
                annotations = fig.layout.annotations or ()
                for ann in annotations:
                    text = getattr(ann, "text", "") or ""
                    if "Code execution error" in text:
                        code_error = text.split("Code execution error:", 1)[-1].strip()
                        break
                if not code_error and annotations:
                    code_error = str(annotations[0].text)
            except Exception:
                code_error = "Code execution failed."
            logger.info(
                f"celery_tasks.build_figure_preview: code-mode execution failed: {code_error}"
            )
        if detected:
            visu_type = detected
    else:
        # Render path uses `selection_*`; preview path doesn't pass them. The
        # underlying helper takes both as kwargs with safe defaults, so always
        # forwarding is fine and keeps the call site type-checkable.
        fig = create_figure_from_data(
            df=df,
            visu_type=visu_type,
            dict_kwargs=dict_kwargs,
            theme=theme,
            selection_enabled=selection_enabled,
            selection_column=selection_column,
            max_points=effective_max_points,
            render_stats=render_stats,
        )
    build_ms = int((time.monotonic() - build_started) * 1000)

    # Both build paths converge here, which is where a faceted figure is made
    # readable at tile size — see `tidy_facet_layout`. Unconditional: whether a
    # figure has facets is a property of the figure, not of the request, and a
    # code figure may lay its own out with grouping switched off entirely. The
    # helper reads the axes and returns untouched when there is one panel.
    try:
        tidy_facet_layout(fig)
    except Exception as exc:  # never lose a figure to its own tidying
        logger.warning(f"celery_tasks.build_figure_preview: facet tidy skipped: {exc}")

    if hasattr(fig, "to_json"):
        fig_dict = json.loads(fig.to_json())
    else:
        fig_dict = fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")

    logger.info(
        f"celery_tasks.build_figure_preview wf={wf_id} dc={dc_id} mode={mode} "
        f"visu={visu_type} load_ms={load_ms} build_ms={build_ms} "
        f"aggregated={bool(render_stats.get('aggregated'))}"
    )

    # Sampling accounting for the "showing N of M points" indicator. A figure is
    # "sampled" when either the UI-mode point-plot downsample fired, or the
    # scan-level load cap truncated the source (code mode / very large point
    # plot). Only run the extra count query when something was actually capped —
    # a full load or an uncapped small frame needs no total lookup.
    loaded_height = df.height if df is not None and hasattr(df, "height") else 0
    displayed_count = int(
        render_stats.get("displayed", render_stats.get("rows_displayed", loaded_height))
    )
    # An aggregation never truncates: it reads every row, it just doesn't keep
    # them. Only the row-returning loader can hit its cap.
    load_truncated = df is not None and bool(limit_rows) and loaded_height >= limit_rows
    was_sampled = bool(render_stats.get("sampled", False)) or load_truncated
    if render_stats.get("total_rows") is not None:
        # The aggregation path already knows the pre-sample total (it needed the
        # row count to size the subsample), so skip the extra count query.
        total_data_count = max(int(render_stats["total_rows"]), displayed_count)
    elif was_sampled and not full_load:
        total_data_count = max(
            count_deltatable_lite(
                workflow_id=wf_oid,
                data_collection_id=str(dc_id),
                metadata=filter_metadata or None,
                init_data=init_data,
            ),
            displayed_count,
        )
    else:
        total_data_count = displayed_count

    response_metadata: dict[str, Any] = {
        "visu_type": visu_type,
        "filter_applied": bool(filter_metadata),
        # Sampling indicator fields consumed by the React viewer badge.
        "was_sampled": was_sampled,
        "displayed_data_count": displayed_count,
        "total_data_count": total_data_count,
        "full_data_loaded": full_load or not was_sampled,
        # True when the figure was colored by the caller's selection groups —
        # the client surfaces it because group coloring overrides `color`.
        "group_colored": group_colored,
        # Column the global "Color by" override actually applied to this frame
        # (None when the frame doesn't carry the column or the mode is off).
        "column_colored": column_colored,
        # Per-stage timings ride back through both the inline and the Celery
        # result-backend paths; the render endpoint lifts them into X-* headers
        # for the benchmark harness. Unknown key — the React client ignores it.
        "timings": {
            "load_ms": load_ms,
            "build_ms": build_ms,
            # Benchmark attribution: how many rows the render actually had to
            # read, and whether a scan-level aggregate served it. ``rows_loaded``
            # is 0 on the aggregate path precisely because that's the win.
            "rows_loaded": loaded_height,
            "rows_displayed": displayed_count,
            "aggregated": bool(render_stats.get("aggregated")),
            "frame_bytes": df.estimated_size() if df is not None else 0,
        },
    }
    if code_error:
        # Surface the underlying Plotly error to the React Code-mode Status
        # alert so it flips to red. The error figure is still in `figure` so
        # the preview pane shows the in-figure annotation as well.
        response_metadata["error"] = code_error
    return {"figure": fig_dict, "metadata": response_metadata}


@celery_app.task(name="depictio.figure.analyze_code", soft_time_limit=10, time_limit=20)
def analyze_figure_code(code: str) -> dict:
    """Heavy body of `POST /figure/analyze_code` — wraps `analyze_constrained_code`."""
    from depictio.api.v1.services.figure.code_mode import analyze_constrained_code

    code = (code or "").strip()
    if not code:
        return {"is_valid": False, "error": "Empty code."}

    try:
        result = analyze_constrained_code(code)
    except Exception as e:
        return {"is_valid": False, "error": f"Analysis failed: {e}"}

    if isinstance(result, dict):
        return {
            "is_valid": bool(result.get("is_valid", True)),
            "error": result.get("error"),
            "visu_type": result.get("visu_type"),
            "dict_kwargs": result.get("dict_kwargs") or {},
            "warnings": result.get("warnings") or [],
        }
    if isinstance(result, tuple):
        is_valid = bool(result[0])
        return {
            "is_valid": is_valid,
            "error": None if is_valid else "Code structure failed validation.",
            "visu_type": result[1] if len(result) > 1 else None,
            "dict_kwargs": (result[2] if len(result) > 2 else {}) or {},
            "warnings": result[3] if len(result) > 3 else [],
        }
    return {"is_valid": True, "dict_kwargs": {}, "visu_type": None, "warnings": []}


@celery_app.task(name="depictio.multiqc.build_preview", soft_time_limit=120, time_limit=180)
def build_multiqc_preview(payload: dict) -> dict:
    """Heavy body of `POST /multiqc/preview`.

    Input shape:
        {
          "s3_locations": [...],
          "module": str, "plot": str,
          "dataset": str | None,
          "theme": "light" | "dark",
          "dc_id": str | None
        }
    """
    from depictio.api.cache import get_cache
    from depictio.api.v1.services import multiqc_prerender_store
    from depictio.api.v1.services.multiqc.figures import (
        MULTIQC_CACHE_TTL_SECONDS,
        _generate_figure_cache_key,
        create_multiqc_plot,
    )

    s3_locations = payload.get("s3_locations") or []
    module = str(payload.get("module"))
    plot = str(payload.get("plot"))
    dataset = payload.get("dataset")
    theme = payload.get("theme") or "light"
    dc_id = payload.get("dc_id")

    started = time.monotonic()

    # Compute the bare cache key once for non-general_stats DC requests — used
    # by the Redis/disk read paths AND the cold-build writeback below so the
    # next click on the same plot hits the warm cache instead of rebuilding.
    cache = get_cache()
    bare_key: str | None = None
    if dc_id and module != "general_stats" and plot != "general_stats":
        bare_key = _generate_figure_cache_key(
            s3_locations,
            module,
            plot,
            str(dataset) if dataset else None,
            theme,
            dc_id=str(dc_id),
        )

        # Short-circuit if the prerender pipeline has already produced this
        # exact (dc, module, plot, dataset, theme) figure. The dashboard render
        # endpoint does the same Redis-then-disk lookup.
        cached_fig = cache.get(bare_key)
        if cached_fig is not None:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                f"celery_tasks.build_multiqc_preview cache_hit=redis dc={dc_id} "
                f"module={module} plot={plot} elapsed_ms={elapsed_ms}"
            )
            if isinstance(cached_fig, dict) and "layout" in cached_fig:
                cached_fig["layout"].setdefault("uirevision", "persistent")
            return {
                "figure": cached_fig,
                "metadata": {"module": module, "plot": plot, "dataset_id": dataset},
            }
        disk_fig = multiqc_prerender_store.read_figure(str(dc_id), bare_key)
        if disk_fig is not None:
            try:
                cache.set(bare_key, disk_fig, ttl=MULTIQC_CACHE_TTL_SECONDS)
            except Exception:
                pass
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                f"celery_tasks.build_multiqc_preview cache_hit=disk dc={dc_id} "
                f"module={module} plot={plot} elapsed_ms={elapsed_ms}"
            )
            if isinstance(disk_fig, dict) and "layout" in disk_fig:
                disk_fig["layout"].setdefault("uirevision", "persistent")
            return {
                "figure": disk_fig,
                "metadata": {"module": module, "plot": plot, "dataset_id": dataset},
            }

    # General Stats Table preview branch — ``general_stats`` is not a real
    # MultiQC module so ``create_multiqc_plot`` would raise. Mirror the Dash
    # design callback (multiqc_component/callbacks/design.py:299): build the
    # JSON payload and return its violin figure so the React preview renders
    # the same Plotly trace the runtime ``MultiQCGeneralStats`` shows.
    if module == "general_stats" or plot == "general_stats":
        from depictio.api.v1.services.multiqc.figures import _get_local_path_for_s3
        from depictio.api.v1.services.multiqc.general_stats_payload import (
            build_general_stats_payload,
        )

        if not s3_locations:
            raise ValueError("No s3_locations resolved for general_stats preview.")
        # The violin figure is built with `template="mantine_light"`
        # (services/multiqc/general_stats_payload.py). Those templates are
        # registered per-process, so without this the worker raises "Invalid
        # value of type 'builtins.str' ... for the 'template' property".
        _ensure_mantine_templates()
        parquet_path = _get_local_path_for_s3(s3_locations[0])
        gs_payload = build_general_stats_payload(parquet_path=parquet_path, show_hidden=True)
        violin = gs_payload.get("modes", {}).get("mean", {}).get("violin_figure") or {
            "data": [],
            "layout": {},
        }
        if isinstance(violin, dict) and "layout" in violin:
            violin["layout"].setdefault("uirevision", "persistent")
        build_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            f"celery_tasks.build_multiqc_preview general_stats "
            f"samples={len(gs_payload.get('all_samples', []))} build_ms={build_ms}"
        )
        return {
            "figure": violin,
            "metadata": {
                "module": module,
                "plot": plot,
                "dataset_id": dataset,
                "is_general_stats": True,
                "sample_count": len(gs_payload.get("all_samples", [])),
            },
        }

    fig = create_multiqc_plot(
        s3_locations=s3_locations,
        module=module,
        plot=plot,
        dataset_id=str(dataset) if dataset else None,
        theme=theme,
        dc_id=str(dc_id) if dc_id else None,
    )
    build_ms = int((time.monotonic() - started) * 1000)

    fig_dict = json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")

    # Writeback after a cold build so the next click for the same plot hits
    # disk/Redis instead of paying 60s again. Same bare_key used by the read
    # paths above, so the next call's cache_hit=disk lookup finds it.
    if bare_key is not None:
        try:
            multiqc_prerender_store.write_figure(str(dc_id), bare_key, fig_dict)
        except Exception as exc:
            logger.warning(
                f"build_multiqc_preview: disk writeback failed dc={dc_id} key={bare_key}: {exc}"
            )
        try:
            cache.set(bare_key, fig_dict, ttl=MULTIQC_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning(
                f"build_multiqc_preview: redis writeback failed dc={dc_id} key={bare_key}: {exc}"
            )

    logger.info(
        f"celery_tasks.build_multiqc_preview module={module} plot={plot} "
        f"dataset={dataset} build_ms={build_ms}"
    )

    return {
        "figure": fig_dict,
        "metadata": {"module": module, "plot": plot, "dataset_id": dataset},
    }


@celery_app.task(name="depictio.deltatables.preview", soft_time_limit=60, time_limit=120)
def preview_deltatable(payload: dict) -> dict:
    """Heavy body of `GET`/`POST /deltatables/preview/{id}`.

    Input shape:
        {"delta_table_location": str, "limit": int,
         "filter_metadata": [...]}    # optional, cleaned InteractiveFilter list

    With ``filter_metadata``, both the returned rows and ``total_rows`` are
    computed on the filtered frame, so the builder's "Showing X of N rows"
    reflects the dashboard's active filters.
    """
    import polars as pl

    from depictio.api.v1.deltatables_utils import apply_filters_to_scan
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import sanitize_for_json
    from depictio.api.v1.s3 import polars_s3_config

    delta_loc = payload["delta_table_location"]
    limit = max(1, min(int(payload.get("limit", 100)), 1000))
    filter_metadata = payload.get("filter_metadata") or []

    started = time.monotonic()
    scan = apply_filters_to_scan(
        pl.scan_delta(delta_loc, storage_options=polars_s3_config), filter_metadata
    )
    df = scan.head(limit).collect()
    total_rows, total_cols = scan.collect().shape
    rows = sanitize_for_json(df.to_dicts())
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        f"celery_tasks.preview_deltatable rows={limit}/{total_rows} cols={total_cols} "
        f"filters={len(filter_metadata)} elapsed_ms={elapsed_ms}"
    )

    return {
        "columns": df.columns,
        "rows": rows,
        "total_rows": total_rows,
        "total_columns": total_cols,
        "filter_applied": bool(filter_metadata),
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_embedding",
    soft_time_limit=600,
    time_limit=900,
)
def compute_embedding(payload: dict) -> dict:
    """Live dim-reduction for the Embedding advanced viz.

    Loads a wide sample×feature matrix DC, projects it via run_pca /
    run_umap / run_tsne / run_pcoa from depictio.recipes.lib.dimreduction,
    and returns the 2D coords in the canonical embedding shape (column-
    oriented dict).

    Input payload (JSON-serialisable):
        {
          "wf_id": str,
          "dc_id": str,                # the feature-matrix DC
          "feature_id_col": str,       # sample-id column in the matrix
          "method": "pca" | "umap" | "tsne" | "pcoa",
          "params": dict,              # per-method tunables
          "filter_metadata": [...],    # sidebar filters (optional)
        }

    Output:
        {
          "sample_ids": [str],
          "dim_1": [float],
          "dim_2": [float],
          "dim_3": [float],  # only when params.n_components == 3
        }
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.recipes.lib.dimreduction import run_pca, run_pcoa, run_tsne, run_umap

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    feature_id_col = payload.get("feature_id_col") or "sample_id"
    method = (payload.get("method") or "pca").lower()
    params = payload.get("params") or {}
    filter_metadata = payload.get("filter_metadata") or []
    # Columns to pass through unchanged from the feature DC alongside the
    # computed (dim_1, dim_2). Used by the renderer to overlay cluster /
    # colour annotations on the live embedding without an extra round-trip.
    extra_cols: list[str] = list(payload.get("extra_cols") or [])

    if not wf_id or not dc_id:
        raise ValueError("compute_embedding: wf_id and dc_id are required")
    if method not in {"pca", "umap", "tsne", "pcoa"}:
        raise ValueError(f"compute_embedding: unsupported method {method!r}")

    # Resolve delta location via Mongo (same pattern as build_figure_preview
    # — keeps the Celery worker self-contained, no HTTP fallbacks).
    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_embedding: feature DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_embedding[%s]: loaded %d rows in %dms", method, df.height, load_ms)

    # Stash any pass-through columns the renderer asked for (e.g. cluster /
    # group labels for colour-coding the embedding) before reducing to the
    # numeric feature matrix.
    import polars as pl

    passthrough: dict[str, list] = {}
    if extra_cols:
        present_extras = [c for c in extra_cols if c in df.columns]
        for col in present_extras:
            passthrough[col] = df.get_column(col).to_list()

    # Reduce to sample_id + numeric features. Polars dtype check filters
    # out string/bool columns so the dim-reduction helpers don't crash on
    # non-numeric input.
    numeric_dtypes = {
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    }
    # Annotation columns are overlays, never features. `extra_cols` is exactly
    # the renderer's colour-by / cluster / hover picks, and a numeric one lands
    # in the feature matrix unless excluded here — on the clustering showcase
    # the annotation column `color` is a Float64 derived from feat_0, so PCA /
    # UMAP were being fed the very annotation the plot exists to illustrate and
    # the projection ended up "explaining" its own colouring. They still reach
    # the renderer through `passthrough` above; they are just not projected on.
    annotation_cols = set(extra_cols)
    feature_cols = [
        c
        for c in df.columns
        if c != feature_id_col and c not in annotation_cols and df[c].dtype in numeric_dtypes
    ]
    if not feature_cols:
        raise ValueError("compute_embedding: no numeric feature columns found in the matrix")
    excluded = [c for c in extra_cols if c in df.columns and df[c].dtype in numeric_dtypes]
    if excluded:
        logger.info(
            "compute_embedding[%s]: excluded annotation column(s) %s from the feature matrix",
            method,
            excluded,
        )
    df = df.select([feature_id_col] + feature_cols)

    # Renderer requests `n_components` (2 or 3) via the params dict; clamped
    # to [2, 3] because that's what the renderer can plot.
    n_components = int(params.get("n_components", 2))
    if n_components not in (2, 3):
        n_components = 2

    runners = {
        "pca": (run_pca, {"n_components": n_components, "scale": True}),
        "umap": (
            run_umap,
            {
                "n_components": n_components,
                "n_neighbors": int(params.get("n_neighbors", 15)),
                "min_dist": float(params.get("min_dist", 0.1)),
                "metric": str(params.get("metric", "euclidean")),
            },
        ),
        "tsne": (
            run_tsne,
            {
                "n_components": n_components,
                "perplexity": float(params.get("perplexity", 30.0)),
                "n_iter": int(params.get("n_iter", 1000)),
                "metric": str(params.get("metric", "euclidean")),
            },
        ),
        "pcoa": (
            run_pcoa,
            {"n_components": n_components, "distance": str(params.get("distance", "bray_curtis"))},
        ),
    }
    runner, kwargs = runners[method]

    compute_started = time.monotonic()
    if method == "pcoa":
        # PCoA's Bray-Curtis distance requires non-negative values; shift
        # the matrix into the positive orthant if any negatives are present.
        import polars as pl

        mins = [df.get_column(c).min() for c in feature_cols]
        global_min = min(float(m if m is not None else 0.0) for m in mins)
        if global_min < 0:
            df = df.with_columns([(pl.col(c) - global_min).alias(c) for c in feature_cols])
    coords = runner(df, **kwargs)
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_embedding[%s]: produced %d coords in %dms (params=%s)",
        method,
        coords.height,
        compute_ms,
        params,
    )

    result = {
        "sample_ids": coords["sample_id"].to_list(),
        "dim_1": coords["dim_1"].to_list(),
        "dim_2": coords["dim_2"].to_list(),
        "extras": passthrough,  # {col: [values]} aligned with sample_ids
        "method": method,
        "params": params,
        "row_count": int(coords.height),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }
    if n_components == 3 and "dim_3" in coords.columns:
        result["dim_3"] = coords["dim_3"].to_list()
    return result


@celery_app.task(
    name="depictio.advanced_viz.compute_complex_heatmap",
    soft_time_limit=300,
    time_limit=600,
)
def compute_complex_heatmap(payload: dict) -> dict:
    """Build a ComplexHeatmap figure server-side via plotly-complexheatmap.

    Input payload:
        {
          "wf_id": str,
          "dc_id": str,                # the matrix DC
          "index_column": str,         # row-label column
          "value_columns": [str] | null,
          "row_annotation_cols": [str],
          "cluster_rows": bool,
          "cluster_cols": bool,
          "cluster_method": str,       # ward / single / complete / average
          "cluster_metric": str,       # euclidean / correlation / cosine
          "normalize": str,            # none / row_z / col_z / log1p
          "colorscale": str | null,
          "filter_metadata": [...],
        }

    Output:
        {
          "figure": <plotly figure dict>,   # straight to react-plotly.js
          "row_count": int,
          "col_count": int,
          "load_ms": int,
          "compute_ms": int,
        }
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    index_column = payload.get("index_column") or "sample_id"
    value_columns = payload.get("value_columns")
    row_annotation_cols = list(payload.get("row_annotation_cols") or [])
    # Column annotations: pre-built per-column category map shipped by the
    # dashboard config. Shape: {annotation_name: {col_label: category_value}}.
    # Aligned to value_columns order below and forwarded as a top strip.
    col_annotations_map = payload.get("col_annotations") or None
    cluster_rows = bool(payload.get("cluster_rows", True))
    cluster_cols = bool(payload.get("cluster_cols", True))
    cluster_method = str(payload.get("cluster_method") or "ward")
    cluster_metric = str(payload.get("cluster_metric") or "euclidean")
    normalize = str(payload.get("normalize") or "none")
    colorscale = payload.get("colorscale")
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_complex_heatmap: wf_id and dc_id are required")

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_complex_heatmap: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    logger.info(
        "compute_complex_heatmap: dispatch dc_id=%s filter_count=%d filter_summary=%s",
        dc_id,
        len(filter_metadata),
        [
            {
                "col": (f.get("metadata") or {}).get("column_name") or f.get("column_name"),
                "type": (f.get("metadata") or {}).get("interactive_component_type")
                or f.get("interactive_component_type"),
                "value": f.get("value"),
            }
            for f in filter_metadata
        ],
    )
    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_complex_heatmap: loaded %d rows in %dms", df.height, load_ms)

    # Convert polars → pandas for plotly-complexheatmap (it accepts both but
    # pandas is its primary input). Drop non-numeric columns from the value
    # set if value_columns wasn't supplied.
    import polars as pl

    numeric_dtypes = {
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    }
    if value_columns is None:
        value_columns = [
            c
            for c in df.columns
            if c != index_column and c not in row_annotation_cols and df[c].dtype in numeric_dtypes
        ]
    if not value_columns:
        raise ValueError("compute_complex_heatmap: no numeric value columns found")

    # Wide-matrix sample subsetting: sample IDs are MATRIX COLUMNS, not rows,
    # so the row-filter skipped them silently. Mirror the subset by matching
    # filter VALUES against the column names — the previous version only
    # honoured filters literally named `sample`/`sample_id`, which is not what
    # a metadata pick (`ID`) or a map lasso sends.
    value_columns = (
        _narrow_wide_matrix_columns(value_columns, filter_metadata, what="heatmap columns")
        or value_columns
    )

    pdf = df.select([index_column] + value_columns + row_annotation_cols).to_pandas()

    # Empty/null categorical annotation values (e.g. an unclassified taxon with a
    # blank Kingdom) would otherwise reach the library as a "" category that has
    # no entry in our colour map → hard ``KeyError('')`` in CategoricalTrack. Fold
    # them into a single explicit "Unclassified" label here so the category set
    # and the colour universe (built below) always agree.
    _ANNO_PLACEHOLDER = "Unclassified"
    for _ann_col in row_annotation_cols:
        if _ann_col in pdf.columns and pdf[_ann_col].dtype.kind in ("O", "U", "S"):
            pdf[_ann_col] = pdf[_ann_col].fillna(_ANNO_PLACEHOLDER).replace("", _ANNO_PLACEHOLDER)

    # Translate depictio normalize vocab → plotly-complexheatmap normalize_data
    # vocab. The renderer/config offers row_z / col_z / log1p / none; the
    # library only knows row / column / global / none. log1p has no library
    # equivalent — apply it to the value matrix here and pass "none" through.
    import math

    normalize_for_lib = {"none": "none", "row_z": "row", "col_z": "column"}.get(normalize, "none")
    if normalize == "log1p":
        for _col in value_columns:
            pdf[_col] = pdf[_col].astype(float).apply(math.log1p)

    compute_started = time.monotonic()
    # Import here so the worker startup doesn't pay the cost unless this
    # task is actually invoked.
    from plotly_complexheatmap import ComplexHeatmap

    # A dendrogram needs at least two leaves. Both axes can be narrowed to one
    # by an ordinary filter — pick a single sample and the wide-matrix column
    # subset leaves one column; pick a single Phylum and the row filter leaves
    # one row — so this is a click away, not an edge case. Clustering is a
    # presentation choice, so drop it rather than failing the tile.
    if len(value_columns) < 2 and cluster_cols:
        logger.info("not clustering heatmap columns: %d column(s) left", len(value_columns))
        cluster_cols = False
    if len(pdf) < 2 and cluster_rows:
        logger.info("not clustering heatmap rows: %d row(s) left", len(pdf))
        cluster_rows = False

    hm_kwargs: dict = {
        "index_column": index_column,
        "value_columns": value_columns,
        "cluster_rows": cluster_rows,
        "cluster_cols": cluster_cols,
        "cluster_method": cluster_method,
        "cluster_metric": cluster_metric,
        "normalize": normalize_for_lib,
    }
    if row_annotation_cols:
        # Stable categorical colour map per annotation column — keyed on the
        # FULL distinct-value universe (unfiltered) so a sidebar filter that
        # narrows the heatmap to a single cluster doesn't reshuffle the
        # annotation track's colour for that cluster. Matches the frontend
        # ``stableColorMap`` behaviour used by the scatter / rarefaction /
        # taxonomy renderers.
        # Set2 pastel — same palette family used by ``compute_upset`` annotation
        # tracks. Numeric columns are left untouched (library auto-picks bars).
        _STABLE_PALETTE = [
            "#66c2a5",
            "#fc8d62",
            "#8da0cb",
            "#e78ac3",
            "#a6d854",
            "#ffd92f",
            "#e5c494",
            "#b3b3b3",
        ]
        # Load the UNFILTERED annotation columns once via a lazy scan so the
        # universe stays invariant under sidebar filtering. Cheap — single
        # column read, no materialisation beyond unique().
        try:
            from depictio.api.v1.s3 import polars_s3_config

            unfiltered_lazy = pl.scan_delta(
                dt_doc["delta_table_location"], storage_options=polars_s3_config
            )
            anno_universes: dict[str, list[str]] = {}
            for ann_col in row_annotation_cols:
                if ann_col not in pdf.columns:
                    continue
                series = pdf[ann_col]
                if series.dtype.kind not in ("U", "S", "O"):
                    continue
                uniq_pl = (
                    unfiltered_lazy.select(pl.col(ann_col)).unique().collect()[ann_col].to_list()
                )
                # Fold empty/null into the same "Unclassified" label used on the
                # data column above so every rendered category has a colour.
                anno_universes[ann_col] = sorted(
                    {(str(v) if v not in ("", None) else _ANNO_PLACEHOLDER) for v in uniq_pl}
                )
        except Exception as exc:  # pragma: no cover - logged + falls back
            logger.warning(
                "compute_complex_heatmap: unique-value lookup for annotations failed (%s); "
                "colours may shift under filtering",
                exc,
            )
            anno_universes = {}

        annotations_spec: dict[str, dict[str, Any]] = {}
        for ann_col in row_annotation_cols:
            if ann_col in anno_universes:
                universe = anno_universes[ann_col]
                # Library silently drops ``colors`` when ``type`` is omitted
                # (the dict path falls through to ``_infer`` which doesn't pass
                # colors). Force ``type="categorical"`` so our stable palette
                # actually reaches CategoricalTrack.
                annotations_spec[ann_col] = {
                    "type": "categorical",
                    "colors": {
                        v: _STABLE_PALETTE[i % len(_STABLE_PALETTE)] for i, v in enumerate(universe)
                    },
                }
            else:
                # Numeric / unknown — let the library auto-pick the track type.
                annotations_spec[ann_col] = {}
        hm_kwargs["row_annotations"] = annotations_spec
    # Column annotations — align dashboard-supplied {col: category} maps to the
    # current value_columns order, then forward as a top strip.
    #
    # Palette choice: Dark2 (saturated sibling of the Set2 pastel used for the
    # row-annotation track). Same hue families, different value range — so col
    # vs row tracks read as distinct families at a glance instead of looking
    # like two views of the same dimension. Source: matplotlib qualitative
    # Dark2.
    #
    # Dashboards can override per-annotation via the `col_annotation_colors`
    # payload field (shape: {annotation_name: {value: hex}}), e.g. to pin
    # habitat → Set1 across PCoA + UpSet + heatmap.
    if col_annotations_map and isinstance(col_annotations_map, dict):
        _COL_PALETTE = [
            "#1b9e77",
            "#d95f02",
            "#7570b3",
            "#e7298a",
            "#66a61e",
            "#e6ab02",
            "#a6761d",
            "#666666",
        ]
        col_annotation_colors = payload.get("col_annotation_colors") or {}
        col_ann_kwargs: dict[str, Any] = {}
        for ann_name, value_map in col_annotations_map.items():
            if not isinstance(value_map, dict):
                continue
            ordered_values = [str(value_map.get(c, "—")) for c in value_columns]
            uniq = sorted(set(v for v in ordered_values if v not in ("", "—")))
            # Dashboard-supplied palette override wins; otherwise palette-cycle.
            override = (
                (col_annotation_colors.get(ann_name) or {})
                if isinstance(col_annotation_colors.get(ann_name), dict)
                else {}
            )
            colors = {
                v: override.get(v) or _COL_PALETTE[i % len(_COL_PALETTE)]
                for i, v in enumerate(uniq)
            }
            colors.setdefault("—", "rgba(150,150,150,0.4)")
            col_ann_kwargs[ann_name] = {
                "values": ordered_values,
                "type": "categorical",
                "colors": colors,
            }
        if col_ann_kwargs:
            hm_kwargs["col_annotations"] = col_ann_kwargs
    if colorscale:
        hm_kwargs["colorscale"] = colorscale

    hm = ComplexHeatmap.from_dataframe(pdf, **hm_kwargs)
    fig = hm.to_plotly()
    # Margin tweak for the React viewer: b=110 so the x-tick labels, which the
    # library sizes from a 6px-per-char approximation, aren't clipped when a
    # rotated sample id runs longer than that estimate (~14 chars @10pt).
    #
    # The right margin is left exactly as the library computed it. It sizes that
    # side from the widest row label plus the widest of the legend / colorbar,
    # and it now anchors both of those to the figure's right edge, so the reserved
    # band holds regardless of the tile width we render into. Forcing a floor here
    # would only pad the figure with empty space.
    try:
        existing_margin = fig.layout.margin
        new_margin = dict(
            l=getattr(existing_margin, "l", None) or 60,
            r=getattr(existing_margin, "r", None) or 200,
            t=getattr(existing_margin, "t", None) or 60,
            b=max(getattr(existing_margin, "b", 50) or 50, 110),
        )
        fig.update_layout(margin=new_margin)
    except Exception:  # pragma: no cover — defensive against library-shape changes
        fig.update_layout(margin=dict(l=60, r=200, t=60, b=110))
    # Round-trip through plotly's JSON serializer so numpy ndarrays in trace
    # arrays / shape coords become plain lists/numbers. Without this, Celery's
    # JSON result backend chokes with "Object of type ndarray is not JSON
    # serializable" and the task can't store its result.
    import json as _json

    import plotly.io as _pio

    fig_dict = _json.loads(_pio.to_json(fig))
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_complex_heatmap: %d×%d in %dms",
        len(value_columns),
        len(pdf),
        compute_ms,
    )

    return {
        "figure": fig_dict,
        "row_count": len(pdf),
        "col_count": len(value_columns),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


def _narrow_wide_matrix_columns(
    candidates: list[str], filter_metadata: list | None, *, what: str = "sets"
) -> list[str] | None:
    """Matrix columns left standing once a filter over their NAMES is applied.

    A wide matrix spends one axis on values that are rows everywhere else —
    samples across a heatmap, groups across an UpSet — so a filter on that
    dimension has no row to match and `load_deltatable_lite` skips it. The
    mirror is a column subset, matched by VALUE: a filter whose values are
    column names is that filter, whatever the filter's own column is called.
    That is what makes it survive link translation, where the column name that
    reaches us is the source DC's (`ID`, `sample`, `sample_id`, …) and no list
    of names could be complete.

    Returns None when no filter names columns — leave the caller's choice
    alone — and never an empty list: a filter that selects none of them is a
    filter about something else.
    """
    if not candidates:
        return None
    column_names = {str(c) for c in candidates}
    for f in filter_metadata or []:
        if not isinstance(f, dict):
            continue
        val = f.get("value")
        if val in (None, [], ""):
            continue
        values = {str(v) for v in val} if isinstance(val, (list, tuple, set)) else {str(val)}
        hit = column_names & values
        # An empty hit is an unrelated filter; a full hit is a no-op that would
        # only reorder the sets.
        if not hit or hit == column_names:
            continue
        nested = f.get("metadata") or {}
        col = f.get("column_name") or (
            nested.get("column_name") if isinstance(nested, dict) else None
        )
        narrowed = [c for c in candidates if str(c) in hit]
        logger.info(
            "narrowing %s to %d of %d via the %s filter",
            what,
            len(narrowed),
            len(candidates),
            col or "unnamed",
        )
        return narrowed
    return None


def _detect_upset_set_columns(df) -> list[str]:
    """Binary (0/1) columns of an UpSet matrix, in frame order.

    Mirrors what plotly-upset does when `set_columns` is left to auto-detect,
    so a set narrowed here is a set the library would also have drawn. Nulls
    count as absent, and an all-zero column is still a set (an empty one).
    """
    import polars as pl

    detected: list[str] = []
    for name, dtype in zip(df.columns, df.dtypes):
        if not (dtype.is_integer() or dtype == pl.Boolean):
            continue
        uniques = df.get_column(name).drop_nulls().unique().to_list()
        if all(int(v) in (0, 1) for v in uniques):
            detected.append(name)
    return detected


@celery_app.task(
    name="depictio.advanced_viz.compute_upset",
    soft_time_limit=300,
    time_limit=600,
)
def compute_upset(payload: dict) -> dict:
    """Build an UpSet plot figure server-side via plotly-upset.

    Input payload:
        {
          "wf_id": str, "dc_id": str,
          "set_columns": [str] | null,
          "sort_by": "cardinality" | "degree" | "degree-cardinality" | "input",
          "sort_order": "descending" | "ascending",
          "min_size": int, "max_degree": int | null,
          "show_set_sizes": bool,
          "color_intersections_by": "none" | "set" | "degree",
          "filter_metadata": [...],
        }
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    set_columns = payload.get("set_columns")
    sort_by = str(payload.get("sort_by") or "cardinality")
    sort_order = str(payload.get("sort_order") or "descending")
    min_size = int(payload.get("min_size", 1))
    max_degree = payload.get("max_degree")
    show_set_sizes = bool(payload.get("show_set_sizes", True))
    show_values = bool(payload.get("show_values", False))
    color_intersections_by = payload.get("color_intersections_by") or "none"
    # Optional per-set colour map ({set_name: hex}). Forwarded to UpSetPlot
    # so set-size bars + matrix dots + intersection bars (when
    # color_intersections_by="set") use project-specific palettes — e.g.
    # nf-core/ampliseq habitats: Riverwater #377EB8 / Groundwater #4DAF4A /
    # Sediment #E41A1C / Soil #FF7F00.
    set_colors = payload.get("set_colors") or None
    # Extra annotation tracks (per-intersection summaries). User-selected
    # non-set columns from the DC schema; library auto-detects numeric vs
    # categorical and renders a track per column above the intersection bars.
    annotation_cols = payload.get("annotation_cols") or []
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_upset: wf_id and dc_id are required")

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_upset: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_upset: loaded %d rows in %dms", df.height, load_ms)

    # Wide-matrix set subsetting: the sets are MATRIX COLUMNS, not rows. The
    # grouping values the recipe pivoted on (habitat / locality / treatment —
    # whatever the project's GROUP_COL is) became column NAMES here, so a
    # filter on that column cannot filter rows: the DC has no such column and
    # `load_deltatable_lite` skipped it. Mirror it as a COLUMN filter instead,
    # by intersecting the set columns with the filter's values.
    #
    # Matched by VALUE, not by column name. Nothing in this payload names the
    # recipe's grouping column, and hardcoding one ("habitat") only ever
    # worked for the seed. A filter whose values ARE set names is that filter,
    # whatever it is called; any other filter has an empty intersection and is
    # left alone.
    #
    # `candidate_sets` falls back to the frame's own binary columns because
    # `set_columns` is usually null (the library auto-detects). Gating the
    # narrowing on an explicit `set_columns` made it a no-op for every
    # dashboard that didn't spell the sets out.
    candidate_sets = list(set_columns) if set_columns else _detect_upset_set_columns(df)
    set_columns = _narrow_wide_matrix_columns(candidate_sets, filter_metadata) or set_columns

    pdf = df.to_pandas()
    compute_started = time.monotonic()
    from plotly_upset import UpSetPlot

    kwargs: dict = {
        "sort_by": sort_by,
        "sort_order": sort_order,
        "min_size": min_size,
        "show_set_sizes": show_set_sizes,
        "show_values": show_values,
    }
    if max_degree is not None:
        kwargs["max_degree"] = int(max_degree)
    if color_intersections_by in ("set", "degree"):
        kwargs["color_intersections_by"] = color_intersections_by
    if set_colors:
        kwargs["set_colors"] = set_colors

    # Distinct categorical palette for annotation tracks — picked to avoid
    # collision with the library's default UPSET_PALETTE that drives the
    # set + intersection-bar colouring. Without this, the first feature_group
    # category and the first set (contrastA) draw from the same first colour
    # and the two legends look like they describe the same partition.
    # Source: matplotlib Set2 (pastel qualitative).
    _ANNOTATION_PALETTE = [
        "#66c2a5",
        "#fc8d62",
        "#8da0cb",
        "#e78ac3",
        "#a6d854",
        "#ffd92f",
        "#e5c494",
        "#b3b3b3",
    ]

    # Route through from_dataframe when set_columns and/or annotation_cols
    # are specified — that path resolves annotation specs and wires them
    # into an UpSetAnnotation container. Falls back to the bare constructor
    # for the legacy "binary-only DataFrame" case.
    if annotation_cols or set_columns:
        annotations_spec: dict | list | None
        if annotation_cols:
            # Build {col: {"column": col, "type": ..., "colors": {value: hex}}}
            # for categorical columns so the library uses our pastel palette
            # instead of the default UPSET_PALETTE. Numeric columns get an
            # empty spec — the library auto-picks "box" or "bar" type.
            #
            # The category list is keyed on the UNFILTERED distinct-value
            # universe, not on `pdf`. Derived from the filtered frame, a sidebar
            # filter down to a single category re-derived a one-entry palette
            # and that category jumped to the palette's first colour — which is
            # the "colour scale resets when I filter by annotation" report.
            # Same lazy single-column scan, and the same reason, as the
            # row-annotation universe in `compute_complex_heatmap` above.
            import polars as pl

            anno_universes: dict[str, list] = {}
            try:
                from depictio.api.v1.s3 import polars_s3_config

                unfiltered_lazy = pl.scan_delta(
                    dt_doc["delta_table_location"], storage_options=polars_s3_config
                )
                for col in annotation_cols:
                    if col not in pdf.columns:
                        continue
                    uniq = unfiltered_lazy.select(pl.col(col)).unique().collect()[col].to_list()
                    anno_universes[col] = [v for v in uniq if v not in ("", None)]
            except Exception as exc:  # pragma: no cover - logged + falls back
                logger.warning(
                    "compute_upset: unique-value lookup for annotations failed (%s); "
                    "colours may shift under filtering",
                    exc,
                )
                anno_universes = {}

            annotations_spec = {}
            for col in annotation_cols:
                if col not in pdf.columns:
                    continue
                series = pdf[col]
                spec: dict = {"column": col}
                # Treat object/string columns and small-cardinality ints as
                # categorical — matches the library's _infer_type heuristic.
                # Cardinality is counted on the universe too, so a filter that
                # narrows an int column can't flip its track from box to
                # categorical halfway through a session.
                universe = anno_universes.get(col)
                distinct = len(universe) if universe is not None else int(series.nunique())
                is_string = series.dtype.kind in ("U", "S", "O")
                is_small_int = series.dtype.kind == "i" and distinct <= 10
                if is_string or is_small_int:
                    values = (
                        universe
                        if universe is not None
                        else [v for v in series.dropna().unique() if v not in ("", None)]
                    )
                    cats = sorted(str(v) for v in values)
                    # Pin the track type instead of leaving it to the library.
                    # Left out, the type is re-inferred by the library's own
                    # `_infer_type` — a second heuristic, run on the FILTERED
                    # frame, where the test above ran on the universe. The two
                    # can disagree (an int column with 12 distinct values in the
                    # universe reads as numeric here, but filtered down to 5 the
                    # library calls it categorical and mints its own palette
                    # from UPSET_PALETTE, ignoring the map below). Pinning it
                    # makes the branch that computes `colors` and the branch
                    # that consumes them agree by construction, so the track
                    # can't change shape or palette as filters narrow the data.
                    spec["type"] = "categorical"
                    spec["colors"] = {
                        cat: _ANNOTATION_PALETTE[i % len(_ANNOTATION_PALETTE)]
                        for i, cat in enumerate(cats)
                    }
                annotations_spec[col] = spec
        else:
            annotations_spec = None

        upset = UpSetPlot.from_dataframe(
            pdf,
            set_columns=list(set_columns) if set_columns else None,
            annotations=annotations_spec,
            **kwargs,
        )
    else:
        upset = UpSetPlot(pdf, **kwargs)
    # Same ndarray-safety dance as compute_complex_heatmap: round-trip
    # through plotly.io.to_json so numpy arrays serialise for the Celery
    # JSON result backend.
    import json as _json

    import plotly.io as _pio

    fig_dict = _json.loads(_pio.to_json(upset.to_plotly()))
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info("compute_upset: built figure in %dms", compute_ms)

    return {
        "figure": fig_dict,
        "row_count": len(pdf),
        "set_count": len(set_columns) if set_columns else None,
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_coverage_track",
    soft_time_limit=180,
    time_limit=300,
)
def compute_coverage_track(payload: dict) -> dict:
    """Aggregate coverage values along a coordinate axis.

    Input payload:
        {
          "wf_id": str, "dc_id": str,
          "chromosome_col": str, "position_col": str, "value_col": str,
          "end_col": str | null,
          "sample_col": str | null, "category_col": str | null,
          "chromosomes_filter": [str] | null,
          "samples_filter": [str] | null,
          "smoothing_window": int (0 disables),
          "max_rows": int | null,
          "filter_metadata": [...],
        }

    Returns column-oriented arrays plus summary stats. The renderer builds
    the Plotly figure client-side so settings like y-scale / colour-by
    don't round-trip.
    """
    import polars as pl

    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    chromosome_col = payload.get("chromosome_col")
    position_col = payload.get("position_col")
    value_col = payload.get("value_col")
    end_col = payload.get("end_col")
    sample_col = payload.get("sample_col")
    category_col = payload.get("category_col")
    chromosomes_filter = payload.get("chromosomes_filter")
    samples_filter = payload.get("samples_filter")
    # Mirror the Pydantic CoverageTrackConfig bounds (0..200). The Celery task
    # is reachable from any caller — not just the validated React payload — so
    # clamp defensively rather than trust the input.
    smoothing_window = max(0, min(200, int(payload.get("smoothing_window") or 0)))
    max_rows = int(payload.get("max_rows") or 200_000)
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_coverage_track: wf_id and dc_id are required")
    if not (chromosome_col and position_col and value_col):
        raise ValueError(
            "compute_coverage_track: chromosome_col, position_col, value_col are required"
        )

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_coverage_track: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    project_cols = [
        c for c in (chromosome_col, position_col, value_col, end_col, sample_col, category_col) if c
    ]

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        select_columns=project_cols,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_coverage_track: loaded %d rows in %dms", df.height, load_ms)

    compute_started = time.monotonic()

    # Per-setting filtering happens after the global filter_metadata pass.
    if chromosomes_filter:
        df = df.filter(pl.col(chromosome_col).is_in(chromosomes_filter))
    if samples_filter and sample_col:
        df = df.filter(pl.col(sample_col).is_in(samples_filter))

    # Universe summaries are computed from the post-filter frame so the UI
    # MultiSelects reflect what's actually showing.
    chromosomes = sorted(df.get_column(chromosome_col).unique().to_list()) if df.height else []
    samples: list[str] = (
        sorted(df.get_column(sample_col).unique().to_list()) if sample_col and df.height else []
    )

    sort_keys = (
        [sample_col, chromosome_col, position_col] if sample_col else [chromosome_col, position_col]
    )
    df = df.sort(sort_keys)

    if smoothing_window > 1:
        group_keys = [chromosome_col, sample_col] if sample_col else [chromosome_col]
        df = df.with_columns(
            pl.col(value_col)
            .rolling_mean(window_size=smoothing_window, min_periods=1)
            .over(group_keys)
            .alias(value_col)
        )

    if df.height > max_rows:
        # Last-ditch decimation for runaway DCs — pick every Nth row inside
        # each (sample, chrom) group so each track stays continuous.
        keep_every = max(1, df.height // max_rows)
        df = df.with_row_index("__row").filter(pl.col("__row") % keep_every == 0).drop("__row")

    rows: dict[str, list] = {}
    for col in (chromosome_col, position_col, value_col, end_col, sample_col, category_col):
        if col and col not in rows:
            rows[col] = df.get_column(col).to_list()

    # Cast the value series to Float64 before reducing so Series.mean()/max()
    # always return float | None — keeps the JSON summary single-typed.
    if df.height:
        values_f64 = df.get_column(value_col).cast(pl.Float64)
        mean_value = values_f64.mean()
        max_value = values_f64.max()
    else:
        mean_value = None
        max_value = None
    summary = {
        "row_count": int(df.height),
        "chromosomes": chromosomes,
        "samples": samples,
        "n_samples": len(samples),
        "mean_value": mean_value,
        "max_value": max_value,
    }
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_coverage_track: %d rows / %d samples / %d chroms in %dms",
        df.height,
        len(samples),
        len(chromosomes),
        compute_ms,
    )

    return {
        "rows": rows,
        "columns": {
            "chromosome": chromosome_col,
            "position": position_col,
            "value": value_col,
            "end": end_col,
            "sample": sample_col,
            "category": category_col,
        },
        "summary": summary,
        "row_count": int(df.height),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_sankey",
    soft_time_limit=120,
    time_limit=240,
)
def compute_sankey(payload: dict) -> dict:
    """Aggregate flow across N ordered categorical levels into a Plotly Sankey.

    Input payload:
        {
          "wf_id": str, "dc_id": str,
          "step_cols": [str] (≥2),
          "value_col": str | null  (null → row count),
          "sort_mode": "alphabetical" | "total_flow" | "input",
          "min_link_value": float,
          "step_filters": {col: [value, ...]} | null,
          "filter_metadata": [...],
        }

    Returns a Plotly figure JSON ready for react-plotly.js plus node/link
    metadata so the renderer can recolour client-side without re-dispatching.
    """
    import polars as pl

    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    step_cols = list(payload.get("step_cols") or [])
    value_col = payload.get("value_col")
    sort_mode = str(payload.get("sort_mode") or "total_flow")
    min_link_value = max(0.0, float(payload.get("min_link_value") or 0.0))
    step_filters = payload.get("step_filters") or {}
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_sankey: wf_id and dc_id are required")
    if len(step_cols) < 2:
        raise ValueError("compute_sankey: step_cols must have ≥2 columns")
    if len(set(step_cols)) != len(step_cols):
        # Duplicate step columns would land in group_by(...).rename({col: ..., col: ...})
        # where the dict literal silently drops one key and polars then raises on
        # ambiguous output names. Reject up front with a clearer message.
        raise ValueError("compute_sankey: step_cols must not contain duplicates")

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_sankey: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    project_cols = [*step_cols, value_col] if value_col else list(step_cols)

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        select_columns=project_cols,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_sankey: loaded %d rows in %dms", df.height, load_ms)

    compute_started = time.monotonic()

    # Per-step filters applied AFTER global filter_metadata.
    for col, allowed in step_filters.items():
        if col in step_cols and allowed:
            df = df.filter(pl.col(col).cast(pl.Utf8).is_in(allowed))
    # Coerce NULL and empty-string categorical values to a literal "(missing)"
    # so they remain visible in the flow — Plotly Sankey can't render NaN node
    # labels. Pure polars expressions; no Python-row UDFs.
    df = df.with_columns(
        [
            pl.when(pl.col(c).cast(pl.Utf8).fill_null("") == "")
            .then(pl.lit("(missing)"))
            .otherwise(pl.col(c).cast(pl.Utf8))
            .alias(c)
            for c in step_cols
        ]
    )

    # Materialise the weight column up-front so polars can aggregate it
    # directly — `pl.lit(1.0).sum()` errors with "cannot aggregate a literal".
    # Drop rows with a null weight before summing so a single bad row can't
    # poison the aggregate into NaN (which would JSON-serialise as null and
    # break Plotly's Sankey value array).
    if value_col:
        df = df.with_columns(pl.col(value_col).cast(pl.Float64).alias("__sk_weight")).filter(
            pl.col("__sk_weight").is_not_null()
        )
    else:
        df = df.with_columns(pl.lit(1.0).alias("__sk_weight"))

    # Build per-adjacent-pair link aggregates: (src_col, src_value, tgt_value,
    # weight). Sankey doesn't care which step a node lives in, but Plotly
    # picks deterministic positions when nodes appear in a single ordered
    # list, so we keep that order below.
    link_frames: list[pl.DataFrame] = []
    for src_col, tgt_col in zip(step_cols[:-1], step_cols[1:]):
        link_frames.append(
            df.group_by([src_col, tgt_col])
            .agg(pl.col("__sk_weight").sum().alias("value"))
            .rename({src_col: "source_value", tgt_col: "target_value"})
            .with_columns(
                [pl.lit(src_col).alias("source_col"), pl.lit(tgt_col).alias("target_col")]
            )
        )

    if link_frames:
        links_df = pl.concat(link_frames, how="vertical_relaxed")
    else:
        links_df = pl.DataFrame(
            schema={
                "source_value": pl.Utf8,
                "target_value": pl.Utf8,
                "value": pl.Float64,
                "source_col": pl.Utf8,
                "target_col": pl.Utf8,
            }
        )

    if min_link_value > 0:
        links_df = links_df.filter(pl.col("value") >= min_link_value)

    # Node universe: one node per (step, value) pair, in step order. Sort
    # values within a step by chosen mode; total_flow falls back to
    # alphabetical when there are no links to rank from.
    def _step_values(step_col: str) -> list:
        if sort_mode == "input":
            return df.get_column(step_col).unique(maintain_order=True).to_list()
        if sort_mode == "total_flow" and links_df.height > 0:
            outgoing = (
                links_df.filter(pl.col("source_col") == step_col)
                .group_by("source_value")
                .agg(pl.col("value").sum().alias("total"))
                .rename({"source_value": "label"})
            )
            incoming = (
                links_df.filter(pl.col("target_col") == step_col)
                .group_by("target_value")
                .agg(pl.col("value").sum().alias("total"))
                .rename({"target_value": "label"})
            )
            totals = (
                pl.concat([outgoing, incoming], how="vertical_relaxed")
                .group_by("label")
                .agg(pl.col("total").sum())
                .sort("total", descending=True)
            )
            return totals.get_column("label").to_list()
        return sorted(df.get_column(step_col).unique().to_list())

    node_rows: list[dict] = []
    seen: dict[tuple[str, str], int] = {}
    for step_index, step_col in enumerate(step_cols):
        for v in _step_values(step_col):
            key = (step_col, str(v))
            if key in seen:
                continue
            seen[key] = len(node_rows)
            node_rows.append({"label": str(v), "step": step_col, "step_index": step_index})

    # Resolve link source/target to node indices.
    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_labels: list[str] = []
    for row in links_df.iter_rows(named=True):
        sk = (row["source_col"], str(row["source_value"]))
        tk = (row["target_col"], str(row["target_value"]))
        if sk not in seen or tk not in seen:
            continue
        sources.append(seen[sk])
        targets.append(seen[tk])
        values.append(float(row["value"]))
        link_labels.append(f"{row['source_value']} → {row['target_value']}")

    # Plotly figure — minimal layout, renderer adds template / dark mode.
    fig_dict = {
        "data": [
            {
                "type": "sankey",
                "arrangement": "snap",
                "node": {
                    "label": [n["label"] for n in node_rows],
                    "pad": 14,
                    "thickness": 18,
                },
                "link": {
                    "source": sources,
                    "target": targets,
                    "value": values,
                    "label": link_labels,
                },
            }
        ],
        "layout": {"font": {"size": 12}, "margin": {"l": 8, "r": 8, "t": 24, "b": 8}},
    }

    compute_ms = int((time.monotonic() - compute_started) * 1000)
    total_flow = float(sum(values)) if values else 0.0
    logger.info(
        "compute_sankey: %d nodes / %d links / total flow %.1f in %dms",
        len(node_rows),
        len(values),
        total_flow,
        compute_ms,
    )

    return {
        "figure": fig_dict,
        "nodes": node_rows,
        "step_cols": step_cols,
        "node_count": len(node_rows),
        "link_count": len(values),
        "total_flow": total_flow,
        "row_count": int(df.height),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


# A step in any of these statuses will never change again on its own, so the
# finalizer can close the run around it and a dependent DC can stop waiting on
# it: "skipped" joined "success"/"failed" once an optional pre-flight miss
# started seeding steps that way (see ``_dispatch_refresh_tasks``).
_TERMINAL_STEP_STATUSES = frozenset({"success", "failed", "skipped"})

# How long a dependent DC's task waits between checks on its dc_ref(s), and how
# many times before it gives up: 180 * 10s = 30 minutes, the same order of
# magnitude as this task's own ``soft_time_limit`` below.
_DEPENDENCY_WAIT_SECONDS = 10
_DEPENDENCY_MAX_WAITS = 180


def _unfinished_dependencies(steps: list[dict], depends_on: list[str]) -> list[str]:
    """The names in ``depends_on`` whose step hasn't reached a terminal status.

    A name in ``depends_on`` with no step in ``steps`` at all (pruned at
    resolution, or simply not part of this run) is not waited for: only a
    step actually seeded here can ever go terminal.
    """
    by_name = {s.get("name"): s.get("status") for s in steps}
    return [
        dep for dep in depends_on if dep in by_name and by_name[dep] not in _TERMINAL_STEP_STATUSES
    ]


def _finalize_manifest_refresh_run(run_id: str) -> None:
    """Close the run once every seeded step is terminal. Idempotent —
    concurrent finalizers both compute the same $set."""
    from depictio.api.v1.monitoring import store

    doc = store.get_ingestion_run(run_id)
    if not doc or doc.get("status") != "running":
        return
    steps = doc.get("steps") or []
    if not steps or any(s.get("status") not in _TERMINAL_STEP_STATUSES for s in steps):
        return
    failed = [s for s in steps if s.get("status") == "failed"]
    if not failed:
        status = "success"
    else:
        # A skipped step is a nominal absence, not a failure: it must never
        # make an otherwise-clean run read as "failed", so it drops out of
        # both sides of the "every step failed" comparison.
        non_skipped = [s for s in steps if s.get("status") != "skipped"]
        status = "failed" if non_skipped and len(failed) == len(non_skipped) else "partial"
    store.finish_ingestion_run(
        run_id,
        status=status,
        current_step=None,
        error=(failed[0].get("detail") if failed else None),
    )


@celery_app.task(
    bind=True,
    name="depictio.manifest.refresh_dc",
    soft_time_limit=1800,
    time_limit=2100,
    max_retries=_DEPENDENCY_MAX_WAITS,
)
def manifest_refresh_dc_task(self, payload: dict) -> dict:
    """Re-ingest one manifest-backed DC — the async unit of a manifest refresh.

    Input shape (built by ``_refresh_manifest_in_project`` / ``_dispatch_refresh_tasks``):
        {
          "run_id":     ingestion-run id (steps pre-seeded, one per DC tag),
          "project_id", "wf_index", "dc_id", "dc_tag",
          "sync_files": bool,
          "user": {"id", "email", "is_admin"},
          "depends_on": [dc_tag, ...] (optional; recipe DCs only, see
                         ``manifest_ingest._recipe_dependencies``),
        }

    The project document is re-read here (nothing rich crosses the broker) and
    is never written: refresh has no scan-config changes to persist or revert,
    which is what makes per-DC parallelism safe.

    ``depends_on`` is checked before the step is even marked "running", and
    outside the ``try/except`` below: ``self.retry()`` raises Celery's own
    ``Retry`` exception to unwind out of this call, and a blanket
    ``except Exception`` would catch that as if it were an ingestion failure.
    An unfinished dependency reschedules this same task after a short wait
    rather than occupying a worker slot for up to 30 minutes; giving up after
    ``_DEPENDENCY_MAX_WAITS`` retries fails the step by name instead of
    retrying forever against a dependency that will never finish.
    """
    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import _run_dc_ingest
    from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
        ProjectStorageUnusable,
        storage_options_for_project,
    )
    from depictio.api.v1.monitoring import store
    from depictio.models.models.users import UserBase

    run_id = payload["run_id"]
    tag = payload["dc_tag"]

    depends_on = payload.get("depends_on") or []
    if depends_on:
        doc = store.get_ingestion_run(run_id) or {}
        unfinished = _unfinished_dependencies(doc.get("steps") or [], depends_on)
        if unfinished:
            names = ", ".join(unfinished)
            if self.request.retries >= _DEPENDENCY_MAX_WAITS:
                message = f"Gave up waiting for {names} to finish."
                store.set_ingestion_step(
                    run_id,
                    step={"name": tag, "status": "failed", "detail": message},
                    current_step=None,
                )
                _finalize_manifest_refresh_run(run_id)
                return {"tag": tag, "ok": False, "message": message}
            if self.request.retries == 0:
                # Stays "pending": this DC hasn't started, it's queued behind
                # another one, but the detail tells a polling UI why.
                store.set_ingestion_step(
                    run_id,
                    step={"name": tag, "status": "pending", "detail": f"Waiting for {names}."},
                    current_step=None,
                )
            raise self.retry(countdown=_DEPENDENCY_WAIT_SECONDS)

    store.set_ingestion_step(run_id, step={"name": tag, "status": "running"}, current_step=tag)
    try:
        project = projects_collection.find_one({"_id": ObjectId(payload["project_id"])})
        if not project:
            raise ValueError("Project no longer exists.")
        workflow_dict = project["workflows"][payload["wf_index"]]
        user = UserBase(
            id=ObjectId(payload["user"]["id"]),
            email=payload["user"]["email"],
            is_admin=bool(payload["user"].get("is_admin", False)),
        )
        ok, message = _run_dc_ingest(
            workflow_dict,
            payload["dc_id"],
            user,
            sync_files=bool(payload.get("sync_files", True)),
            # Resolved worker-side so credentials never cross the broker.
            remote_storage_options=storage_options_for_project(payload["project_id"]),
        )
    except ProjectStorageUnusable as exc:
        # The project's stored storage config cannot be used from this worker
        # (secret encrypted with a key this worker does not have, or endpoint
        # no longer allowed). Reading with the instance credentials instead
        # would be silent misbehaviour, so the DC step fails with the reason;
        # the operator context (key path) goes to the worker log only.
        logger.error(f"Manifest refresh for DC '{tag}' cannot use project storage: {exc}")
        ok, message = False, exc.detail
    except Exception as exc:  # noqa: BLE001 — any crash is a per-DC failure
        logger.error(f"Manifest refresh task crashed for DC '{tag}': {exc}")
        ok, message = False, str(exc)

    store.set_ingestion_step(
        run_id,
        step={"name": tag, "status": "success" if ok else "failed", "detail": message},
        current_step=None,
    )
    _finalize_manifest_refresh_run(run_id)
    return {"tag": tag, "ok": ok, "message": message}


__all__: list[str] = [
    "build_figure_preview",
    "analyze_figure_code",
    "build_multiqc_preview",
    "preview_deltatable",
    "compute_embedding",
    "compute_complex_heatmap",
    "compute_upset",
    "compute_coverage_track",
    "compute_sankey",
    "manifest_refresh_dc_task",
]
