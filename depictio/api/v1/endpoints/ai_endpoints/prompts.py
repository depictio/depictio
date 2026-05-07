"""Prompt templates for the AI flows.

Kept in one place so prompt iteration is decoupled from route handlers.
"""

from __future__ import annotations

import json

from depictio.api.v1.endpoints.ai_endpoints.context import (
    DashboardContext,
    DataContext,
)

_FIGURE_SCHEMA_BLOCK = """Respond with valid JSON matching this exact schema:
{
    "visu_type": "scatter|bar|line|histogram|box|violin|heatmap",
    "dict_kwargs": {"x": "column_name", "y": "column_name", ...},
    "title": "Chart title",
    "explanation": "Why this plot is useful"
}
- "dict_kwargs" must NOT be empty. For non-histogram plots, "x" is required.
- Reference only column names that appear in the dataset schema.
- Do not wrap the JSON in markdown fences.
"""


_FIGURE_KWARGS_RULES = """RULES FOR dict_kwargs (very important):
- Include ONLY the kwargs the user explicitly asked for. If the user said "x is A, y is B", emit ONLY x and y.
- Do NOT add color, facet_row, facet_col, size, symbol, hover_data, animation_frame, log_x, log_y, marginal_x,
  marginal_y, trendline, opacity, barmode, points, notched, etc. unless the user explicitly mentioned them.
- The user's intent is the source of truth — if it's a minimal request ("box of X by Y"), produce a minimal plot.
- The 'title' field can describe the chart richly, but dict_kwargs stays minimal.
"""


def figure_from_prompt_messages(
    ctx: DataContext,
    prompt: str,
    previous_visu_type: str | None = None,
    previous_dict_kwargs: dict | None = None,
    previous_code: str | None = None,
) -> list[dict]:
    refine_block = ""
    if previous_visu_type or previous_dict_kwargs or previous_code:
        refine_block = f"""

ITERATIVE REFINEMENT MODE:
The user is iterating on a previous chart. Treat their new prompt as a
DELTA against this prior suggestion — keep everything they don't ask to
change, change only what they describe.

Previous chart:
- visu_type: {previous_visu_type or "(unknown)"}
- dict_kwargs: {json.dumps(previous_dict_kwargs or {}, default=str)}
- code: {previous_code or "(none)"}
"""
    system = f"""You are a data visualization expert. Given a dataset description and a user request,
suggest a single Plotly Express plot configuration that mirrors the user's request EXACTLY,
without inventing extra encoding channels.

CONTEXT:
{ctx.metadata_block()}

DATASET SCHEMA:
{ctx.schema_block()}

SAMPLE ROWS:
{ctx.sample_block()}
{refine_block}
{_FIGURE_KWARGS_RULES}
{_FIGURE_SCHEMA_BLOCK}"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


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
