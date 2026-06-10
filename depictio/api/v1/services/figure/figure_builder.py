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

# Above this row count, per-marker scatter plots are downsampled before being
# handed to Plotly: a 1M-row scatter serialises to tens of MB of trace JSON that
# stalls the browser, and beyond ~50k markers the extra points are visually
# indistinguishable. Only applied to per-row marker plots (scatter family) —
# never to line/bar/box/histogram where every row matters or is aggregated.
FIGURE_MAX_POINTS = 50_000
_POINT_PLOT_TYPES = frozenset(
    {"scatter", "scatter_3d", "scatter_ternary", "scatter_polar", "strip"}
)

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


def process_code_mode_figure(
    code_content: str,
    df: Any,
    current_theme: str,
    task_id: str,
) -> tuple[bool, go.Figure | None, str | None]:
    """
    Process a figure in code mode by executing user-provided code.

    Args:
        code_content: User-provided Python code to execute
        df: DataFrame to pass to the code execution
        current_theme: Current theme name for styling
        task_id: Task ID for logging

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
    success, fig, message = executor.execute_code(code_content, df)

    if not success:
        logger.error(f"[{task_id}] Code execution failed: {message}")
        return False, create_error_figure(f"Code execution error: {message}", current_theme), None

    detected_visu_type = extract_visualization_type_from_code(code_content)

    if "template=" not in code_content:
        theme_template = f"mantine_{current_theme}"
        fig.update_layout(template=theme_template)

    fig.update_layout(uirevision="persistent")

    return True, fig, detected_visu_type


def create_figure_from_data(
    df: Any,
    visu_type: str,
    dict_kwargs: dict,
    theme: str = "light",
    selection_enabled: bool = False,
    selection_column: str | None = None,
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

    Returns:
        Plotly Figure object
    """
    import json

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

        keep_empty_string_params = {
            "parents",
            "names",
            "ids",
            "hover_name",
            "hover_data",
            "custom_data",
        }

        json_parseable_params = {
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

        cleaned_kwargs = {}
        for k, v in dict_kwargs.items():
            if v is None:
                continue

            if k in json_parseable_params and isinstance(v, str) and v.strip():
                try:
                    v = json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    logger.warning(f"Failed to parse {k} as JSON: {v}, skipping")
                    continue

            if isinstance(v, bool):
                cleaned_kwargs[k] = v
            elif v != "" and v != [] or (k in keep_empty_string_params and v == ""):
                cleaned_kwargs[k] = v

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

        # Downsample very large point-style scatters and prefer WebGL so the
        # serialised figure stays small and the browser stays responsive.
        if visu_type in _POINT_PLOT_TYPES and plot_df.height > FIGURE_MAX_POINTS:
            original_height = plot_df.height
            plot_df = plot_df.sample(n=FIGURE_MAX_POINTS, seed=0)
            logger.info(
                f"create_figure_from_data: downsampled {visu_type} from "
                f"{original_height} to {FIGURE_MAX_POINTS} points to cap payload size"
            )
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

        return fig

    except Exception as e:
        logger.error(f"Figure creation failed: {e}", exc_info=True)
        return create_error_figure(f"Error: {str(e)}", theme)
