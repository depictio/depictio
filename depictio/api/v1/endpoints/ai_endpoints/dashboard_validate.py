"""Validate a generated dashboard: the envelope offline, the columns against the data.

`validate_envelope` is the offline pass: the assembled lite dict goes through
`DashboardDataLite.from_yaml`, the same loader `depictio-cli dashboard import`
uses, so nothing the CLI would reject gets persisted.

`check_against_schema` is the server-side port of the CLI's
`validate_schema_online` (depictio/cli/cli/commands/dashboard.py). The CLI
fetches delta-table specs over HTTP; here the generator already holds a
`DataContext` per collection (columns with dtype and distinct count), so the
checks run on those: column existence for every column-bearing field,
aggregation and interactive type against the stored column type, the extra
fields a card's `secondary_layout` needs, and a MultiSelect on a column with
too many distinct values. Each finding is `{component_id, field, message}`,
worded so `format_validation_error_for_llm`-style repair prompts can quote it.
"""

from __future__ import annotations

from typing import Any

import yaml

from depictio.api.v1.endpoints.ai_endpoints.context import DataContext
from depictio.api.v1.endpoints.ai_endpoints.suggest import column_type_for
from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    INTERACTIVE_COMPATIBILITY,
)
from depictio.models.components.lite import (
    CardLiteComponent,
    FigureLiteComponent,
    ImageLiteComponent,
    InteractiveLiteComponent,
    MapLiteComponent,
    TableLiteComponent,
)
from depictio.models.models.dashboards import DashboardDataLite

# A MultiSelect over more distinct values than this is a wall of chips; the
# planner is told to pick another column or filter type.
MULTISELECT_MAX_DISTINCT = 50

# Card `secondary_layout` values and the field each one cannot render without.
SECONDARY_LAYOUT_REQUIRES: dict[str, str] = {
    "top_n": "breakdown_col",
    "concentration": "breakdown_col",
    "composition": "breakdown_col",
    "donut": "breakdown_col",
    "coverage": "coverage_max",
    "gauge": "coverage_max",
    "trend": "trend_col",
    "threshold": "threshold_value",
    "attrition": "attrition_cols",
}

# Plotly Express kwargs whose value names a column (a string) or columns (a list).
FIGURE_COLUMN_KEYS: tuple[str, ...] = (
    "x",
    "y",
    "z",
    "color",
    "size",
    "symbol",
    "text",
    "names",
    "values",
    "facet_col",
    "facet_row",
    "hover_name",
    "line_group",
    "line_dash",
    "pattern_shape",
    "animation_frame",
    "animation_group",
    "lat",
    "lon",
    "locations",
)
FIGURE_COLUMN_LIST_KEYS: tuple[str, ...] = ("hover_data", "dimensions", "path", "custom_data")

MAP_COLUMN_FIELDS: tuple[str, ...] = (
    "lat_column",
    "lon_column",
    "color_column",
    "size_column",
    "text_column",
    "z_column",
    "locations_column",
    "selection_column",
)

# Types the column checks do not apply to: text has no data, multiqc reads a
# report rather than a table, advanced_viz binds roles the catalog validates.
_SKIPPED_TYPES: frozenset[str] = frozenset({"text", "multiqc", "advanced_viz"})


def validate_envelope(lite_dict: dict[str, Any]) -> DashboardDataLite:
    """Round-trip the assembled dashboard dict through the CLI's YAML loader.

    Raises `ValueError` (unparseable) or `pydantic.ValidationError` (schema)
    exactly as `DashboardDataLite.from_yaml` does; callers format them for
    the repair prompt.
    """
    content = yaml.safe_dump(lite_dict, sort_keys=False, allow_unicode=True)
    return DashboardDataLite.from_yaml(content)


class _Schema:
    """Column name -> (COLUMN_TYPES entry or None, distinct count) for one collection."""

    def __init__(self, ctx: DataContext) -> None:
        self.tag = ctx.data_collection_tag or ctx.dc_name or ctx.data_collection_id
        self.types: dict[str, str | None] = {c.name: column_type_for(c.dtype) for c in ctx.columns}
        self.nunique: dict[str, int] = {c.name: int(c.nunique) for c in ctx.columns}

    def __contains__(self, column: str) -> bool:
        return column in self.types

    def available(self) -> str:
        names = sorted(self.types)
        shown = ", ".join(names[:40])
        return shown + (f", ... ({len(names)} columns)" if len(names) > 40 else "")


def _finding(component_id: str, field: str, message: str) -> dict[str, str]:
    return {"component_id": component_id, "field": field, "message": message}


def _missing_column(cid: str, field: str, column: str, schema: _Schema) -> dict[str, str]:
    return _finding(
        cid,
        field,
        f"Column '{column}' not found in '{schema.tag}'. Available: {schema.available()}",
    )


def _check_columns(
    cid: str, schema: _Schema, fields: list[tuple[str, Any]], findings: list[dict[str, str]]
) -> None:
    """Flag every (field, value) whose string value, or list of string values, is not a column."""
    for field, value in fields:
        if isinstance(value, str):
            if value and value not in schema:
                findings.append(_missing_column(cid, field, value, schema))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item and item not in schema:
                    findings.append(_missing_column(cid, field, item, schema))


def _declared_type_matches(declared: str | None, inferred: str | None) -> bool:
    if declared is None or inferred is None or declared == inferred:
        return True
    # category and object share one compatibility row; either name is fine.
    return {declared, inferred} == {"object", "category"}


def _check_card(
    cid: str, comp: CardLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    column = comp.column_name
    if column not in schema:
        out.append(_missing_column(cid, "column_name", column, schema))
    else:
        inferred = schema.types.get(column)
        if not _declared_type_matches(comp.column_type, inferred):
            out.append(
                _finding(
                    cid,
                    "column_type",
                    f"column_type='{comp.column_type}' but '{column}' is stored as '{inferred}'",
                )
            )
        valid = AGGREGATION_COMPATIBILITY.get(inferred or "", [])
        if valid:
            if comp.aggregation not in valid:
                out.append(
                    _finding(
                        cid,
                        "aggregation",
                        f"aggregation='{comp.aggregation}' is not valid for column '{column}' "
                        f"(server type: '{inferred}'). Valid: {', '.join(valid)}",
                    )
                )
            for agg in comp.aggregations or []:
                if agg not in valid:
                    out.append(
                        _finding(
                            cid,
                            "aggregations",
                            f"secondary aggregation '{agg}' is not valid for column '{column}' "
                            f"(server type: '{inferred}'). Valid: {', '.join(valid)}",
                        )
                    )

    _check_columns(
        cid,
        schema,
        [
            ("breakdown_col", comp.breakdown_col),
            ("trend_col", comp.trend_col),
            ("attrition_cols", comp.attrition_cols),
        ],
        out,
    )

    required = SECONDARY_LAYOUT_REQUIRES.get(comp.secondary_layout)
    if required and not getattr(comp, required, None):
        out.append(
            _finding(
                cid,
                required,
                f"secondary_layout='{comp.secondary_layout}' needs '{required}'; "
                f"set it or choose another secondary_layout",
            )
        )


def _check_interactive(
    cid: str, comp: InteractiveLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    column = comp.column_name
    if column not in schema:
        out.append(_missing_column(cid, "column_name", column, schema))
        return
    inferred = schema.types.get(column)
    if not _declared_type_matches(comp.column_type, inferred):
        out.append(
            _finding(
                cid,
                "column_type",
                f"column_type='{comp.column_type}' but '{column}' is stored as '{inferred}'",
            )
        )
    if inferred is not None:
        valid = INTERACTIVE_COMPATIBILITY.get(inferred, [])
        if not valid:
            out.append(
                _finding(
                    cid,
                    "interactive_component_type",
                    f"No interactive component supports column '{column}' (server type: '{inferred}')",
                )
            )
        elif comp.interactive_component_type not in valid:
            out.append(
                _finding(
                    cid,
                    "interactive_component_type",
                    f"'{comp.interactive_component_type}' is not valid for column '{column}' "
                    f"(server type: '{inferred}'). Valid: {', '.join(valid)}",
                )
            )
    distinct = schema.nunique.get(column, 0)
    if comp.interactive_component_type == "MultiSelect" and distinct > MULTISELECT_MAX_DISTINCT:
        out.append(
            _finding(
                cid,
                "interactive_component_type",
                f"MultiSelect on '{column}' would list {distinct} distinct values; pick a column "
                f"with at most {MULTISELECT_MAX_DISTINCT} or drop this filter",
            )
        )


def _check_figure(
    cid: str, comp: FigureLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    kwargs = comp.dict_kwargs or {}
    fields: list[tuple[str, Any]] = [
        (f"dict_kwargs.{key}", kwargs[key])
        for key in (*FIGURE_COLUMN_KEYS, *FIGURE_COLUMN_LIST_KEYS)
        if key in kwargs
    ]
    fields.append(("selection_column", comp.selection_column))
    _check_columns(cid, schema, fields, out)


def _check_table(
    cid: str, comp: TableLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    _check_columns(
        cid,
        schema,
        [("columns", comp.columns), ("row_selection_column", comp.row_selection_column)],
        out,
    )


def _check_map(
    cid: str, comp: MapLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    fields: list[tuple[str, Any]] = [(f, getattr(comp, f, None)) for f in MAP_COLUMN_FIELDS]
    fields.append(("hover_columns", comp.hover_columns))
    _check_columns(cid, schema, fields, out)


def _check_image(
    cid: str, comp: ImageLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    _check_columns(cid, schema, [("image_column", comp.image_column)], out)


def check_against_schema(
    lite: DashboardDataLite, contexts: dict[str, DataContext]
) -> list[dict[str, str]]:
    """Check every data-bound component of `lite` against its collection's columns.

    `contexts` is keyed by `data_collection_tag`. A component naming a tag
    outside it is flagged on `data_collection_tag`; text, multiqc and
    advanced_viz components are not column-checked. Components are
    identified by their `tag`, or `component[<index>]` when they have none.
    Returns an empty list when everything fits.
    """
    findings: list[dict[str, str]] = []
    schemas: dict[str, _Schema] = {}

    for i, comp in enumerate(lite.components):
        if isinstance(comp, dict):
            # Only an unknown component_type falls through from_yaml as a dict;
            # there is no typed model to check it against.
            continue
        component_type = comp.component_type
        if component_type in _SKIPPED_TYPES:
            continue
        cid = comp.tag or f"component[{i}]"

        dc_tag = (comp.data_collection_tag or "").strip()
        if not dc_tag:
            findings.append(
                _finding(
                    cid, "data_collection_tag", f"{component_type} needs a data_collection_tag"
                )
            )
            continue
        ctx = contexts.get(dc_tag)
        if ctx is None:
            known = ", ".join(sorted(contexts)) or "(none)"
            findings.append(
                _finding(
                    cid,
                    "data_collection_tag",
                    f"data_collection_tag '{dc_tag}' is not one of the dashboard's collections. "
                    f"Available: {known}",
                )
            )
            continue
        schema = schemas.get(dc_tag)
        if schema is None:
            schema = schemas[dc_tag] = _Schema(ctx)

        if isinstance(comp, CardLiteComponent):
            _check_card(cid, comp, schema, findings)
        elif isinstance(comp, InteractiveLiteComponent):
            _check_interactive(cid, comp, schema, findings)
        elif isinstance(comp, FigureLiteComponent):
            _check_figure(cid, comp, schema, findings)
        elif isinstance(comp, TableLiteComponent):
            _check_table(cid, comp, schema, findings)
        elif isinstance(comp, MapLiteComponent):
            _check_map(cid, comp, schema, findings)
        elif isinstance(comp, ImageLiteComponent):
            _check_image(cid, comp, schema, findings)

    return findings
