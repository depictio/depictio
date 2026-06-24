"""Compose a dashboard from a scanned run directory (the catalog → dashboard step).

Turns the catalog's run recognition (``match_run_dir``) into an actual
``DashboardDataLite``: each recognised tool output contributes its ``renders_as``
entries, mapped to the matching lite component, and laid out on an 8-column grid.

Pure + offline by contract: like ``catalog.py`` this module **never imports a
recipe** ``.py``. It only maps ``Render`` → lite component and places tiles; the
recipe → data-collection resolution lives in the CLI. Advanced-viz tiles are
emitted as ``use: <tool>/<render-or-output>`` references and expanded by
``AdvancedVizLiteComponent`` (role → ``<role>_col`` config) at validation time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogOutput,
    Render,
    load_catalog_entries,
    match_run_dir,
)

if TYPE_CHECKING:
    from depictio.models.models.dashboards import DashboardDataLite
    from depictio.models.models.run_info import WorkflowRunInfo

# 8-column grid (matches the real nf-core dashboards, e.g. ampliseq base.yaml).
GRID_WIDTH = 8

# Tile size (w, h) per component type on the 8-column grid.
_TILE_SIZE: dict[str, tuple[int, int]] = {
    "card": (2, 2),
    "advanced_viz": (8, 8),
    "figure": (8, 8),
    "table": (8, 6),
    "multiqc": (8, 5),
    "text": (8, 1),
}

# polars dtype name (as the catalog declares it) → depictio column_type.
_DTYPE_TO_COLUMN_TYPE: dict[str, str] = {
    "String": "object",
    "Utf8": "object",
    "Categorical": "category",
    "Boolean": "bool",
    "Date": "datetime",
    "Datetime": "datetime",
    "Time": "datetime",
    "Int8": "int64",
    "Int16": "int64",
    "Int32": "int64",
    "Int64": "int64",
    "UInt8": "int64",
    "UInt16": "int64",
    "UInt32": "int64",
    "UInt64": "int64",
    "Float32": "float64",
    "Float64": "float64",
}


class _LayoutPacker:
    """Left-to-right grid packer: wraps to a new row when a tile overflows."""

    def __init__(self, width: int = GRID_WIDTH) -> None:
        self._width = width
        self._x = 0
        self._y = 0
        self._row_h = 0

    def place(self, component_type: str) -> dict[str, int]:
        w, h = _TILE_SIZE.get(component_type, (8, 6))
        if self._x + w > self._width:
            self._x = 0
            self._y += self._row_h
            self._row_h = 0
        layout = {"x": self._x, "y": self._y, "w": w, "h": h}
        self._x += w
        self._row_h = max(self._row_h, h)
        return layout


def _short_output_id(tool_id: str, output_id: str) -> str:
    """``mosdepth`` + ``mosdepth_genome_coverage`` → ``genome_coverage``."""
    return output_id.removeprefix(f"{tool_id}_")


def _tile_title(output: CatalogOutput) -> str:
    """A short human title from the output description (first sentence)."""
    if output.description:
        return output.description.split(".")[0].strip()
    return output.id


def render_to_component_dict(
    render: Render,
    entry: CatalogEntry,
    output: CatalogOutput,
    *,
    workflow_tag: str,
    data_collection_tag: str,
    index: int,
) -> dict[str, Any] | None:
    """Map one catalog ``Render`` to a lite-component dict (no layout), or None to skip.

    Returns ``None`` for render targets that can't be grounded from the catalog
    alone (today: ``multiqc`` lacks a ``selected_plot``; non-tabular targets like
    jbrowse/image/map/text are not emitted from a run scan yet).
    """
    common: dict[str, Any] = {
        "workflow_tag": workflow_tag,
        "data_collection_tag": data_collection_tag,
        "tag": f"{output.id}-{render.component}-{index}",
        "title": _tile_title(output),
    }

    if render.component == "advanced_viz":
        short = render.id or _short_output_id(entry.id, output.id)
        comp: dict[str, Any] = {
            "component_type": "advanced_viz",
            "use": f"{entry.id}/{short}",
            **common,
        }
        if not render.id and render.kind is not None:
            # Output-id reference can render several kinds → disambiguate.
            comp["viz_kind"] = render.kind
        return comp

    if render.component == "figure":
        comp = {"component_type": "figure", **common}
        if render.code:
            comp["mode"] = "code"
            comp["code_content"] = render.code
            comp["visu_type"] = render.visu_type or "scatter"
        else:
            comp["mode"] = "ui"
            comp["visu_type"] = render.visu_type or "scatter"
            if render.dict_kwargs:
                comp["dict_kwargs"] = dict(render.dict_kwargs)
        return comp

    if render.component == "card":
        comp = {
            "component_type": "card",
            "aggregation": render.aggregation,
            "column_name": render.column,
            **common,
        }
        if render.aggregations:
            comp["aggregations"] = list(render.aggregations)
        if render.secondary_layout:
            comp["secondary_layout"] = render.secondary_layout
        if render.breakdown_col:
            comp["breakdown_col"] = render.breakdown_col
        if render.top_n_count:
            comp["top_n_count"] = render.top_n_count
        if render.coverage_max is not None:
            comp["coverage_max"] = render.coverage_max
        if render.filter_expr:
            comp["filter_expr"] = render.filter_expr
        if render.column and (dtype := output.columns.get(render.column)):
            if column_type := _DTYPE_TO_COLUMN_TYPE.get(dtype):
                comp["column_type"] = column_type
        return comp

    if render.component == "table":
        return {"component_type": "table", **common}

    # multiqc (no selected_plot) + non-tabular targets: skip for now.
    return None


def _build_lite_component(comp: dict[str, Any]):
    """Instantiate the typed lite component so validation errors surface here."""
    from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
    from depictio.models.components.lite import (
        CardLiteComponent,
        FigureLiteComponent,
        TableLiteComponent,
    )

    builders = {
        "advanced_viz": AdvancedVizLiteComponent,
        "figure": FigureLiteComponent,
        "card": CardLiteComponent,
        "table": TableLiteComponent,
    }
    return builders[comp["component_type"]](**comp)


def build_dashboard_from_run_dir(
    run_dir: str | Path,
    *,
    info: WorkflowRunInfo | None = None,
    workflow_tag: str = "",
    project_tag: str | None = None,
    title: str | None = None,
    confirm_with_versions: bool = True,
    entries: tuple[CatalogEntry, ...] | None = None,
) -> DashboardDataLite:
    """Compose a ``DashboardDataLite`` from the catalog outputs present in ``run_dir``.

    Engine-agnostic: ``info`` (any ``WorkflowRunInfo`` — Nextflow, Snakemake, …)
    drives the title and ``workflow_tag`` when not given explicitly, and scopes
    recognition to the tools the run executed (``info.tools_executed``). With no
    ``info``, ``confirm_with_versions`` falls back to the nf-core
    ``software_versions.yml`` when present.
    """
    from depictio.models.models.dashboards import DashboardDataLite

    run_dir = Path(run_dir)
    entries = entries if entries is not None else load_catalog_entries()

    if not workflow_tag and info is not None and info.pipeline_name:
        workflow_tag = info.pipeline_name

    executed_tools = info.tools_executed if info is not None and info.tools_executed else None
    matches = match_run_dir(
        run_dir,
        entries,
        confirm_with_versions=confirm_with_versions,
        executed_tools=executed_tools,
    )
    present: set[tuple[str, str]] = {(m.tool_id, m.output_id) for m in matches}

    entry_by_id = {e.id: e for e in entries}
    packer = _LayoutPacker()
    components: list = []

    for tool_id in sorted({t for t, _ in present}):
        entry = entry_by_id[tool_id]
        for output in entry.outputs:
            if (tool_id, output.id) not in present:
                continue
            for index, render in enumerate(output.renders_as):
                comp = render_to_component_dict(
                    render,
                    entry,
                    output,
                    workflow_tag=workflow_tag,
                    data_collection_tag=output.id,
                    index=index,
                )
                if comp is None:
                    continue
                comp["layout"] = packer.place(comp["component_type"])
                components.append(_build_lite_component(comp))

    if title is None:
        if info is not None and info.pipeline_name:
            version = f" {info.pipeline_version}" if info.pipeline_version else ""
            title = f"{info.short_name or info.pipeline_name}{version}"
        else:
            title = run_dir.name

    subtitle = ""
    if info is not None and info.pipeline_name:
        subtitle = f"Auto-composed from {info.pipeline_name} run"

    return DashboardDataLite(
        title=title,
        subtitle=subtitle,
        project_tag=project_tag,
        workflow_system=(info.engine if info is not None and info.engine else None),
        components=components,
    )
