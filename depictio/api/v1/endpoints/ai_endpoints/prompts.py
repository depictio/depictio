"""Prompt templates for the AI flows.

Kept in one place so prompt iteration is decoupled from route handlers.
"""

from __future__ import annotations

from typing import Literal

from depictio.api.v1.endpoints.ai_endpoints.context import (
    DashboardContext,
    DataContext,
)
from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    INTERACTIVE_COMPATIBILITY,
    MAP_STYLES,
    MAP_TYPES,
    VISU_TYPES,
)

ComponentType = Literal[
    "figure",
    "card",
    "interactive",
    "table",
    "image",
    "multiqc",
    "map",
]


# ---------------------------------------------------------------------------
# Component-from-prompt: per-type constraint sheets + YAML examples
# ---------------------------------------------------------------------------


def _aggregation_lines() -> str:
    return "\n".join(
        f"  {col_type:9s} -> {', '.join(aggs)}"
        for col_type, aggs in AGGREGATION_COMPATIBILITY.items()
    )


def _interactive_lines() -> str:
    return "\n".join(
        f"  {col_type:9s} -> {', '.join(types) if types else '(unsupported)'}"
        for col_type, types in INTERACTIVE_COMPATIBILITY.items()
    )


_CONSTRAINT_SHEETS: dict[str, str] = {
    "figure": (
        f"FIGURE: Plotly Express chart. Required: visu_type, dict_kwargs.\n"
        f"  visu_type ∈ {{{', '.join(VISU_TYPES)}}}\n"
        "  dict_kwargs maps Plotly Express kwargs (x, y, color, ...) to column names.\n"
        "  Reference only columns from the DATASET SCHEMA. Histogram does not require y.\n"
        "  Optional: mode='ui' (default) or mode='code' with code_content for custom code."
    ),
    "card": (
        "CARD: single aggregated statistic. Required: aggregation, column_name, column_type.\n"
        "Allowed aggregation × column_type:\n"
        f"{_aggregation_lines()}\n"
        "Optional: aggregations (list of secondary stats, same compatibility rules),\n"
        "filter_expr (Polars expression scoped to the DC), icon_name, icon_color, title."
    ),
    "interactive": (
        "INTERACTIVE: filter control. Required: interactive_component_type, column_name, column_type.\n"
        "Allowed interactive_component_type × column_type:\n"
        f"{_interactive_lines()}\n"
        "Timeline requires timescale ∈ (year, month, day, hour, minute).\n"
        "Optional: filter_expr, placement (left|top — only Timeline supports top),\n"
        "group (≤ 3 components share a group), title, icon_name."
    ),
    "table": (
        "TABLE: tabular view of the DC. Optional: columns (list of column names to show),\n"
        "page_size (default 10), sortable, filterable, row_selection_enabled +\n"
        "row_selection_column (selecting rows filters other components)."
    ),
    "image": (
        "IMAGE: thumbnail grid from an image-path column. Required: image_column.\n"
        "Optional: thumbnail_size (px, default 150), columns (grid width, default 4),\n"
        "max_images (default 20). s3_base_folder is resolved server-side; omit unless\n"
        "the user explicitly overrides it."
    ),
    "multiqc": (
        "MULTIQC: render a single MultiQC plot. Required: selected_module, selected_plot.\n"
        "Both names must match an entry in the DC's MultiQC catalog. Ask the user if\n"
        "the prompt is too vague to disambiguate."
    ),
    "map": (
        f"MAP: tile-based map. Required: map_type ∈ {{{', '.join(MAP_TYPES)}}}.\n"
        "scatter_map / density_map require lat_column + lon_column (both numeric).\n"
        "density_map additionally requires z_column.\n"
        "choropleth_map requires locations_column + color_column + a geojson source\n"
        "(geojson_data, geojson_url, or geojson_dc_id).\n"
        f"map_style ∈ {{{', '.join(MAP_STYLES)}}}. Optional: color_column, size_column,\n"
        "hover_columns, text_column, opacity, size_max, title."
    ),
}


_YAML_EXAMPLES: dict[str, str] = {
    "figure": """\
component_type: figure
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
visu_type: scatter
dict_kwargs:
  x: <column>
  y: <column>
  color: <column>
""",
    "card": """\
component_type: card
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
aggregation: average
column_name: <column>
column_type: float64
""",
    "interactive": """\
component_type: interactive
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
interactive_component_type: MultiSelect
column_name: <column>
column_type: object
""",
    "table": """\
component_type: table
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
columns: []
""",
    "image": """\
component_type: image
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
image_column: <column>
""",
    "multiqc": """\
component_type: multiqc
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
selected_module: <module name>
selected_plot: <plot name>
""",
    "map": """\
component_type: map
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
map_type: scatter_map
lat_column: <numeric column>
lon_column: <numeric column>
""",
}


def _constraint_sheet(component_type: ComponentType) -> str:
    return _CONSTRAINT_SHEETS[component_type]


def _example_yaml(component_type: ComponentType) -> str:
    return _YAML_EXAMPLES[component_type]


def _data_tags_block(ctx: DataContext) -> str:
    """Hand the LLM the workflow_tag + data_collection_tag explicitly.

    Without this the model would guess from the project name and produce
    YAML that fails to resolve against MongoDB.
    """
    return (
        f"workflow_tag: {ctx.workflow_tag or '(unknown)'}\n"
        f"data_collection_tag: {ctx.data_collection_tag or ctx.dc_name or '(unknown)'}"
    )


def component_from_prompt_messages(
    ctx: DataContext,
    prompt: str,
    component_type: ComponentType,
    current: dict | None = None,
) -> list[dict]:
    """System + user messages for the /ai/component-from-prompt endpoint.

    `current` is set in the "modify existing component" flow — we
    include its YAML representation so the LLM can produce a revision
    rather than a from-scratch component.
    """
    mode_note = "REVISE an existing component" if current else "CREATE a new component"

    current_block = ""
    if current:
        # Lazy import to avoid circular: component_yaml.dump_single is
        # in the same package and pulls in DashboardDataLite indirectly.
        from depictio.api.v1.endpoints.ai_endpoints.component_yaml import dump_single

        current_block = (
            "\nCURRENT COMPONENT (YAML the user is revising):\n"
            f"```yaml\n{dump_single(current)}```\n"
            "Modify the fields the user asked to change. Preserve everything else.\n"
        )

    system = f"""You are filling a single Depictio dashboard component for the user.
You will {mode_note} of type "{component_type}".

OUTPUT FORMAT — strict:
- Emit ONE YAML mapping describing the component.
- No prose, no Markdown fences, no comments — YAML only.
- Use the workflow_tag and data_collection_tag from CONTEXT verbatim.

CONTEXT:
{ctx.metadata_block()}

DATA SOURCE TAGS (use these literally):
{_data_tags_block(ctx)}

DATASET SCHEMA:
{ctx.schema_block()}

SAMPLE ROWS:
{ctx.sample_block()}

COMPONENT CONSTRAINTS:
{_constraint_sheet(component_type)}

EXAMPLE SHAPE FOR component_type="{component_type}":
```yaml
{_example_yaml(component_type)}```
{current_block}
RULES:
- Reference only column names that appear in DATASET SCHEMA.
- Match user intent literally: if they ask for "histogram of x", emit a histogram
  with that x — do not add color/facet/size unless they explicitly asked.
- The YAML must be valid against the Depictio Lite schema for the chosen type.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


# ---------------------------------------------------------------------------
# Kept legacy prompts for /ai/suggest-figures and /ai/analyze
# ---------------------------------------------------------------------------


def suggest_figures_messages(ctx: DataContext, n: int) -> list[dict]:
    system = f"""You are a data visualization expert. Propose {n} distinct Plotly Express plots
that surface the most useful patterns in this dataset. Favor variety
(distribution, comparison, relationship) over slight variations of the same
chart. Avoid suggesting the same column pair twice.

CONTEXT:
{ctx.metadata_block()}

DATASET SCHEMA:
{ctx.schema_block()}

SAMPLE ROWS:
{ctx.sample_block()}

Respond with valid JSON of the form:
{{"suggestions": [<PlotSuggestion>, <PlotSuggestion>, ...]}}

Each PlotSuggestion follows this schema:
{{
    "visu_type": "scatter|bar|line|histogram|box|violin|heatmap",
    "dict_kwargs": {{"x": "column_name", "y": "column_name", ...}},
    "title": "Chart title",
    "explanation": "Why this plot is useful"
}}

- "dict_kwargs" must NOT be empty. For non-histogram plots, "x" is required.
- Reference only column names that appear in the dataset schema.
- Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Suggest {n} figures."},
    ]


def analyze_messages(
    data_ctx: DataContext,
    dashboard_ctx: DashboardContext,
    user_prompt: str,
    selected_component_id: str | None,
) -> list[dict]:
    """System prompt for the analyze flow.

    The model is asked to produce a plan: free-text reasoning, optional
    Polars expression(s) for execution, an answer, and any dashboard
    actions (filter changes / figure mutations) — all wrapped in a single
    JSON envelope so we can parse incrementally.
    """
    selected = (
        f"\nThe user has selected component '{selected_component_id}'."
        if selected_component_id
        else ""
    )
    system = f"""You are a data analyst assistant for a bioinformatics dashboard.
You can answer questions about the data and propose changes to the dashboard.

CONTEXT:
{data_ctx.metadata_block()}

DATASET SCHEMA:
{data_ctx.schema_block()}

SAMPLE ROWS:
{data_ctx.sample_block()}

CURRENT DASHBOARD FIGURES:
{dashboard_ctx.figures_block()}

CURRENT FILTERS:
{dashboard_ctx.filters_block()}
{selected}

When you need to compute something, write a single Polars expression on a
DataFrame named `df`. Only the following are allowed:
- `df` and `pl` (polars import)
- DataFrame methods: filter, select, with_columns, group_by, agg, sort,
  head, drop_nulls, unique, describe, value_counts, n_unique, null_count,
  min/max/mean/median/sum/std/var/count
- pl helpers: col, lit, when, sum/mean/min/max/count, type casts (Int64,
  Float64, Utf8, Boolean, Date)

NO imports, NO file I/O, NO lambdas, NO bare function calls.

Respond with valid JSON of the form:
{{
  "thought": "what you intend to do",
  "code": "<polars expression or empty string>",
  "answer": "natural-language answer once you have the result",
  "actions": {{
      "filters": [{{"component_id": "...", "value": ..., "reason": "..."}}],
      "figure_mutations": [{{"component_id": "...", "dict_kwargs_patch": {{...}}, "reason": "..."}}]
  }}
}}

- Use the `code` field if and only if you need to compute something.
- Use `actions.filters` to suggest setting interactive components.
- Use `actions.figure_mutations` to propose patches to existing figures
  (keys mapped to null are removed).
- Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
