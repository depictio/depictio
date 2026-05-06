"""Prompt templates for the AI flows.

Kept in one place so prompt iteration is decoupled from route handlers.
"""

from __future__ import annotations

from depictio.api.v1.endpoints.ai_endpoints.context import (
    DashboardContext,
    DataContext,
)


_FIGURE_SCHEMA_BLOCK = """Respond with valid JSON matching this exact schema:
{
    "visu_type": "scatter|bar|line|histogram|box|violin|heatmap",
    "dict_kwargs": {"x": "column_name", "y": "column_name", "color": "column_name", ...},
    "title": "Chart title",
    "explanation": "Why this plot is useful"
}
- "dict_kwargs" must NOT be empty. For non-histogram plots, "x" is required.
- Reference only column names that appear in the dataset schema.
- Do not wrap the JSON in markdown fences.
"""


def figure_from_prompt_messages(ctx: DataContext, prompt: str) -> list[dict]:
    system = f"""You are a data visualization expert. Given a dataset description and a user request,
suggest a single Plotly Express plot configuration.

CONTEXT:
{ctx.metadata_block()}

DATASET SCHEMA:
{ctx.schema_block()}

SAMPLE ROWS:
{ctx.sample_block()}

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
