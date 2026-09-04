"""Figure construction helpers extracted from
depictio.dash.modules.figure_component.callbacks.core.

These functions build Plotly figures from a DataFrame plus user-provided
parameters (either UI dict_kwargs or executed user code). They are Dash-free so
the API/Celery preview path can use them without importing the Dash app.
"""

from typing import Any

import plotly.express as px
import plotly.graph_objects as go

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.figure.error_figure import create_error_figure
from depictio.api.v1.services.figure.heatmap import collect_heatmap_kwargs
from depictio.api.v1.services.multiqc.themes import get_theme_template
from depictio.models.models.branding import BrandTheme, resolve_brand_theme

# Above this row count, per-marker plots are downsampled before being handed to
# Plotly: a 1M-row scatter serialises to tens of MB of trace JSON that stalls the
# browser, and beyond ~50k markers the extra points are visually indistinguishable.
FIGURE_MAX_POINTS = 50_000

# Template names that mean "follow the UI theme" rather than an explicit style
# choice. Legacy components carry `template: "mantine_light"` as a stamped
# default, so honoring it literally would lock them to light mode.
_THEME_FOLLOW_TEMPLATES = frozenset({"mantine_light", "mantine_dark"})


def resolve_template_override(requested: str | None) -> str | None:
    """The explicit Plotly template a component/dashboard picked, if any.

    Returns ``None`` for unset values and for the mantine sentinels — both mean
    "use the theme-matched mantine template".
    """
    if requested and requested not in _THEME_FOLLOW_TEMPLATES:
        return requested
    return None


def merge_dashboard_brand_theme(brand_theme: Any, dict_kwargs: dict) -> dict:
    """Apply a dashboard's brand theme figure defaults to a figure's kwargs (#397).

    ``brand_theme`` is a ``BrandTheme`` or its dict form (what Mongo stores).
    It is resolved first, so a dashboard that only sets ``primary`` still hands
    the figure a derived colorway — the same one the SPA received.

    Component-explicit choices always win:
    - ``colorway`` fills ``color_discrete_sequence`` only when the component
      sets neither a sequence nor a ``color_discrete_map``.
    - ``template`` applies only when the component's own template is unset or a
      mantine sentinel (i.e. "follow the UI theme" — see
      ``resolve_template_override``).
    """
    if not brand_theme:
        return dict_kwargs

    theme = brand_theme if isinstance(brand_theme, BrandTheme) else BrandTheme(**brand_theme)
    plots = resolve_brand_theme(theme).plots
    if not plots:
        return dict_kwargs

    merged = dict(dict_kwargs)
    if (
        plots.colorway
        and not merged.get("color_discrete_sequence")
        and not merged.get("color_discrete_map")
    ):
        merged["color_discrete_sequence"] = plots.colorway
    if plots.template and resolve_template_override(merged.get("template")) is None:
        merged["template"] = plots.template
    return merged


# Scatter-family plots — one marker per row, and the only types we force to WebGL.
_POINT_PLOT_TYPES = frozenset(
    {"scatter", "scatter_3d", "scatter_ternary", "scatter_polar", "strip"}
)

# Plot types that materialise one mark/vertex per row, so downsampling both cuts
# the serialised payload and stays visually faithful: the scatter family plus
# line/area (one vertex per row) and ecdf (one step per row).
#
# Deliberately NOT sampled — these aggregate or bin, so every row shapes the
# result: box, violin, histogram, density_heatmap, density_contour, funnel.
# They are instead computed as a Polars aggregation over the lazy scan (see
# ``services/figure/aggregate.py``), which is both exact and far cheaper.
#
# ``bar`` was in this set and had to come out: px.bar does NOT aggregate, it
# emits one stacked segment per row, so a random sample scales every bar's
# height by the sample ratio — silently wrong output, not an approximation.
# Bars now go through the same group-by aggregation as the other reducing types.
#
# Kept in sync with ``isPointPlot`` in viewer/src/builder/figure/FigureUIMode.tsx.
_SAMPLABLE_PLOT_TYPES = _POINT_PLOT_TYPES | frozenset({"line", "area", "ecdf"})

# Ordered (non-random) decimation applies to these: a series is defined by the
# order of its vertices, so a random sample thins it unevenly and visibly
# deforms the line. See ``_decimate_ordered``.
_ORDERED_PLOT_TYPES = frozenset({"line", "area"})

# Plotly Express keyword args whose value is a single DataFrame column name.
_PX_COLUMN_PARAMS: frozenset[str] = frozenset(
    {
        "x", "y", "z", "color", "size", "symbol", "line_dash", "line_group",
        "pattern_shape", "hover_name", "names", "values", "facet_col", "facet_row",
        "animation_frame", "animation_group", "base", "r", "theta", "a", "b", "c",
        "error_x", "error_y", "error_z",
    }
)  # fmt: skip

# Plotly Express keyword args whose value is a list (or ``{col: bool}`` dict) of
# column names.
_PX_COLUMN_LIST_PARAMS: frozenset[str] = frozenset({"hover_data", "custom_data", "dimensions"})

# Visualisations that read the whole frame (or a column set we can't reliably
# enumerate from dict_kwargs): projecting them risks dropping needed columns, so
# signal a full load instead.
_WHOLE_FRAME_VISU: frozenset[str] = frozenset(
    {
        "heatmap", "scatter_matrix", "parallel_coordinates",
        "parallel_categories", "imshow", "scatter_geo", "choropleth",
    }
)  # fmt: skip


def referenced_columns(visu_type: str, dict_kwargs: dict) -> set[str] | None:
    """Columns a UI-mode figure references, for scan-level column projection (#7).

    Returns the set of column names the Plotly Express call will read from the
    DataFrame, so the loader can project the Delta scan to just those columns
    (it folds in any filter columns and schema-guards the result). Returns
    ``None`` whenever projection is unsafe — a whole-frame visualisation
    (heatmap, scatter_matrix, …), a column list we can't parse, or a non-dict
    spec — so the caller falls back to a full load. Missing a referenced column
    would silently break the figure, so this errs toward ``None`` on any
    uncertainty.

    Code-mode figures must never be projected via this helper — arbitrary user
    code can reference any column — so callers gate on ``mode != "code"``.
    """
    import json

    if not isinstance(dict_kwargs, dict):
        return None
    if (visu_type or "").lower() in _WHOLE_FRAME_VISU:
        return None

    cols: set[str] = set()
    for key, value in dict_kwargs.items():
        if value is None or value == "" or value == []:
            continue
        if key in _PX_COLUMN_PARAMS:
            # error_x/y/z may be a dict config carrying no column — only a bare
            # string names a column.
            if isinstance(value, str):
                cols.add(value)
        elif key in _PX_COLUMN_LIST_PARAMS:
            parsed = value
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except (json.JSONDecodeError, ValueError):
                    # Opaque string we can't decompose into column names — don't
                    # risk projecting away a column it might reference.
                    return None
            if isinstance(parsed, dict):
                cols.update(k for k in parsed if isinstance(k, str))
            elif isinstance(parsed, (list, tuple)):
                cols.update(v for v in parsed if isinstance(v, str))
            else:
                return None
        # Unknown keys are Plotly styling params (templates, colour maps, …)
        # that take literal values, not column names — safe to ignore.
    return cols or None


def _decimate_ordered(plot_df, x_col: str | None, cap: int):
    """Thin a series to ~``cap`` rows while preserving its visual shape.

    Random sampling is wrong for line/area: the mark is defined by the *order*
    of its vertices, so dropping rows uniformly at random thins dense and sparse
    stretches alike and turns a smooth series into a jagged one — and it can drop
    the spikes, which are usually the whole point of looking at the series.

    This is the M4 idea: sort by x, cut into ``cap // 4`` equal-width buckets and
    keep each bucket's first / last / min / max row. At the pixel resolution a
    plot actually has, that is visually indistinguishable from the full series
    (every vertical extent is preserved) at a fraction of the vertices.

    Falls back to an ordered stride when there's no usable x column to sort on.
    """
    import polars as pl

    if plot_df.height <= cap:
        return plot_df

    if not x_col or x_col not in plot_df.columns:
        # No x to order by — take every k-th row. Still better than random:
        # spacing stays uniform, so the series keeps its shape.
        stride = max(1, plot_df.height // cap)
        return plot_df.gather_every(stride)

    n_buckets = max(1, cap // 4)
    ordered = plot_df.sort(x_col, nulls_last=True).with_row_index("_row_idx")
    # Bucket by position rather than by x value so irregularly-spaced series
    # (gaps, bursts) still get an even vertex budget across their length.
    bucket = (pl.col("_row_idx") * n_buckets // ordered.height).alias("_bucket")

    y_candidates = [
        c
        for c, dt in zip(ordered.columns, ordered.dtypes)
        if c not in (x_col, "_row_idx") and dt.is_numeric()
    ]
    keep = [
        pl.col("_row_idx").first().alias("_k_first"),
        pl.col("_row_idx").last().alias("_k_last"),
    ]
    if y_candidates:
        # Preserve vertical extent on the first numeric column — that's the one
        # carrying the spikes we must not lose.
        y = y_candidates[0]
        keep += [
            pl.col("_row_idx").sort_by(pl.col(y)).first().alias("_k_min"),
            pl.col("_row_idx").sort_by(pl.col(y)).last().alias("_k_max"),
        ]

    idx = (
        ordered.with_columns(bucket)
        .group_by("_bucket")
        .agg(keep)
        .select(pl.concat_list(pl.exclude("_bucket")).alias("_idx"))
        .explode("_idx")
        .unique()
        .drop_nulls()
    )
    return (
        ordered.join(idx, left_on="_row_idx", right_on="_idx", how="semi")
        .sort("_row_idx")
        .drop("_row_idx")
    )


def process_code_mode_figure(
    code_content: str,
    df: Any,
    current_theme: str,
    task_id: str,
    extra_globals: dict[str, Any] | None = None,
) -> tuple[bool, go.Figure | None, str | None]:
    """
    Process a figure in code mode by executing user-provided code.

    Args:
        code_content: User-provided Python code to execute
        df: DataFrame to pass to the code execution
        current_theme: Current theme name for styling
        task_id: Task ID for logging
        extra_globals: Extra names to bind in the sandbox, e.g. the grouping
            kwargs a code figure spreads to honour the Colour/Split toggle

    Returns:
        Tuple of (success, figure, visu_type):
        - success: Whether code execution succeeded
        - figure: The generated figure (or None on failure)
        - visu_type: Detected visualization type (or None on failure)
    """
    if not code_content:
        logger.error(f"[{task_id}] Code mode but no code_content")
        return False, None, None

    from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor
    from depictio.api.v1.services.figure.code_mode import (
        extract_visualization_type_from_code,
    )

    executor = SimpleCodeExecutor()
    success, fig, message = executor.execute_code(code_content, df, extra_globals)

    if not success:
        logger.error(f"[{task_id}] Code execution failed: {message}")
        return False, create_error_figure(f"Code execution error: {message}", current_theme), None

    detected_visu_type = extract_visualization_type_from_code(code_content)

    if "template=" not in code_content:
        theme_template = f"mantine_{current_theme}"
        fig.update_layout(template=theme_template)

    fig.update_layout(uirevision="persistent")

    return True, fig, detected_visu_type


# px parameters whose stored value is a JSON string (the builder serialises
# maps and lists into text fields) and must be parsed before reaching px.
JSON_PARSEABLE_PX_PARAMS: frozenset[str] = frozenset(
    {
        "color_discrete_map",
        "color_continuous_scale",
        "category_orders",
        "labels",
        "hover_data",
        "custom_data",
        "line_dash_map",
        "symbol_map",
        "pattern_shape_map",
        "size_map",
    }
)

# px parameters for which an empty string is a meaningful value.
KEEP_EMPTY_STRING_PX_PARAMS: frozenset[str] = frozenset(
    {"parents", "names", "ids", "hover_name", "hover_data", "custom_data"}
)


def clean_px_kwargs(dict_kwargs: dict) -> dict:
    """The builder's ``dict_kwargs`` as the keyword arguments px receives.

    Drops ``None``/empty values, parses the JSON-string parameters, keeps
    booleans as they are. Shared by :func:`create_figure_from_data` and the
    notebook export, so a generated ``px.<visu_type>(...)`` call carries
    exactly what the server passed.
    """
    import json

    cleaned: dict = {}
    for k, v in dict_kwargs.items():
        if v is None:
            continue
        if k in JSON_PARSEABLE_PX_PARAMS and isinstance(v, str) and v.strip():
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"Failed to parse {k} as JSON: {v}, skipping")
                continue
        if isinstance(v, bool):
            cleaned[k] = v
        elif v != "" and v != [] or (k in KEEP_EMPTY_STRING_PX_PARAMS and v == ""):
            cleaned[k] = v
    return cleaned


def create_figure_from_data(
    df: Any,
    visu_type: str,
    dict_kwargs: dict,
    theme: str = "light",
    selection_enabled: bool = False,
    selection_column: str | None = None,
    max_points: int | None = None,
    render_stats: dict[str, Any] | None = None,
) -> go.Figure:
    """
    Create Plotly figure from DataFrame and parameters.

    Args:
        df: Polars DataFrame with data
        visu_type: Visualization type (scatter, line, bar, box)
        dict_kwargs: Figure parameters
        theme: Theme name (light or dark)
        selection_enabled: Whether to enable scatter selection filtering
        selection_column: Column to include in customdata for selection extraction
        max_points: Point-plot downsampling target (falls back to
            ``FIGURE_MAX_POINTS``). Only applies to the scatter family.
        render_stats: Optional out-dict. When provided, it is populated with
            ``{"displayed": int, "sampled": bool}`` reflecting the plotted marker
            count so the caller can surface a "sampled" indicator to the client.

    Returns:
        Plotly Figure object
    """

    import polars as pl

    try:
        # Modern plotly.express consumes Polars natively (via narwhals), so we
        # keep the frame in Polars and skip the full pandas copy that used to
        # happen on every figure. plotly-complexheatmap (the heatmap branch
        # below) also accepts Polars now, so no conversion is needed there either.
        if isinstance(df, pl.DataFrame):
            plot_df = df
        elif hasattr(df, "to_pandas"):
            # e.g. a pyarrow Table — normalise to Polars once.
            plot_df = pl.from_pandas(df.to_pandas())
        else:
            # Legacy pandas input.
            plot_df = pl.from_pandas(df)

        # `mantine_light`/`mantine_dark` Plotly templates are registered
        # natively now that Dash/dmc is gone. Ensure they exist before px
        # consumes the template name — covers every caller (API inline, Celery
        # task, worker prerender), not just the endpoint-level guards.
        from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates

        ensure_mantine_templates()

        template = get_theme_template(theme)

        cleaned_kwargs = clean_px_kwargs(dict_kwargs)

        # An explicit template choice (component picker or dashboard brand theme)
        # wins; otherwise follow the UI theme (see resolve_template_override).
        if resolve_template_override(cleaned_kwargs.get("template")) is None:
            cleaned_kwargs["template"] = template

        if selection_enabled and selection_column and selection_column in plot_df.columns:
            existing_custom_data = cleaned_kwargs.get("custom_data", [])
            if isinstance(existing_custom_data, str):
                # If it's a single column name, convert to list
                existing_custom_data = [existing_custom_data]
            elif not isinstance(existing_custom_data, list):
                existing_custom_data = []

            if selection_column not in existing_custom_data:
                cleaned_kwargs["custom_data"] = [selection_column] + list(existing_custom_data)

        # Heatmap uses plotly-complexheatmap instead of px
        if visu_type.lower() == "heatmap":
            from plotly_complexheatmap import ComplexHeatmap

            # Extract dynamic column annotations from recipe-generated column
            if "_col_annotations_json" in plot_df.columns:
                if "col_annotations" not in cleaned_kwargs or not cleaned_kwargs.get(
                    "col_annotations"
                ):
                    try:
                        raw_val = plot_df["_col_annotations_json"][0]
                        if isinstance(raw_val, str):
                            cleaned_kwargs["col_annotations"] = raw_val
                        elif isinstance(raw_val, dict):
                            cleaned_kwargs["col_annotations"] = raw_val
                    except Exception as e:
                        logger.error(f"Failed to extract _col_annotations_json: {e}")
                plot_df = plot_df.drop("_col_annotations_json")

            heatmap_kwargs = collect_heatmap_kwargs(cleaned_kwargs)

            # Sanitize col_annotations: remove annotations with None/empty values
            # (ComplexHeatmap crashes on None in categorical color mapping)
            if "col_annotations" in heatmap_kwargs and isinstance(
                heatmap_kwargs["col_annotations"], dict
            ):
                heatmap_kwargs["col_annotations"] = {
                    k: v
                    for k, v in heatmap_kwargs["col_annotations"].items()
                    if not any(val is None or val == "" for val in v.get("values", []))
                }

            hm = ComplexHeatmap.from_dataframe(plot_df, **heatmap_kwargs)
            fig = hm.to_plotly()
            fig.update_layout(
                autosize=True,
                width=None,
                height=None,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            return fig

        # Gate on the curated registry, not a stale hand-maintained subset.
        # The previous hardcoded list (scatter/line/bar/box/histogram) silently
        # downgraded every advanced Plotly Express type — density_heatmap,
        # density_contour, area, funnel, strip, violin, ecdf, scatter_matrix —
        # to scatter, even though they're all in ALLOWED_VISUALIZATIONS and
        # picked up by parameter discovery in the builder. Use the same
        # registry the builder uses so add-a-viz only touches one place.
        from depictio.api.v1.services.figure.definitions import (
            ALLOWED_VISUALIZATIONS,
        )

        if visu_type not in ALLOWED_VISUALIZATIONS:
            logger.warning(
                f"Unsupported visualization type: {visu_type!r} "
                f"(not in ALLOWED_VISUALIZATIONS), defaulting to scatter"
            )
            visu_type = "scatter"

        # Plotly rejects NaN in the marker `size` property with a hard
        # ValueError. When the user picks a column that has missing values for
        # some rows (common in viralrecon summary metrics where unassigned
        # samples have null variant counts), drop those rows so the rest of
        # the dataset still renders.
        size_col = cleaned_kwargs.get("size")
        if isinstance(size_col, str) and size_col in plot_df.columns:
            # Drop both null and (for float columns) NaN — Plotly rejects either
            # in marker.size. ``is_not_nan`` is only valid on float dtypes.
            keep = pl.col(size_col).is_not_null()
            if plot_df[size_col].dtype in (pl.Float32, pl.Float64):
                keep = keep & pl.col(size_col).is_not_nan()
            before = plot_df.height
            plot_df = plot_df.filter(keep)
            dropped = before - plot_df.height
            if dropped:
                logger.info(
                    f"create_figure_from_data: dropped {dropped} row(s) with "
                    f"NaN in size column '{size_col}'"
                )

        # Downsample very large mark-per-row plots and prefer WebGL so the
        # serialised figure stays small and the browser stays responsive.
        # ``max_points``: None → module default; <= 0 → sampling disabled (the
        # caller asked for a full, uncapped render); > 0 → explicit cap.
        if max_points is None:
            point_cap: int | None = FIGURE_MAX_POINTS
        elif max_points <= 0:
            point_cap = None
        else:
            point_cap = max_points
        if (
            point_cap is not None
            and visu_type in _SAMPLABLE_PLOT_TYPES
            and plot_df.height > point_cap
        ):
            original_height = plot_df.height
            if visu_type in _ORDERED_PLOT_TYPES:
                # Series: thin by ordered decimation, never at random.
                plot_df = _decimate_ordered(plot_df, cleaned_kwargs.get("x"), point_cap)
                how = "decimated"
            else:
                plot_df = plot_df.sample(n=point_cap, seed=0)
                how = "downsampled"
            if render_stats is not None:
                render_stats["sampled"] = True
            logger.info(
                f"create_figure_from_data: {how} {visu_type} from "
                f"{original_height} to {plot_df.height} points to cap payload size"
            )
        if render_stats is not None:
            render_stats.setdefault("sampled", False)
            render_stats["displayed"] = plot_df.height
        if visu_type == "scatter":
            # px.scatter renders SVG by default for small N; force WebGL so even
            # the capped point count draws on the GPU instead of as DOM/SVG nodes.
            # (Unsupported kwargs are dropped by the signature filter below.)
            cleaned_kwargs.setdefault("render_mode", "webgl")

        plot_func = getattr(px, visu_type)

        # Drop kwargs the target px function doesn't accept. The builder's
        # dict_kwargs can carry leftovers from a previous visu type (e.g.,
        # `markers=True` chosen while in line/scatter still in dict_kwargs
        # after the user switches to strip / funnel which don't take that
        # kwarg). Without this filter px raises a hard TypeError and the
        # whole render fails. The signature inspection is cheap (cached per
        # function by inspect) and forwarding-friendly via **kwargs.
        import inspect

        try:
            sig = inspect.signature(plot_func)
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not accepts_var_kw:
                allowed_names = set(sig.parameters.keys())
                dropped = {k: cleaned_kwargs[k] for k in cleaned_kwargs if k not in allowed_names}
                if dropped:
                    logger.info(
                        f"create_figure_from_data: dropping {len(dropped)} kwarg(s) "
                        f"not accepted by px.{visu_type}: {sorted(dropped.keys())}"
                    )
                    cleaned_kwargs = {k: v for k, v in cleaned_kwargs.items() if k in allowed_names}
        except (ValueError, TypeError) as sig_err:
            # signature() can fail on C-extension callables; fall through and
            # let plotly handle (or fail loudly on) whatever we pass.
            logger.debug(
                f"create_figure_from_data: signature inspection failed for "
                f"px.{visu_type}: {sig_err}"
            )

        fig = plot_func(plot_df, **cleaned_kwargs)

        layout_updates: dict[str, Any] = {
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "uirevision": "persistent",
        }

        if selection_enabled:
            layout_updates["clickmode"] = "event+select"
            layout_updates["dragmode"] = "lasso"

        fig.update_layout(**layout_updates)
        # A floor, not a ceiling — see the same pair in `aggregate.py`. Without
        # this a fixed 40px bottom margin clips rotated category labels
        # mid-glyph and lets the axis title overwrite them.
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)

        return fig

    except Exception as e:
        logger.error(f"Figure creation failed: {e}", exc_info=True)
        return create_error_figure(f"Error: {str(e)}", theme)
