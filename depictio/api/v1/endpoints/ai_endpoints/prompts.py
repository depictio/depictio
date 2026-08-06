"""Prompt templates for the AI flows.

Kept in one place so prompt iteration is decoupled from route handlers.
"""

from __future__ import annotations

from typing import Literal

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints.context import (
    DashboardContext,
    DashboardDataContext,
    DataContext,
)
from depictio.api.v1.endpoints.ai_endpoints.executor import grammar_block
from depictio.api.v1.endpoints.ai_endpoints.schemas import AnalyzeMode
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


def _data_block(
    data_ctx: DataContext,
    multi: DashboardDataContext | None,
    warnings: list[str] | None,
) -> tuple[str, list[str]]:
    """Render the data section, degrading gracefully under the char budget.

    `max_context_chars` has always been documented as a hard cap and has
    only ever been enforced on the section-summary prompt. Describing N
    schemas instead of one is exactly the case that overruns it, so this
    is where it starts to matter. Sample rows go first (they illustrate
    shape, they are not evidence), then whole collections from the tail.
    Whatever is dropped is reported, because a silently shortened context
    reads to the model as the complete picture.
    """
    budget = settings.ai.max_context_chars
    notes: list[str] = []

    if multi is None or not multi.collections:
        return (
            f"DATASET SCHEMA:\n{data_ctx.schema_block()}\n\n"
            f"SAMPLE ROWS:\n{data_ctx.sample_block()}",
            [],
        )

    def render(collections: list[DataContext], with_samples: bool) -> str:
        view = DashboardDataContext(
            dashboard_id=multi.dashboard_id, collections=collections, joins=multi.joins
        )
        return (
            f"DATA COLLECTIONS:\n{view.collections_block(with_samples=with_samples)}\n\n"
            f"DECLARED JOINS:\n{view.joins_block()}"
        )

    kept = list(multi.collections)
    block = render(kept, True)
    if len(block) > budget:
        block = render(kept, False)
        notes.append("Sample rows were omitted from the context to stay within the size budget.")
    while len(block) > budget and len(kept) > 1:
        dropped = kept.pop()
        notes.append(
            f"Data collection '{dropped.data_collection_tag or dropped.data_collection_id}' "
            "was left out of the context to stay within the size budget."
        )
        block = render(kept, False)

    if warnings is not None:
        warnings.extend(notes)
    return block, [c.data_collection_tag or c.data_collection_id for c in kept]


def analyze_messages(
    data_ctx: DataContext,
    dashboard_ctx: DashboardContext,
    user_prompt: str,
    selected_component_id: str | None,
    mode: AnalyzeMode = "mutate",
    multi: DashboardDataContext | None = None,
    warnings: list[str] | None = None,
) -> list[dict]:
    """System prompt for the analyze flow, in one of two exclusive modes.

    ``mutate`` asks for the original envelope: reasoning, optional Polars
    code, an answer, and dashboard actions the user can Apply.

    ``analyze`` is read-only. `actions` is absent from the envelope and
    stripped server-side if the model emits it anyway, so the surface
    rendering the reply never has to guess whether an Apply button
    belongs there.

    `mode` is the first field of the envelope in both cases: the loop is
    driven by blocking completions today, so nothing reads it early, but
    it keeps the door open for token-level streaming to route the
    rendering before the reply is complete.
    """
    selected = (
        f"\nThe user has selected component '{selected_component_id}'."
        if selected_component_id
        else ""
    )
    if mode == "analyze":
        role = """You are a data analyst producing a traceable analysis report for a
bioinformatics dashboard. You answer by computing, step by step. You do
NOT change the dashboard: this request is read-only, and any dashboard
action you propose will be discarded."""
        envelope = """{
  "mode": "analyze",
  "plan": "on your FIRST reply only: 2-4 lines stating how you will approach the question",
  "thought": "what this step is for",
  "code": "<polars expression, or empty string when you are done>",
  "answer": "final narrative in Markdown — only when code is empty",
  "findings": [
      {"claim": "one specific, quantified statement",
       "evidence_step_ids": [<indices of the executed steps that prove it>],
       "confidence": "low" | "medium" | "high"}
  ]
}"""
        rules = """- Iterate: explore, verify, cross-check. You will see your remaining
  budget (steps, tokens, seconds) after every step — plan to conclude
  before it runs out rather than being cut off.
- Every finding MUST cite evidence_step_ids of steps that ran
  successfully. A finding without evidence is dropped server-side.
  The sample rows illustrate the shape of the data; they are never
  evidence. Steps are numbered from 0 in the order they executed.
- Prefer aggregates over row dumps; output is capped per step.
- Do NOT emit an "actions" key. It will be discarded.
- Do not wrap the JSON in markdown fences."""
        contract = ""
    else:
        role = """You are a data analyst assistant for a bioinformatics dashboard.
You can answer questions about the data and propose changes to the dashboard."""
        envelope = """{
  "mode": "mutate",
  "thought": "what you intend to do",
  "code": "<polars expression or empty string>",
  "answer": "natural-language answer once you have the result",
  "actions": {
      "figure_mutations": [{"component_id": "...", "dict_kwargs_patch": {...}, "reason": "..."}],
      "filter_proposals": [<FilterProposal>, ...]
  }
}"""
        rules = """- Use the `code` field if and only if you need to compute something.
- Use `actions.filter_proposals` to change what data the dashboard shows.
- Use `actions.figure_mutations` to propose patches to existing figures
  (keys mapped to null are removed).
- Do not wrap the JSON in markdown fences."""
        contract = f"\n{FILTER_PROPOSAL_CONTRACT}\n"

    data_block, tags = _data_block(data_ctx, multi, warnings)

    system = f"""{role}

CONTEXT:
{data_ctx.metadata_block()}

{data_block}

DASHBOARD COMPONENTS:
{dashboard_ctx.components_block()}

CURRENT DASHBOARD FIGURES:
{dashboard_ctx.figures_block()}

CURRENT FILTERS:
{dashboard_ctx.filters_block()}
{selected}

{grammar_block(tags)}

Respond with valid JSON of the form:
{envelope}
{contract}
{rules}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]


def analysis_continuation(
    step_index: int,
    step_output: str,
    rows_in: int | None,
    rows_out: int | None,
    seconds: float,
    *,
    steps_left: int,
    tokens_left: int,
    seconds_left: float,
    conclude: bool,
) -> str:
    """The message that drives the read-only loop forward.

    The earlier continuation told the model, verbatim, to set `code` to ''
    and answer — which capped every analysis at exactly one executed step
    no matter what MAX_ANALYZE_STEPS said. This one permits iteration and
    shows the countdown, so concluding is a decision rather than an
    interruption.
    """
    cardinality = ""
    if rows_in is not None:
        arrow = f"{rows_in:,} rows in"
        if rows_out is not None:
            arrow += f" -> {rows_out:,} rows out"
        cardinality = f" ({arrow}, {seconds:.1f}s)"

    header = f"Observation for step {step_index}{cardinality}:\n{step_output}"
    if conclude:
        return (
            f"{header}\n\n"
            "Your budget is exhausted. Respond with the same JSON envelope, "
            'set "code" to "", and provide your final "answer" and "findings" '
            "based on the steps that already ran."
        )
    return (
        f"{header}\n\n"
        f"Budget remaining: {steps_left} steps, ~{tokens_left:,} tokens, "
        f"{seconds_left:.0f}s.\n"
        'Respond with the same JSON envelope. Set "code" to your next '
        'expression to keep investigating, or set "code" to "" and provide '
        'your final "answer" and "findings".'
    )


# ---------------------------------------------------------------------------
# Filter proposals (analyze + resolve-filters)
# ---------------------------------------------------------------------------
#
# The grammar recited below is the one enforced by `validate_filter_expr`
# in `depictio/models/components/filter_expr.py`, NOT the executor's
# allowlist. They are separate sandboxes guarding different lifetimes: a
# filter_expr is persisted on the dashboard document and re-evaluated on
# every render, whereas executor code runs once and is discarded. That is
# why this grammar is the narrower of the two and why `.over(...)`,
# `is_between` and `str.contains` appearing here says nothing about what
# `grammar_block()` will accept.

FILTER_PROPOSAL_CONTRACT = """\
Each FilterProposal is one of three kinds:
1. Set an existing interactive component (PREFERRED whenever a listed
   interactive component covers the column you want to constrain — the user
   sees and can adjust the widget):
   {"kind": "set_widget", "component_id": "<id from CURRENT FILTERS>",
    "value": <widget value>, "reason": "..."}
2. A Polars filter expression on the data collection (for conditions no
   widget covers). Grammar: col('<column>') with comparisons (==, !=, >,
   >=, <, <=), combined with & | ~ and parentheses; helpers: is_in([...]),
   is_between(a, b), str.contains/starts_with/ends_with, and mean/sum/min/
   max/count/median (optionally .over('<column>')):
   {"kind": "filter_expr", "filter_expr": "(col('depth') >= 30) & (col('qc') == 'pass')",
    "reason": "..."}
3. A percentile threshold — NEVER hand-compute percentile cutoffs; the
   server resolves the quantile on the live data. "top 3% of X" is
   q=0.97 with op ">=", "bottom 5%" is q=0.05 with op "<=":
   {"kind": "threshold", "threshold": {"column": "<numeric column>",
    "kind": "quantile", "q": 0.97, "op": ">="}, "reason": "..."}\
"""


def resolve_filters_messages(
    data_ctx: DataContext,
    dashboard_ctx: DashboardContext,
    user_prompt: str,
) -> list[dict]:
    """Single-shot NL → filter proposals (no ReAct loop).

    The model only plans filters here — no code execution, no prose
    analysis. Kept separate from `analyze_messages` so the drawer's
    "apply to dashboard" box stays fast and cheap.
    """
    system = f"""You translate a user's natural-language request into dashboard filters.

CONTEXT:
{data_ctx.metadata_block()}

DATASET SCHEMA:
{data_ctx.schema_block()}

SAMPLE ROWS:
{data_ctx.sample_block()}

CURRENT FILTERS (interactive components on the dashboard):
{dashboard_ctx.filters_block()}

Respond with valid JSON of the form:
{{
  "explanation": "one short sentence describing what will be filtered",
  "proposals": [<FilterProposal>, ...]
}}

{FILTER_PROPOSAL_CONTRACT}

- Reference only columns from DATASET SCHEMA.
- Emit the smallest set of proposals that satisfies the request.
- If the request is not a filtering request, return an empty proposals
  list and say why in "explanation".
- Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
