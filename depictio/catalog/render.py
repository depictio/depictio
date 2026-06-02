"""Render a catalog output's ``renders_as`` targets on its bundled fixture.

This is the shared, **Dash-free** render core behind ``depictio catalog preview``
(offline HTML for contributors) and, later, the demo-gated docs embed endpoint.
Given a :class:`CatalogOutput`, it loads the output's ``fixture`` — the canonical,
already-reshaped sample of the output's bindable shape, i.e. the same data
``depictio catalog validate`` grounds roles against — into a polars DataFrame and
builds each declared render:

  - figure (UI)   → plotly-express ``px.<visu_type>(df, **dict_kwargs)``
  - figure (code) → a RestrictedPython executor mirroring the dashboard's figure
                    code-mode (``SimpleCodeExecutor``), kept dependency-light (no
                    Dash import) so it runs in the CLI / CI.
  - card          → a polars aggregation (same semantics as the card component's
                    ``compute_value``).
  - table         → the column schema + a ``head()`` sample.

``advanced_viz`` / ``multiqc`` renders are recognised but not rendered here yet
(Phase 2 — they need the Celery compute helpers / a MultiQC report). They surface
as a clear "not supported yet" placeholder rather than an error.

The single ``render_output`` entry point returns a list of
:class:`RenderedComponent`; ``render_output_to_html`` wraps them into one
self-contained, interactive HTML page (plotly.js for figures, ag-grid-community
for tables — the very libraries the depictio frontend uses).
"""

from __future__ import annotations

import html as _html
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from depictio.models.components.advanced_viz.catalog import PROJECTS_DIR

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from depictio.models.components.advanced_viz.catalog import CatalogOutput, Render

# Frontend libraries (pinned to match ``viewer/package.json``) loaded from a CDN
# so the static preview behaves like the real depictio app. Plotly itself is
# injected by ``fig.to_html(include_plotlyjs="cdn")``.
_AGGRID_JS = "https://cdn.jsdelivr.net/npm/ag-grid-community@32.3.0/dist/ag-grid-community.min.js"
_AGGRID_CSS = "https://cdn.jsdelivr.net/npm/ag-grid-community@32.3.0/styles/ag-grid.css"
_AGGRID_THEME_CSS = (
    "https://cdn.jsdelivr.net/npm/ag-grid-community@32.3.0/styles/ag-theme-alpine.css"
)

# Rows shown in a table preview (a fixture is a small canonical sample anyway).
_TABLE_PREVIEW_ROWS = 100


class CatalogRenderError(Exception):
    """Raised when a catalog output cannot be rendered (no fixture, bad spec…)."""


@dataclass
class RenderedComponent:
    """One rendered ``renders_as`` target, ready for HTML or a JSON payload."""

    component: str
    label: str
    kind: str | None = None
    ok: bool = True
    error: str | None = None
    # Exactly one of the following is set when ``ok`` is True.
    figure: Any = None  # plotly.graph_objects.Figure
    card: dict[str, Any] | None = None  # {column, aggregation, value}
    table: dict[str, Any] | None = None  # {columns, rows, total_rows}


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def _load_fixture_df(output: CatalogOutput):  # -> pl.DataFrame
    """Load the output's bundled fixture (path under ``depictio/projects/``)."""
    import polars as pl

    if not output.fixture:
        raise CatalogRenderError(
            f"output {output.id!r} has no 'fixture' to preview — add a bundled "
            f"sample under projects/ (see catalog TODO 'add a fixture to every output')"
        )
    path = PROJECTS_DIR / output.fixture
    if not path.exists():
        raise CatalogRenderError(f"fixture not found: {path}")
    separator = "\t" if path.suffix == ".tsv" else ","
    return pl.read_csv(path, separator=separator)


# ---------------------------------------------------------------------------
# Per-component renderers
# ---------------------------------------------------------------------------


def _render_figure_ui(df, render: Render) -> go.Figure:
    """UI-mode figure: ``px.<visu_type>(df, **dict_kwargs)`` (plotly-express)."""
    import plotly.express as px

    fn = getattr(px, render.visu_type or "", None)
    if fn is None or not callable(fn):
        raise CatalogRenderError(f"unknown plotly-express visu_type {render.visu_type!r}")
    return fn(df.to_pandas(), **render.dict_kwargs)


def _figure_code_globals() -> dict[str, Any]:
    """Safe globals mirroring ``SimpleCodeExecutor`` (figure code-mode), Dash-free.

    Same surface the dashboard's code mode exposes (px/go/pl/pd/np + a small set
    of safe builtins and dataframe guards) so a snippet that previews here renders
    identically in a real dashboard.
    """
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    import polars as pl
    from RestrictedPython.Guards import safe_builtins, safe_globals

    def _getitem(obj, key):
        return obj[key]

    def _getattr(obj, name, default=None, getattr=getattr):
        return getattr(obj, name, default)

    def _write(obj, key, value):
        obj[key] = value
        return obj

    def _setattr(obj, name, value, setattr=setattr):
        setattr(obj, name, value)
        return value

    return {
        **safe_globals,
        "px": px,
        "go": go,
        "pl": pl,
        "pd": pd,
        "np": np,
        "__builtins__": safe_builtins,
        "_getitem_": _getitem,
        "_getattr_": _getattr,
        "_write_": _write,
        "_setattr_": _setattr,
        "_iter_unpack_sequence_": lambda seq, *a: iter(seq),
        "_getiter_": iter,
        "enumerate": enumerate,
        "zip": zip,
        "len": len,
        "range": range,
        "list": list,
        "dict": dict,
        "tuple": tuple,
    }


def _render_figure_code(df, render: Render) -> go.Figure:
    """Code-mode figure: run the snippet under RestrictedPython, return ``fig``.

    Mirrors ``depictio.dash.modules.figure_component.simple_code_executor`` but
    without importing the Dash-coupled ``code_mode`` helper, so it runs in the CLI.
    """
    import ast

    from RestrictedPython import compile_restricted

    code = render.code or ""
    # Guard: the dataset is read-only, like the dashboard's code mode.
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "df":
                    raise CatalogRenderError("code may not reassign 'df' (it is the dataset)")
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "df":
                raise CatalogRenderError("code may not reassign 'df' (it is the dataset)")

    bytecode = compile_restricted(code, filename="<catalog_code>", mode="exec")
    if bytecode is None:
        raise CatalogRenderError("code failed to compile (contains restricted operations)")
    g = _figure_code_globals()
    g["df"] = df.clone()
    local_vars: dict[str, Any] = {}
    exec(bytecode, g, local_vars)  # noqa: S102 — RestrictedPython-compiled, sandboxed
    fig = local_vars.get("fig")
    if fig is None:
        raise CatalogRenderError("code did not define a 'fig' variable")
    if not hasattr(fig, "to_dict"):
        raise CatalogRenderError("'fig' is not a valid Plotly figure")
    return fig


def _aggregate(df, column: str, aggregation: str):
    """Card aggregation — same semantics as ``card_component.compute_value``."""
    if column not in df.columns:
        raise CatalogRenderError(f"card column {column!r} absent from fixture {df.columns}")
    col = df[column]
    if aggregation == "count":
        return col.len()
    if aggregation == "sum":
        return col.sum()
    if aggregation == "average":
        return col.mean()
    if aggregation == "median":
        return col.median()
    if aggregation == "min":
        return col.min()
    if aggregation == "max":
        return col.max()
    if aggregation == "variance":
        return col.var()
    if aggregation == "std_dev":
        return col.std()
    if aggregation == "nunique":
        return col.n_unique()
    if aggregation == "range":
        return col.max() - col.min()
    if aggregation in ("q1", "q3"):
        return col.quantile(0.25 if aggregation == "q1" else 0.75, interpolation="linear")
    if aggregation == "mode":
        modes = col.mode()
        return modes[0] if len(modes) else None
    raise CatalogRenderError(f"unsupported card aggregation {aggregation!r}")


def _render_card(df, render: Render) -> dict[str, Any]:
    value = _aggregate(df, render.column or "", render.aggregation or "")
    return {"column": render.column, "aggregation": render.aggregation, "value": value}


def _render_table(df) -> dict[str, Any]:
    head = df.head(_TABLE_PREVIEW_ROWS)
    return {"columns": list(df.columns), "rows": head.to_dicts(), "total_rows": df.height}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _label(render: Render, index: int) -> str:
    if render.component == "figure":
        return f"Figure ({'code' if render.code else render.visu_type})"
    if render.component == "card":
        return f"Card — {render.aggregation}({render.column})"
    if render.component == "advanced_viz":
        return f"Advanced viz — {render.kind}"
    if render.component == "table":
        return "Table"
    if render.component == "multiqc":
        return f"MultiQC — {render.section or 'section'}"
    return f"{render.component} #{index}"


def render_output(
    output: CatalogOutput, render_index: int | None = None
) -> list[RenderedComponent]:
    """Render an output's ``renders_as`` (or just one, by index) on its fixture.

    Never raises for a per-render failure: each unrenderable target becomes a
    :class:`RenderedComponent` with ``ok=False`` and an ``error`` message, so a
    contributor sees every component's status in one pass.
    """
    renders = list(output.renders_as)
    if render_index is not None:
        if not 0 <= render_index < len(renders):
            raise CatalogRenderError(
                f"render index {render_index} out of range (output has {len(renders)})"
            )
        renders = [renders[render_index]]

    # Load the fixture once; if it fails, report it against every render.
    try:
        df = _load_fixture_df(output)
    except CatalogRenderError as exc:
        return [
            RenderedComponent(
                component=r.component, label=_label(r, i), kind=r.kind, ok=False, error=str(exc)
            )
            for i, r in enumerate(renders)
        ]

    results: list[RenderedComponent] = []
    for i, render in enumerate(renders):
        rc = RenderedComponent(
            component=render.component, label=_label(render, i), kind=render.kind
        )
        try:
            if render.component == "figure":
                rc.figure = (
                    _render_figure_code(df, render)
                    if render.code
                    else _render_figure_ui(df, render)
                )
            elif render.component == "card":
                rc.card = _render_card(df, render)
            elif render.component == "table":
                rc.table = _render_table(df)
            else:
                rc.ok = False
                rc.error = (
                    f"preview for component '{render.component}' is not supported yet "
                    f"(figure/card/table only for now)"
                )
        except Exception as exc:  # surface, don't crash the whole preview
            rc.ok = False
            rc.error = str(exc)
        results.append(rc)
    return results


# ---------------------------------------------------------------------------
# HTML rendering (self-contained, interactive)
# ---------------------------------------------------------------------------


def _figure_html(fig, *, include_js: bool) -> str:
    # First figure loads plotly.js (CDN); the rest reuse the global.
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if include_js else False)


def _card_html(card: dict[str, Any]) -> str:
    value = card["value"]
    shown = f"{value:.4g}" if isinstance(value, float) else _html.escape(str(value))
    return (
        '<div class="catalog-card">'
        f'<div class="catalog-card-value">{shown}</div>'
        f'<div class="catalog-card-label">{_html.escape(str(card["aggregation"]))}'
        f"({_html.escape(str(card['column']))})</div>"
        "</div>"
    )


def _table_html(table: dict[str, Any], grid_id: str) -> str:
    col_defs = [{"field": c} for c in table["columns"]]
    rows_json = json.dumps(table["rows"], default=str)
    cols_json = json.dumps(col_defs)
    note = f'<div class="catalog-note">showing {len(table["rows"])} of {table["total_rows"]} row(s)</div>'
    return (
        f'<div id="{grid_id}" class="ag-theme-alpine catalog-grid"></div>{note}'
        f"<script>(function(){{"
        f"agGrid.createGrid(document.getElementById('{grid_id}'),{{"
        f"columnDefs:{cols_json},rowData:{rows_json},"
        f"defaultColDef:{{sortable:true,filter:true,resizable:true}}"
        f"}});}})();</script>"
    )


def render_output_to_html(
    output: CatalogOutput, render_index: int | None = None, *, title: str | None = None
) -> str:
    """Render an output into one self-contained, interactive HTML page."""
    components = render_output(output, render_index)
    page_title = title or f"Catalog preview — {output.id}"

    sections: list[str] = []
    grid_count = 0
    plotly_loaded = False
    for rc in components:
        body: str
        if not rc.ok:
            body = f'<div class="catalog-error">⚠ {_html.escape(rc.error or "render failed")}</div>'
        elif rc.figure is not None:
            body = _figure_html(rc.figure, include_js=not plotly_loaded)
            plotly_loaded = True
        elif rc.card is not None:
            body = _card_html(rc.card)
        elif rc.table is not None:
            body = _table_html(rc.table, f"catalog-grid-{grid_count}")
            grid_count += 1
        else:
            body = '<div class="catalog-error">⚠ nothing rendered</div>'
        sections.append(
            f'<section class="catalog-section"><h2>{_html.escape(rc.label)}</h2>{body}</section>'
        )

    desc = _html.escape(output.description or "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_html.escape(page_title)}</title>
<link rel="stylesheet" href="{_AGGRID_CSS}"/>
<link rel="stylesheet" href="{_AGGRID_THEME_CSS}"/>
<script src="{_AGGRID_JS}"></script>
<style>
  :root {{ --fg:#1a1b1e; --muted:#868e96; --border:#e9ecef; --surface:#fff; --bg:#f8f9fa; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin:0; padding:24px;
         background:var(--bg); color:var(--fg); }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .catalog-sub {{ color:var(--muted); margin:0 0 24px; font-size:14px; }}
  .catalog-section {{ background:var(--surface); border:1px solid var(--border);
         border-radius:8px; padding:16px; margin-bottom:16px; }}
  .catalog-section h2 {{ font-size:15px; margin:0 0 12px; }}
  .catalog-card {{ display:inline-block; min-width:160px; padding:12px 16px;
         border:1px solid var(--border); border-radius:8px; }}
  .catalog-card-value {{ font-size:28px; font-weight:600; }}
  .catalog-card-label {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .catalog-grid {{ width:100%; height:420px; }}
  .catalog-note {{ color:var(--muted); font-size:12px; margin-top:6px; }}
  .catalog-error {{ color:#e03131; font-size:14px; }}
</style>
</head>
<body>
<h1>{_html.escape(output.id)}</h1>
<p class="catalog-sub">{desc}</p>
{"".join(sections)}
</body>
</html>
"""
