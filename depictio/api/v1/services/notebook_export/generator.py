"""From an :class:`ExportPlan` to a marimo notebook.

The endpoint gathers everything that needs Mongo, Delta or link resolution
into an ``ExportPlan``; this module only turns the plan into cells, so it
runs in tests with no infrastructure. The same pass that names cells also
produces the preflight the export modal shows.
"""

from __future__ import annotations

import pprint
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import polars as pl

from depictio.models.models.analysis_state import (
    AnalysisState,
    NotebookPreflight,
    NotebookPreflightComponent,
    NotebookPreflightDC,
    NotebookPreflightStage,
)

from .aggregations import agg_expr_source
from .cells import Cell, md_cell, render_notebook
from .classify import Classification, classify
from .names import NameAllocator, slug
from .predicates import PredicateSource, emit_filter_expr, emit_predicate
from .provenance import header_markdown
from .reading_order import ComponentUnit, MarkdownUnit, ordered_units

DEFAULT_MARIMO_VERSION = "0.24.0"


@dataclass
class DCPlan:
    dc_id: str
    tag: str
    wf_id: str | None = None
    dtypes: dict[str, pl.DataType] | None = None  # None = schema unknown at export
    initial_rows: int | None = None
    n_cols: int | None = None

    @property
    def columns(self) -> set[str] | None:
        return set(self.dtypes) if self.dtypes is not None else None

    def dtype(self, column: str) -> pl.DataType | None:
        return (self.dtypes or {}).get(column)


@dataclass
class StagePlan:
    """One active filter, and what it adds to each data collection."""

    index: str
    label: str
    column: str | None
    interactive_component_type: str | None
    value: Any
    source_dc_id: str | None
    # Cleaned filter entries (``clean_filter_payload`` shape, plus ``index``
    # and ``link`` flags) that become applicable to each DC at this stage —
    # the user's own filter where its DC matches, and any link-resolved ones.
    per_dc: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    rows_by_dc: dict[str, int | None] = field(default_factory=dict)


@dataclass
class ExportPlan:
    tabs: list[dict[str, Any]]
    project: dict[str, Any] | None
    state: AnalysisState
    dcs: list[DCPlan]
    stages: list[StagePlan]
    title: str
    subtitle: str | None = None
    exported_by: str | None = None
    exported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    instance: str | None = None
    api_url: str = "https://depictio.example.org"
    warnings: list[str] = field(default_factory=list)
    marimo_version: str = DEFAULT_MARIMO_VERSION

    @property
    def dashboard_id(self) -> str:
        main = self.tabs[0] if self.tabs else {}
        return str(main.get("dashboard_id") or self.state.context.dashboard_id)

    @property
    def stem(self) -> str:
        return slug(self.title, max_len=60, fallback="dashboard")


@dataclass
class ComponentEntry:
    unit: ComponentUnit
    verdict: Classification
    name: str | None


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _comment(text: str) -> str:
    return "\n".join(f"# {line}" if line else "#" for line in _sentence(text).split("\n"))


def _kwargs_source(kwargs: dict[str, Any]) -> list[str]:
    lines = []
    for k, v in kwargs.items():
        rendered = pprint.pformat(v, width=80, sort_dicts=False)
        if "\n" in rendered:
            rendered = rendered.replace("\n", "\n    ")
        lines.append(f"    {k}={rendered},")
    return lines


def _fmt_value(value: Any) -> str:
    if isinstance(value, list):
        shown = ", ".join(str(v) for v in value[:6])
        if len(value) > 6:
            shown += f", … ({len(value)} values)"
        return shown
    return str(value)


class NotebookBuilder:
    def __init__(self, plan: ExportPlan) -> None:
        self.plan = plan
        self.names = NameAllocator()
        self.dc_by_id: dict[str, DCPlan] = {dc.dc_id: dc for dc in plan.dcs}
        self.df_names: dict[str, str] = {}
        self.final_names: dict[str, str] = {}
        for dc in plan.dcs:
            self.df_names[dc.dc_id] = self.names.claim("df", dc.tag, fallback="table")
            self.names.reserve(f"final_{self.df_names[dc.dc_id][3:]}")
            self.final_names[dc.dc_id] = f"final_{self.df_names[dc.dc_id][3:]}"
        self._entries: list[tuple[MarkdownUnit | ComponentEntry, str | None]] | None = None

    # ------------------------------------------------------------------ names
    def _stage_name(self, k: int, dc_id: str) -> str:
        return f"stage_{k}_{self.df_names[dc_id][3:]}"

    def entries(self) -> list[tuple[MarkdownUnit | ComponentEntry, str | None]]:
        """Reading-order units with their verdict and the name each cell defines."""
        if self._entries is not None:
            return self._entries
        out: list[tuple[MarkdownUnit | ComponentEntry, str | None]] = []
        current_tab: str | None = None
        for unit in ordered_units(self.plan.tabs):
            if isinstance(unit, MarkdownUnit):
                if unit.kind == "tab":
                    current_tab = unit.text
                out.append((unit, current_tab))
                continue
            meta = unit.meta
            verdict = classify(meta)
            dc_id = str(meta.get("dc_id") or "")
            if verdict.status == "code" and meta.get("component_type") != "text":
                if dc_id not in self.dc_by_id:
                    verdict = Classification(
                        "api",
                        "its data collection has no Delta table in this export "
                        "(e.g. a MultiQC report); re-rendered through the Depictio API",
                        kind=verdict.kind,
                    )
            name = self._name_for(meta, verdict)
            out.append((ComponentEntry(unit=unit, verdict=verdict, name=name), current_tab))
        self._entries = out
        return out

    def _name_for(self, meta: dict[str, Any], verdict: Classification) -> str | None:
        ctype = str(meta.get("component_type") or "")
        hint = meta.get("title") or meta.get("column_name") or meta.get("index")
        if verdict.status == "omitted" or ctype == "text":
            return None
        if verdict.status == "api":
            return self.names.claim("viz", hint)
        prefix = {"figure": "fig", "card": "card", "table": "table"}.get(ctype, "tile")
        return self.names.claim(prefix, hint)

    # -------------------------------------------------------------- preflight
    def preflight(self, *, ipynb_available: bool) -> NotebookPreflight:
        components: list[NotebookPreflightComponent] = []
        counts = {"code": 0, "api": 0, "omitted": 0}
        for entry, tab in self.entries():
            if isinstance(entry, MarkdownUnit):
                continue
            meta = entry.unit.meta
            counts[entry.verdict.status] = counts.get(entry.verdict.status, 0) + 1
            components.append(
                NotebookPreflightComponent(
                    index=str(meta.get("index") or ""),
                    title=meta.get("title"),
                    component_type=str(meta.get("component_type") or ""),
                    kind=entry.verdict.kind,
                    status=entry.verdict.status,  # type: ignore[arg-type]
                    reason=entry.verdict.reason,
                    name=entry.name,
                    tab=tab,
                    section=entry.unit.section,
                )
            )
        return NotebookPreflight(
            components=components,
            dcs=[
                NotebookPreflightDC(dc_id=dc.dc_id, tag=dc.tag, rows=dc.initial_rows)
                for dc in self.plan.dcs
            ],
            stages=[
                NotebookPreflightStage(index=s.index, label=s.label, rows_by_dc=s.rows_by_dc)
                for s in self.plan.stages
            ],
            warnings=list(self.plan.warnings),
            ipynb_available=ipynb_available,
            counts={**counts, "stages": len(self.plan.stages), "dcs": len(self.plan.dcs)},
        )

    # ------------------------------------------------------------------ build
    def build(self) -> str:
        cells: list[Cell] = []
        cells.append(self._imports_cell())
        cells.append(self._connection_cell())
        cells.append(md_cell(self._header()))
        cells.append(self._state_cell())
        cells.extend(self._data_cells())
        cells.extend(self._funnel_cells())
        cells.extend(self._group_cells())
        cells.extend(self._panel_cells())
        cells.extend(self._tile_cells())
        cells.append(
            md_cell(
                "---\n\n*Generated by Depictio's notebook export. The dashboard's theme and "
                "brand colours are not reproduced; every number is.*"
            )
        )
        return render_notebook(cells, generated_with=self.plan.marimo_version)

    def _imports_cell(self) -> Cell:
        return Cell(
            "import datetime\n"
            "\n"
            "import marimo as mo\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import plotly.express as px\n"
            "import plotly.graph_objects as go\n"
            "import polars as pl\n"
            "from depictio.notebook import DepictioClient\n"
            "from polars import col, lit"
        )

    def _connection_cell(self) -> Cell:
        return Cell(
            _comment(
                "Reads DEPICTIO_API_URL and DEPICTIO_API_TOKEN, or ~/.depictio/CLI.yaml. "
                "Offline: set DEPICTIO_DATA_DIR to a folder of <dc_id>.parquet files"
            )
            + "\nclient = DepictioClient()\n"
            + f"DASHBOARD_ID = {self.plan.dashboard_id!r}"
        )

    def _header(self) -> str:
        return header_markdown(
            title=self.plan.title,
            subtitle=self.plan.subtitle,
            project=self.plan.project,
            exported_by=self.plan.exported_by,
            exported_at=self.plan.exported_at,
            instance=self.plan.instance,
            api_url=self.plan.api_url,
            stem=self.plan.stem,
            state_version=self.plan.state.version,
            warnings=self.plan.warnings,
        )

    def _state_cell(self) -> Cell:
        state = self.plan.state.model_dump(mode="json", exclude_none=True)
        literal = pprint.pformat(state, width=88, sort_dicts=False)
        return Cell(
            _comment(
                "The analysis state as exported: filters, funnel order, groups. Components "
                "rendered by Depictio below re-use it; edit it to change what they show"
            )
            + f"\ndepictio_state = {literal}"
        )

    def _data_cells(self) -> list[Cell]:
        cells = []
        for dc in self.plan.dcs:
            shape = ""
            if dc.initial_rows is not None:
                shape = f": {dc.initial_rows:,} rows"
                if dc.n_cols is not None:
                    shape += f", {dc.n_cols} columns"
                shape += " at export time"
            cells.append(
                Cell(
                    _comment(f'Data collection "{dc.tag}"{shape}')
                    + f"\n{self.df_names[dc.dc_id]} = client.data({dc.dc_id!r})"
                )
            )
        return cells

    # ---------------------------------------------------------------- funnel
    def _funnel_cells(self) -> list[Cell]:
        cells: list[Cell] = []
        stages = self.plan.stages
        if not stages:
            cells.append(
                md_cell(
                    "## Filters\n\nNo filter was active when this notebook was exported: "
                    "every tile below reads the whole table."
                )
            )
        else:
            cells.append(
                md_cell(
                    "## Filters, in funnel order\n\nEach cell applies one filter on top of the "
                    "previous stage, in the order the funnel view showed. The row counts in the "
                    "comments are what the dashboard measured at export time; reordering "
                    "stages changes the intermediate counts, never the final one."
                )
            )
        prev = dict(self.df_names)
        for k, stage in enumerate(stages, start=1):
            lines: list[str] = []
            head = f'Stage {k}, "{stage.label}"'
            if stage.interactive_component_type:
                head += f" ({stage.interactive_component_type})"
            if stage.value is not None:
                head += f": {_fmt_value(stage.value)}"
            counts = []
            for dc in self.plan.dcs:
                n = stage.rows_by_dc.get(dc.dc_id)
                if n is not None:
                    counts.append(f"{dc.tag} → {n:,} rows")
            if counts:
                head += ". After this stage: " + "; ".join(counts)
            lines.append(_comment(head))
            for dc in self.plan.dcs:
                name = self._stage_name(k, dc.dc_id)
                self.names.reserve(name)
                entries = stage.per_dc.get(dc.dc_id) or []
                applied = False
                lines.append(f"{name} = {prev[dc.dc_id]}")
                for entry in entries:
                    src = self._entry_source(dc, entry)
                    if src is None:
                        column = entry.get("column_name")
                        lines.append(
                            f"# '{column}' is not a column of {dc.tag}: the server skips this "
                            "filter here, and so does the notebook"
                        )
                        continue
                    if entry.get("link"):
                        lines.append(
                            f"# values resolved at export time through the cross-collection "
                            f"link {entry.get('index')!r}"
                        )
                    lines.extend(src.as_lines(name))
                    applied = True
                    fexpr = entry.get("filter_expr")
                    if fexpr:
                        lines.append(f"{name} = {name}.filter({emit_filter_expr(str(fexpr))})")
                if not applied and not entries:
                    lines[-1] += f"  # this filter does not touch {dc.tag}"
                prev[dc.dc_id] = name
            cells.append(Cell("\n".join(lines)))
        final_lines = [_comment("Every tile below reads this frame: the last funnel stage")]
        for dc in self.plan.dcs:
            final_lines.append(f"{self.final_names[dc.dc_id]} = {prev[dc.dc_id]}")
        cells.append(Cell("\n".join(final_lines)))
        return cells

    def _entry_source(self, dc: DCPlan, entry: dict[str, Any]) -> PredicateSource | None:
        column = str(entry.get("column_name") or "")
        itype = entry.get("interactive_component_type")
        if dc.columns is not None and column not in dc.columns and itype != "__link_no_match__":
            return None
        return emit_predicate(itype, column, entry.get("value"), dc.dtype(column))

    # ---------------------------------------------------------------- groups
    def _pick_dc(self, dc_id: str | None) -> DCPlan | None:
        if dc_id and dc_id in self.dc_by_id:
            return self.dc_by_id[dc_id]
        return self.plan.dcs[0] if self.plan.dcs else None

    def _group_cells(self) -> list[Cell]:
        groups = self.plan.state.groups
        if not groups:
            return []
        cells = [
            md_cell(
                "## Selection groups\n\nGroups saved in the viewer, each as its own frame "
                "over the final stage. A group whose filter was active in the viewer is "
                "already part of the funnel above; it is repeated here so it can be used "
                "on its own."
            )
        ]
        for g in groups:
            dc = self._pick_dc(g.dc_id)
            name = self.names.claim("group", g.name)
            active = "filter active" if g.filter_active else "filter off"
            head = _comment(
                f'Selection group "{g.name}" ({active}): {len(g.values)} values of {g.column_name}'
            )
            if dc is None:
                cells.append(Cell(head + f"\n{name} = None  # no data collection in this export"))
                continue
            if dc.columns is not None and g.column_name not in dc.columns:
                cells.append(
                    Cell(
                        head
                        + f"\n{name} = {self.final_names[dc.dc_id]}  # '{g.column_name}' is not "
                        f"a column of {dc.tag}: nothing to select"
                    )
                )
                continue
            src = emit_predicate(
                "MultiSelect", g.column_name, list(g.values), dc.dtype(g.column_name)
            )
            body = [head, f"{name} = {self.final_names[dc.dc_id]}"]
            if src is not None:
                body.extend(src.as_lines(name))
            cells.append(Cell("\n".join(body)))
        return cells

    def _panel_cells(self) -> list[Cell]:
        panels = self.plan.state.split_panels
        if not panels:
            return []
        cells = [
            md_cell(
                "## Split panels\n\nThe viewer was split into small multiples; each panel is "
                "the final stage narrowed by its own constraints."
            )
        ]
        for p in panels:
            name = self.names.claim("panel", p.name)
            dc_hint = None
            for c in p.constraints:
                dc_hint = (c.metadata.dc_id if c.metadata else None) or dc_hint
            dc = self._pick_dc(dc_hint)
            body = [_comment(f'Panel "{p.name}"')]
            if dc is None:
                body.append(f"{name} = None  # no data collection in this export")
                cells.append(Cell("\n".join(body)))
                continue
            body.append(f"{name} = {self.final_names[dc.dc_id]}")
            for c in p.constraints:
                column = c.column_name or (c.metadata.column_name if c.metadata else None)
                if not column:
                    continue
                if dc.columns is not None and column not in dc.columns:
                    body.append(f"# '{column}' is not a column of {dc.tag}: constraint skipped")
                    continue
                src = emit_predicate(
                    c.interactive_component_type or "MultiSelect", column, c.value, dc.dtype(column)
                )
                if src is not None:
                    body.extend(src.as_lines(name))
            cells.append(Cell("\n".join(body)))
        return cells

    # ----------------------------------------------------------------- tiles
    def _tile_cells(self) -> list[Cell]:
        cells: list[Cell] = []
        for entry, _tab in self.entries():
            if isinstance(entry, MarkdownUnit):
                level = max(1, min(6, entry.level + (1 if entry.kind == "section" else 0)))
                text = f"{'#' * level} {entry.text}"
                if entry.description:
                    text += f"\n\n{entry.description}"
                cells.append(md_cell(text))
                continue
            cells.append(self._tile_cell(entry))
        return cells

    def _tile_cell(self, entry: ComponentEntry) -> Cell:
        meta = entry.unit.meta
        ctype = str(meta.get("component_type") or "")
        title = str(meta.get("title") or meta.get("index") or ctype)
        if ctype == "text":
            return self._text_cell(meta)
        if entry.verdict.status == "omitted":
            return md_cell(f"> **{title}** is not in this notebook: {entry.verdict.reason}.")
        if entry.verdict.status == "api":
            return self._api_cell(entry, title)
        dc = self.dc_by_id[str(meta.get("dc_id") or "")]
        final = self.final_names[dc.dc_id]
        name = entry.name or self.names.claim("tile", title)
        fexpr = meta.get("filter_expr")
        source = final
        prelude: list[str] = []
        if fexpr:
            prelude.append(f"_scoped = {final}.filter({emit_filter_expr(str(fexpr))})")
            source = "_scoped"
        if ctype == "card":
            agg = str(meta.get("aggregation") or "")
            column = str(meta.get("column_name") or "")
            expr = agg_expr_source(column, agg) or "pl.lit(None)"
            body = [
                _comment(f'Card "{title}": {agg} of {column} over the filtered rows'),
                *prelude,
                f"{name} = {source}.select({expr}).item()",
                name,
            ]
            return Cell("\n".join(body))
        if ctype == "table":
            columns = [c for c in (meta.get("columns") or []) if isinstance(c, str)]
            page = int(meta.get("page_size") or 100)
            select = f".select({columns!r})" if columns else ""
            body = [
                _comment(f'Table "{title}": the first {page} filtered rows'),
                *prelude,
                f"{name} = {source}{select}.head({page})",
                name,
            ]
            return Cell("\n".join(body))
        if ctype == "figure":
            return self._figure_cell(meta, name, source, prelude, title)
        return md_cell(f"> **{title}** ({ctype}) has no code path yet.")

    def _text_cell(self, meta: dict[str, Any]) -> Cell:
        title = str(meta.get("title") or "").strip()
        body = str(meta.get("body") or "").strip()
        order = meta.get("order")
        try:
            level = max(1, min(6, int(order))) if order is not None else 3
        except (TypeError, ValueError):
            level = 3
        parts = []
        if title:
            parts.append(f"{'#' * level} {title}")
        if body:
            parts.append(body)
        return md_cell("\n\n".join(parts) or "*(empty text tile)*")

    def _api_cell(self, entry: ComponentEntry, title: str) -> Cell:
        meta = entry.unit.meta
        tab_id = str(entry.unit.tab.get("dashboard_id") or self.plan.dashboard_id)
        kind = entry.verdict.kind or str(meta.get("component_type") or "component")
        name = entry.name or self.names.claim("viz", title)
        head = _comment(
            f'"{title}" ({kind}) is rendered by Depictio with the state above: '
            f"{entry.verdict.reason}. `.figure` is the Plotly figure, `.data` the data, "
            "`.html` the interactive tile"
        )
        return Cell(
            head + f"\n{name} = client.component({tab_id!r}, {str(meta.get('index'))!r}, "
            "state=depictio_state)" + f"\n{name}"
        )

    def _figure_cell(
        self, meta: dict[str, Any], name: str, source: str, prelude: list[str], title: str
    ) -> Cell:
        from depictio.api.v1.services.figure.figure_builder import clean_px_kwargs

        mode = str(meta.get("mode") or "ui")
        if mode == "code":
            code = str(meta.get("code_content") or "").rstrip()
            code_lines = ["    " + line if line.strip() else "" for line in code.split("\n")]
            body = [
                _comment(f'Figure "{title}", code mode: the author\'s code, verbatim'),
                *prelude,
                f"def _make_{name}(df):",
                *code_lines,
                "    return fig",
                "",
                f"{name} = _make_{name}({source})",
                name,
            ]
            return Cell("\n".join(body))
        visu = str(meta.get("visu_type") or "scatter")
        kwargs = clean_px_kwargs(dict(meta.get("dict_kwargs") or {}))
        kwargs.pop("template", None)
        body = [
            _comment(
                f'Figure "{title}": px.{visu} over the filtered frame. The dashboard theme '
                "is not reproduced"
            ),
            *prelude,
            f"{name} = px.{visu}(",
            f"    {source},",
            *_kwargs_source(kwargs),
            ")",
            name,
        ]
        return Cell("\n".join(body))


def generate_marimo(plan: ExportPlan) -> str:
    return NotebookBuilder(plan).build()
