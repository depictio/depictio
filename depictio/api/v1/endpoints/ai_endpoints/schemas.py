"""Pydantic schemas for the AI endpoints.

Ported from the `claude/ai-compatible-depictio-gR9q7` exploration branch
(itself descended from the `dev/litellm-prototype` prototype, PR #879) and
extended with the action types the analyze endpoint can return so the React
side can mutate filters and existing figures based on an LLM-generated plan.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

VisuType = Literal[
    "scatter",
    "bar",
    "line",
    "histogram",
    "box",
    "violin",
    "heatmap",
]


class PlotSuggestion(BaseModel):
    """A single Plotly Express plot configuration proposed by the LLM."""

    visu_type: VisuType
    dict_kwargs: dict[str, Any] = Field(default_factory=dict)
    title: str
    explanation: str
    # Synthesized server-side from (visu_type, dict_kwargs) so the React
    # drawer can show users the Python that would render the chart they
    # asked for. Display-only; never eval'd. Empty when not yet computed
    # (e.g. when validating raw LLM output).
    code: str = ""

    @field_validator("dict_kwargs")
    @classmethod
    def _non_empty(cls, v: dict[str, Any], info) -> dict[str, Any]:
        if not v:
            raise ValueError("dict_kwargs must not be empty")
        visu_type = info.data.get("visu_type")
        if visu_type and visu_type != "histogram" and "x" not in v:
            raise ValueError("dict_kwargs must include 'x' for non-histogram plots")
        return v


class SuggestFiguresResponse(BaseModel):
    """Returned by `/ai/suggest-figures` (data-driven flow)."""

    suggestions: list[PlotSuggestion]


ComponentType = Literal[
    "figure",
    "card",
    "interactive",
    "table",
    "image",
    "multiqc",
    "map",
]


class ComponentFromPromptResponse(BaseModel):
    """Returned by `/ai/component-from-prompt` (prompt → single typed component).

    The LLM emits YAML (verbatim CLI grammar); we validate it through
    `DashboardDataLite.from_yaml(...)` and hand the React side both the
    raw YAML (for "show your work") and the validated dict the builder
    store consumes.
    """

    component_type: ComponentType
    yaml: str
    parsed: dict[str, Any]
    explanation: str = ""
    validation_attempts: int = 1


class ExecutionStep(BaseModel):
    """One iteration of the analyze loop.

    Fields are deliberately permissive — the executor surfaces failures as
    steps with status="error" rather than raising, so the trace is always
    renderable end-to-end.
    """

    thought: str = ""
    code: str = ""
    output: str = ""
    status: Literal["success", "error", "warning"] = "success"


class FilterAction(BaseModel):
    """Set the value of an interactive component on the dashboard."""

    component_id: str
    value: Any
    reason: str = ""


class FigureMutation(BaseModel):
    """Patch the dict_kwargs of an existing figure component.

    The React side merges `dict_kwargs_patch` into the figure's current
    kwargs; keys mapped to `None` are removed.
    """

    component_id: str
    dict_kwargs_patch: dict[str, Any]
    reason: str = ""


class ThresholdSpec(BaseModel):
    """A percentile-style threshold the server resolves to a concrete value.

    "top 3% of X" → `{column: "X", kind: "quantile", q: 0.97, op: ">="}`.
    The quantile is computed server-side on the delta table (respecting the
    currently-active filters), keeping the filter-expression allowlist free
    of quantile/rank primitives.
    """

    column: str
    kind: Literal["quantile"] = "quantile"
    q: float = Field(ge=0.0, le=1.0)
    op: Literal[">=", ">", "<=", "<"] = ">="


class FilterProposal(BaseModel):
    """One LLM-proposed dashboard filter, before server-side resolution.

    - `set_widget`: set an existing interactive component's value
      (component_id + value required).
    - `filter_expr`: a Polars filter expression string, validated through
      `validate_filter_expr` before it ever reaches a client.
    - `threshold`: a percentile request resolved server-side to a concrete
      `filter_expr` (see ThresholdSpec).
    """

    kind: Literal["set_widget", "filter_expr", "threshold"]
    component_id: str | None = None
    value: Any = None
    filter_expr: str | None = None
    threshold: ThresholdSpec | None = None
    reason: str = ""


class ResolvedFilter(BaseModel):
    """A proposal after validation/resolution — safe for the client to apply.

    `set_widget` entries target an existing interactive component;
    `filter_expr` entries are injected client-side as an
    `InteractiveFilter{source: 'ai_prompt'}` carrying only the expression.
    """

    kind: Literal["set_widget", "filter_expr"]
    component_id: str | None = None
    value: Any = None
    filter_expr: str | None = None
    dc_id: str | None = None
    description: str = ""


class DashboardActions(BaseModel):
    """All side-effects the analyze flow may apply to the dashboard."""

    filters: list[FilterAction] = Field(default_factory=list)
    figure_mutations: list[FigureMutation] = Field(default_factory=list)
    filter_proposals: list[FilterProposal] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Returned by `/ai/analyze` (prompt-driven analysis)."""

    answer: str
    steps: list[ExecutionStep]
    actions: DashboardActions = Field(default_factory=DashboardActions)
    resolved_filters: list[ResolvedFilter] = Field(default_factory=list)


# ---------- Request bodies ----------


class SuggestFiguresRequest(BaseModel):
    data_collection_id: str
    n: int = Field(default=4, ge=1, le=8)


class ComponentFromPromptRequest(BaseModel):
    """Body for `/ai/component-from-prompt`.

    `current` is set in the "modify existing component" flow — when the
    user clicks the AI fill button on an already-loaded component, we
    pass its current StoredMetadata so the LLM produces a revision
    rather than a fresh component.
    """

    data_collection_id: str
    prompt: str = Field(min_length=1, max_length=2000)
    component_type: ComponentType
    current: dict[str, Any] | None = None


class AnalyzeRequest(BaseModel):
    dashboard_id: str
    prompt: str = Field(min_length=1, max_length=2000)
    selected_component_id: str | None = None
    # Currently-active InteractiveFilter dicts from the client — threshold
    # resolution computes quantiles on the *filtered* data the user sees.
    filters: list[dict[str, Any]] = Field(default_factory=list)


class ResolveFiltersRequest(BaseModel):
    """Body for `/ai/resolve-filters` (direct NL → filters, no ReAct loop)."""

    dashboard_id: str
    prompt: str = Field(min_length=1, max_length=2000)
    filters: list[dict[str, Any]] = Field(default_factory=list)


class ResolveFiltersResponse(BaseModel):
    applied: list[ResolvedFilter] = Field(default_factory=list)
    explanation: str = ""
    warnings: list[str] = Field(default_factory=list)


# ---------- Section summaries ----------


class SummaryComponent(BaseModel):
    """One rendered component as the client sees it, digest included.

    `digest` is the visible payload: a card's computed value, a figure's
    trimmed Plotly `{data, layout}`, a table's first rows. The server trims
    it again (defense in depth) before it reaches a prompt.
    """

    id: str
    type: str
    title: str = ""
    digest: Any = None


class SummarizeSectionRequest(BaseModel):
    """Body for `/ai/summarize-section` — client-supplied context.

    The client sends exactly what the user sees (filters applied); the
    server never re-renders. `section` is None for un-sectioned components
    ("the whole grid" on section-less dashboards).
    """

    dashboard_id: str
    section: str | None = None
    filters: list[dict[str, Any]] = Field(default_factory=list)
    components: list[SummaryComponent] = Field(default_factory=list, max_length=40)
    force: bool = False


class SummarizeSectionResponse(BaseModel):
    summary_md: str
    generated_at: str
    model: str
    context_hash: str
    cached: bool = False


class SummaryEntry(BaseModel):
    """One cached summary as returned by `GET /ai/summaries/{dashboard_id}`."""

    section: str | None = None
    summary_md: str
    generated_at: str
    model: str
    context_hash: str


class SummariesResponse(BaseModel):
    summaries: list[SummaryEntry] = Field(default_factory=list)


# ---------- Streaming envelope ----------

StreamEventType = Literal[
    "status",
    "step",
    "answer",
    "actions",
    "result",
    "error",
    "done",
]


class StreamEvent(BaseModel):
    """Wire format for a single SSE-style chunk over the streaming POST body."""

    type: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
