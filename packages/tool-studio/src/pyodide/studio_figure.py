"""Tool Studio's exact figure preview inside Pyodide (src/pyodide/engine.ts).

Builds a UI-mode figure with the server's own code, shipped by
src/pyodide/figureModules.ts: the UI-mode body of ``build_figure_preview``
(api/v1/celery_tasks.py), with its Delta load replaced by the fixture:

1. the fixture read as ``catalog validate`` reads it (``read_fixture_schema``:
   ``pl.read_csv``, separator by suffix, ``infer_schema_length=10_000``), then
   only the rows the preview filters keep (the mask Tool Studio computed);
2. the scan-level aggregation fast path (``plan_aggregation`` +
   ``build_aggregated_figure`` over the frame as a LazyFrame) for box /
   histogram / bar / density, else the column projection of
   ``referenced_columns`` and ``create_figure_from_data`` with the
   ``figure_max_points`` default;
3. ``tidy_facet_layout`` (extracted from groups.py by the serverless bundler's
   ``extract``), ``fig.to_json()``, ``apply_figure_style`` with the style block
   ``figure_style_payload`` builds for the component, and ``uirevision``.

Not reproduced: the Delta row ceiling (``limit_rows``; a fixture is far below
it), a dashboard's brand theme and category colours (a catalog render has no
dashboard) and selection groups. Takes and returns JSON strings.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import types
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl

ROOT = Path(__file__).parent
SOURCE_DIR = ROOT / "depictio_studio_src"

# What figureModules.ts ships under SOURCE_DIR, and the functions cut out of it.
_EXTRACT = {
    "depictio/api/v1/services/figure/groups.py": (
        "depictio.api.v1.services.figure.groups",
        ("tidy_facet_layout",),
    ),
}

_ext: dict[str, types.ModuleType] = {}


def _extracted(rel: str) -> types.ModuleType:
    """``modules.extract`` (the serverless bundler) on a shipped server source."""
    if rel in _ext:
        return _ext[rel]
    from depictio.serverless.pyodide import modules

    name, roots = _EXTRACT[rel]
    source_mod = types.ModuleType(name)
    source_mod.__file__ = str(SOURCE_DIR / rel)
    code = modules.extract(source_mod, roots)
    short = name.rsplit(".", 1)[-1]
    mod = types.ModuleType(f"depictio_studio_ext.{short}")
    mod.__file__ = f"<extracted {name}>"
    exec(compile(code, mod.__file__, "exec"), mod.__dict__)  # noqa: S102 - server source
    sys.modules[mod.__name__] = mod
    _ext[rel] = mod
    return mod


class _Errors(logging.Handler):
    """``create_figure_from_data`` logs and returns an error figure instead of
    raising; keep the message so the caller can tell an environment gap (a
    module Pyodide lacks) from what depictio itself would show."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def read_fixture(file_name: str, text: str) -> pl.DataFrame:
    sep = "\t" if PurePosixPath(file_name).suffix == ".tsv" else ","
    return pl.read_csv(io.BytesIO(text.encode("utf-8")), separator=sep, infer_schema_length=10_000)


def _build(df: pl.DataFrame, metadata: dict[str, Any], theme: str, style_override: Any) -> dict:
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.services.figure.aggregate import (
        build_aggregated_figure,
        plan_aggregation,
    )
    from depictio.api.v1.services.figure.figure_builder import (
        create_figure_from_data,
        referenced_columns,
        resolve_template_override,
    )
    from depictio.api.v1.services.figure.style_presets import (
        apply_figure_style,
        figure_style_payload,
    )

    visu_type = metadata.get("visu_type") or "scatter"
    dict_kwargs = metadata.get("dict_kwargs") or {}
    render_stats: dict[str, Any] = {}

    fig = None
    plan = plan_aggregation(visu_type, dict_kwargs)
    if plan is not None:
        fig = build_aggregated_figure(
            df.lazy(),
            plan,
            theme,
            render_stats,
            template_override=resolve_template_override(dict_kwargs.get("template")),
        )
    if fig is None:
        cols = referenced_columns(visu_type, dict_kwargs)
        if cols is not None:
            df = df.select([c for c in df.columns if c in cols])
        fig = create_figure_from_data(
            df=df,
            visu_type=visu_type,
            dict_kwargs=dict_kwargs,
            theme=theme,
            max_points=metadata.get("max_points") or settings.performance.figure_max_points,
            render_stats=render_stats,
        )
    try:
        _extracted("depictio/api/v1/services/figure/groups.py").tidy_facet_layout(fig)
    except Exception as exc:  # the server never loses a figure to its tidying
        logging.getLogger("depictio.studio").warning(f"facet tidy skipped: {exc}")

    fig_dict = json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    style = figure_style_payload(metadata, None, style_override)
    fig_dict = apply_figure_style(
        fig_dict,
        style.get("figure_style"),
        theme=theme,
        header_title=bool(style.get("header_title")),
        hide_legend=bool(style.get("hide_legend")),
        category_colors=None,
    )
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")
    return {"figure": fig_dict, "stats": render_stats}


def render_figure(request_json: str, file_name: str, text: str) -> str:
    """``request``: ``{metadata, theme, style?, keep?: [row index] | null,
    rows?: int}``. ``rows`` is the row count the caller's mask was computed
    over; a fixture polars reads to a different height cannot take that mask."""
    request = json.loads(request_json)
    metadata = request.get("metadata") or {}
    theme = "dark" if request.get("theme") == "dark" else "light"
    df = read_fixture(file_name, text)
    keep = request.get("keep")
    if keep is not None:
        rows = request.get("rows")
        if rows is not None and rows != df.height:
            raise ValueError(
                f"the preview filters were computed over {rows} rows, polars reads {df.height}"
            )
        df = df[keep] if keep else df.clear()
    total = df.height

    errors = _Errors()
    logging.getLogger("depictio.studio").addHandler(errors)
    try:
        built = _build(df, metadata, theme, request.get("style"))
    finally:
        logging.getLogger("depictio.studio").removeHandler(errors)
    stats = built["stats"]
    displayed = int(stats.get("displayed", stats.get("rows_displayed", total)))
    return json.dumps(
        {
            "figure": built["figure"],
            "metadata": {
                "visu_type": metadata.get("visu_type") or "scatter",
                "was_sampled": bool(stats.get("sampled", False)),
                "displayed_data_count": displayed,
                "total_data_count": max(int(stats.get("total_rows") or total), displayed),
                "aggregated": bool(stats.get("aggregated")),
            },
            "errors": [m for m in errors.messages if "Figure creation failed" in m],
        }
    )


def packages_needed(metadata_json: str) -> str:
    """Pyodide packages a figure needs beyond polars + plotly: px imports
    statsmodels for an OLS / LOWESS trendline (and its fit needs pandas)."""
    metadata = json.loads(metadata_json)
    kwargs = metadata.get("dict_kwargs") or {}
    trendline = kwargs.get("trendline")
    needed: list[str] = []
    if trendline in ("ols", "lowess"):
        needed.append("statsmodels")
    if trendline in ("rolling", "ewm", "expanding", "ols", "lowess"):
        needed.append("pandas")
    return json.dumps(needed)
