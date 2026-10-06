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
fields a card's `secondary_layout` needs, a MultiSelect on a column with too
many distinct values, and an advanced_viz's role bindings against the viz's
canonical schema. Each finding is `{component_id, field, message}`, worded so
`format_validation_error_for_llm`-style repair prompts can quote it.

`substance_error` and `schema_error` are the one-component wrappers the three
generating routes share: they answer the repair-prompt text, or None. They live
here rather than in `dashboard_gen` because `suggest` needs them too and cannot
import `dashboard_gen`, which imports `suggest`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import yaml

from depictio.api.v1.endpoints.ai_endpoints.context import DataContext, column_type_for
from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    INTERACTIVE_COMPATIBILITY,
)
from depictio.models.components.lite import (
    AdvancedVizLiteComponent,
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

# Types the column checks do not apply to: text has no data and multiqc reads a
# report rather than a table. advanced_viz used to sit here too, on the grounds
# that the catalog validates its role bindings. That is true of the catalog
# path alone: a component built from a `use:` handle inherits bindings the
# catalog author declared and a recipe guarantees. The ranked path the
# generator uses binds roles from `viz_suggestions_for`'s candidates and was
# validated by nothing, which is how a rarefaction over penguin bill
# measurements reached a saved dashboard and 500ed on render. See
# `_check_advanced_viz`, which now covers both paths identically.
_SKIPPED_TYPES: frozenset[str] = frozenset({"text", "multiqc"})


def validate_envelope(lite_dict: dict[str, Any]) -> DashboardDataLite:
    """Round-trip the assembled dashboard dict through the CLI's YAML loader.

    Raises `ValueError` (unparseable) or `pydantic.ValidationError` (schema)
    exactly as `DashboardDataLite.from_yaml` does; callers format them for
    the repair prompt.
    """
    content = yaml.safe_dump(lite_dict, sort_keys=False, allow_unicode=True)
    return DashboardDataLite.from_yaml(content)


class _Schema:
    """Column name -> (COLUMN_TYPES entry or None, distinct count) for one collection.

    `types` is the coarse Depictio vocabulary (`int64`, `object`, ...) the card
    and interactive compatibility tables are keyed on. `dtypes` is the raw
    polars dtype name the collection actually carries (`Float64`, `String`,
    ...), which is what `validate_binding` compares an advanced_viz role
    against; `DataContext.columns` already stores exactly that, since
    `context._summarize_columns` fills each `ColumnSummary.dtype` with
    `str(series.dtype)`. Both views are built here rather than in the models
    package so nothing in `depictio/models/` has to learn about `DataContext`.
    """

    def __init__(self, ctx: DataContext) -> None:
        self.tag = ctx.data_collection_tag or ctx.dc_name or ctx.data_collection_id
        self.types: dict[str, str | None] = {c.name: column_type_for(c.dtype) for c in ctx.columns}
        self.dtypes: dict[str, str] = {c.name: str(c.dtype) for c in ctx.columns}
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


def _binding_view(config: Any) -> SimpleNamespace:
    """The view of a viz config `validate_binding` expects: `viz_kind` + `<role>_col`.

    `validate_binding` reads every role off `<role>_col`, which is the field
    name for all but a handful of roles: ComplexHeatmap's `index` lives on
    `index_column`, Sunburst's `ranks` on `rank_cols`, Sankey's `steps` on
    `step_cols`. `role_config_key` is the single mapping the React builder, the
    catalog preview and the `use:` expansion all spell bindings through, so
    resolving each role through it here is what keeps a catalog-sourced
    component from being reported as "role not bound" when the renderer can see
    the binding perfectly well. Reading the config through this shim rather
    than teaching `validate_binding` about the aliases keeps the change on the
    AI side, where the new caller is.
    """
    from depictio.models.components.advanced_viz.catalog import role_config_key
    from depictio.models.components.advanced_viz.schemas import role_dtype_specs

    kind = config.viz_kind
    return SimpleNamespace(
        viz_kind=kind,
        **{
            f"{role}_col": getattr(config, role_config_key(kind, role), None)
            for role in role_dtype_specs(kind)
        },
    )


def _check_advanced_viz(
    cid: str, comp: AdvancedVizLiteComponent, schema: _Schema, out: list[dict[str, str]]
) -> None:
    """Check an advanced_viz's role bindings against the collection's real schema.

    Runs `validate_binding` (depictio/models/components/advanced_viz/schemas.py),
    which is what the builder's binding panel was written for and which had no
    caller anywhere in the repository. Every required role must be bound, every
    bound column (required or optional) must exist in the collection, and its
    polars dtype must be one the role accepts.

    Both sources of an advanced_viz land here identically: a catalog `use:`
    handle is already expanded into `viz_kind` + `config` by the lite model's
    `_expand_catalog_use` validator before `from_yaml` returns, so this reads
    the same bound columns the renderer will. `_binding_view` covers the roles
    whose config field is not spelled `<role>_col`, which is the one way this
    check could have started failing catalog components that render fine.

    Only blocking errors are reported. `validate_binding` downgrades a castable
    dtype mismatch (an Int column bound to a Float role, say) to a `warning`
    because the renderer coerces it; a finding carries no severity, so passing
    warnings on would read to the repair prompt as something that must be
    fixed and would send it hunting for a column that does not exist.
    """
    from depictio.models.components.advanced_viz.catalog import role_config_key
    from depictio.models.components.advanced_viz.schemas import validate_binding

    kind = str(comp.viz_kind)
    for error in validate_binding(_binding_view(comp.config), schema.dtypes):
        field = f"config.{role_config_key(kind, error.role)}"
        if error.column is None:
            out.append(
                _finding(
                    cid,
                    field,
                    f"viz_kind '{kind}' needs its '{error.role}' role bound to a column of "
                    f"'{schema.tag}'. Available: {schema.available()}",
                )
            )
        elif error.column not in schema:
            out.append(_missing_column(cid, field, error.column, schema))
        elif error.severity == "error":
            out.append(
                _finding(
                    cid,
                    field,
                    f"viz_kind '{kind}' role '{error.role}': {error.reason}",
                )
            )


def check_against_schema(
    lite: DashboardDataLite, contexts: dict[str, DataContext]
) -> list[dict[str, str]]:
    """Check every data-bound component of `lite` against its collection's columns.

    `contexts` is keyed by `data_collection_tag`. A component naming a tag
    outside it is flagged on `data_collection_tag`; text and multiqc
    components are not column-checked. Components are identified by their
    `tag`, or `component[<index>]` when they have none. Returns an empty list
    when everything fits.
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
        elif isinstance(comp, AdvancedVizLiteComponent):
            _check_advanced_viz(cid, comp, schema, findings)

    return findings


def substance_error(component: dict[str, Any]) -> str | None:
    """Reject a validated component that would render nothing.

    The lite figure defaults to a scatter with no bindings, so a UI-mode
    figure without a single `dict_kwargs` column passes the validator and
    draws an empty plot; the repair prompt asks for the bindings instead.
    """
    if component.get("component_type") == "figure" and component.get("mode", "ui") != "code":
        if not (component.get("dict_kwargs") or component.get("figure_params")):
            return (
                "figure: dict_kwargs is empty; bind at least one column (x, y, color, ...) "
                "from DATASET SCHEMA"
            )
    return None


def schema_error(component: dict[str, Any], ctx: DataContext) -> str | None:
    """`check_against_schema` on one validated component, as repair-prompt text or None."""
    lite = validate_envelope({"title": "AI", "components": [component]})
    tag = ctx.data_collection_tag or ctx.data_collection_id
    findings = check_against_schema(lite, {tag: ctx})
    if not findings:
        return None
    return "Schema check failed:\n" + "\n".join(f"- {f['field']}: {f['message']}" for f in findings)
