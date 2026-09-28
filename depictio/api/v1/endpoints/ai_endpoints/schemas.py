"""Pydantic schemas for the AI endpoints.

Ported from the `claude/ai-compatible-depictio-gR9q7` exploration branch
(itself descended from the `dev/litellm-prototype` prototype, PR #879) and
extended with the action types the analyze endpoint can return so the React
side can mutate filters and existing figures based on an LLM-generated plan.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from depictio.models.components.constants import VISU_TYPES

# Derived from the one visu_type list the lite model validates against, so a
# suggestion the LLM is allowed to make is always one the figure accepts.
VisuType = Literal[*VISU_TYPES]


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
    """Returned by `/ai/suggest-figures` (data-driven flow).

    Deprecated: the viewer calls `/ai/suggest-components` instead, which
    proposes any component type; this stays for older clients.
    """

    suggestions: list[PlotSuggestion]


# Every component type the builder offers. The prompt sheets, the YAML
# examples and the request validator are keyed on this Literal.
ComponentType = Literal[
    "figure",
    "card",
    "interactive",
    "table",
    "text",
    "image",
    "multiqc",
    "map",
    "advanced_viz",
]


class RoutedCollection(BaseModel):
    """A data collection the router considered, resolved to its ids.

    The router speaks in tags (that is what the inventory shows it); the
    client needs ids to load the collection, so both are returned.
    """

    data_collection_id: str
    data_collection_tag: str
    workflow_id: str
    workflow_tag: str | None = None


RoutingSource = Literal["user", "single", "auto"]
"""Who decided the component type and data collection of a request.

``user``: both were pinned in the request, nothing was routed.
``single``: the type was pinned and exactly one collection fitted it, so
the collection was picked without an LLM call.
``auto``: the router LLM call chose the type and/or the collection.
"""


class RoutingInfo(BaseModel):
    """How the server settled the component type and data collection."""

    source: RoutingSource
    reason: str | None = None
    # Other plausible collections the router named, resolved against the
    # inventory. Empty when none were named (and always for "user").
    alternatives: list[RoutedCollection] = Field(default_factory=list)


SuggestionOrigin = Literal["llm", "ranked"]
"""Where a `/ai/suggest-components` item came from.

``llm``: proposed by the model and validated server-side.
``ranked``: built deterministically from the data (no LLM), for the types
the model never handles (advanced_viz, table).
"""


class ComponentSuggestion(BaseModel):
    """One proposed component for the dashboard, ready to land in the builder.

    `component` is the validated lite component (the output of
    `component_yaml.validate_single`): it carries component_type,
    workflow_tag, data_collection_tag, title and the type's own fields.
    `data_collection_id` / `workflow_id` resolve the tags for the client
    (None for text). `code` is the Plotly Express rendering of a figure,
    display-only.
    """

    component_type: ComponentType
    data_collection_id: str | None = None
    data_collection_tag: str | None = None
    workflow_id: str | None = None
    title: str
    rationale: str
    component: dict[str, Any]
    code: str | None = None
    origin: SuggestionOrigin


class SuggestComponentsResponse(BaseModel):
    """Returned by `/ai/suggest-components`.

    `warnings` explains a degraded answer, e.g. the LLM call failed and only
    the ranked (deterministic) suggestions are shown.
    """

    suggestions: list[ComponentSuggestion]
    warnings: list[str] = Field(default_factory=list)


class ComponentFromPromptResponse(BaseModel):
    """Returned by `/ai/component-from-prompt` (prompt → single typed component).

    The LLM emits YAML (verbatim CLI grammar); we validate it through
    `DashboardDataLite.from_yaml(...)` and hand the React side both the
    raw YAML (for "show your work") and the validated dict the builder
    store consumes.

    `component_type` is the type actually generated, which is the routed
    one when the request left it open. `data_collection_id` /
    `workflow_id` name the collection the component was generated
    against (None for `text`), and `routing` says who chose them.
    """

    component_type: ComponentType
    yaml: str
    parsed: dict[str, Any]
    explanation: str = ""
    validation_attempts: int = 1
    data_collection_id: str | None = None
    workflow_id: str | None = None
    routing: RoutingInfo | None = None


class ExecutionStep(BaseModel):
    """One iteration of the analyze loop.

    Fields are deliberately permissive — the executor surfaces failures as
    steps with status="error" rather than raising, so the trace is always
    renderable end-to-end.

    `rows_in`/`rows_out` are what make a step auditable. A filter that
    silently matched every row and one that silently matched none produce
    identical prose; they produce very different cardinalities.
    """

    thought: str = ""
    code: str = ""
    output: str = ""
    status: Literal["success", "error", "warning"] = "success"
    dc_tag: str = ""
    rows_in: int | None = None
    rows_out: int | None = None
    seconds: float = 0.0


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
    # Human handle for set_widget targets (the widget's column) so clients
    # can show "body_mass_g → [4450, 6300]" instead of a raw component id.
    label: str | None = None


class DashboardActions(BaseModel):
    """All side-effects the analyze flow may apply to the dashboard."""

    filters: list[FilterAction] = Field(default_factory=list)
    figure_mutations: list[FigureMutation] = Field(default_factory=list)
    filter_proposals: list[FilterProposal] = Field(default_factory=list)


AnalyzeMode = Literal["mutate", "analyze"]
"""Which half of the assistant a `/ai/analyze` request is asking for.

``mutate`` is the original conversational flow: answer a question *and*
propose dashboard actions the user can Apply. ``analyze`` is read-only —
the model may execute code and narrate, but `actions` is stripped
server-side and no Apply affordance is ever rendered. Keeping the two
exclusive is what lets the UI decide how to render a reply.
"""


class AnalysisResult(BaseModel):
    """Returned by `/ai/analyze` (prompt-driven analysis)."""

    answer: str
    steps: list[ExecutionStep]
    mode: AnalyzeMode = "mutate"
    actions: DashboardActions = Field(default_factory=DashboardActions)
    resolved_filters: list[ResolvedFilter] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------- Analysis reports (read-only mode's artifact) ----------


class Finding(BaseModel):
    """One claim the analysis makes, tied to the steps that ground it.

    `evidence_step_ids` is required and non-empty by validation, not by
    convention: a claim with no executed evidence behind it is exactly the
    failure mode this artifact exists to prevent — asserting a conclusion
    from a handful of sample rows. Claims that fail this check are dropped
    and the drop is recorded in the report's warnings, never rendered with
    a caveat.
    """

    claim: str = Field(min_length=1)
    evidence_step_ids: list[int] = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("evidence_step_ids")
    @classmethod
    def _non_empty_evidence(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("a finding must cite at least one executed step")
        return v


class BudgetSpent(BaseModel):
    steps: int = 0
    tokens: int = 0
    seconds: float = 0.0


class AnalysisReport(BaseModel):
    """The persisted artifact of one read-only analysis run.

    Stored in the `ai_analyses` collection — a derived document, never
    written into the dashboard itself, same policy as `ai_summaries`.
    """

    id: str
    dashboard_id: str
    created_at: str
    model: str
    prompt: str
    status: Literal["running", "complete", "failed", "cancelled"] = "running"
    findings: list[Finding] = Field(default_factory=list)
    steps: list[ExecutionStep] = Field(default_factory=list)
    narrative_md: str = ""
    budget_spent: BudgetSpent = Field(default_factory=BudgetSpent)
    warnings: list[str] = Field(default_factory=list)


# ---------- Whole-dashboard generation ----------


class GenerateDashboardRequest(BaseModel):
    """Body for `/ai/generate-dashboard` (prompt -> whole dashboard draft).

    `prompt` may be empty: the planner then builds the most useful overview
    of the project it can. `data_collection_ids` narrows the collections the
    planner sees (every table collection of the project when empty); each
    id must belong to the project. `title` pins the dashboard title, and a
    title collision is then a 409 unless `overwrite`; left None, the planner
    chooses one and a collision gets a suffix instead.
    """

    project_id: str
    prompt: str = Field(default="", max_length=2000)
    title: str | None = None
    data_collection_ids: list[str] = Field(default_factory=list)
    overwrite: bool = False


GeneratedComponentStatus = Literal["ok", "repaired", "dropped"]
"""Fate of one planned component.

``ok``: validated first time. ``repaired``: validated after at least one
repair round-trip. ``dropped``: left out of the draft (repairs exhausted,
or the token / wall-clock budget ran out before it was filled).
"""


class GeneratedComponentEvent(BaseModel):
    """Payload of one `component` stream event, emitted once per planned component."""

    tag: str
    section: str
    component_type: ComponentType
    status: GeneratedComponentStatus
    attempts: int = 1
    error: str | None = None


class GeneratedDashboardEvent(BaseModel):
    """Payload of the terminal `dashboard` stream event.

    `yaml` is the persisted draft (show-your-work, like the single component
    flow); `dropped` lists the tags that did not make it so the client can
    say what is missing without diffing the plan.
    """

    dashboard_id: str
    title: str
    project_id: str
    yaml: str
    warnings: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)


class PromoteResponse(BaseModel):
    """Returned by `/ai/generated-dashboards/{dashboard_id}/promote`."""

    dashboard_id: str
    status: Literal["promoted"] = "promoted"


# ---------- Request bodies ----------


class SuggestFiguresRequest(BaseModel):
    """Body for the deprecated `/ai/suggest-figures`."""

    data_collection_id: str
    n: int = Field(default=4, ge=1, le=8)


class SuggestComponentsRequest(BaseModel):
    """Body for `/ai/suggest-components` ("what would you add to this dashboard?").

    Everything is derived from the dashboard: its project inventory says
    which collections exist and what they can back, its components say
    what is already shown. `component_type` and `data_collection_id` are
    optional pins (None = let the server mix types / pick collections).
    """

    dashboard_id: str
    component_type: ComponentType | None = None
    data_collection_id: str | None = None
    n: int = Field(default=4, ge=1, le=8)


class ComponentFromPromptRequest(BaseModel):
    """Body for `/ai/component-from-prompt`.

    The prompt comes first; `component_type` and `data_collection_id` are
    optional pins. Whatever is left open is routed server-side from the
    dashboard's project inventory before generation, which is why
    `dashboard_id` is required as soon as either one is None (a `text`
    request with a pinned type is the exception: it has no data source,
    and only uses `dashboard_id` to describe the tiles it will sit next
    to). A non-text type with a data collection is the fully pinned case
    and generates exactly as before.

    `current` is set in the "modify existing component" flow — when the
    user clicks the AI fill button on an already-loaded component, we
    pass its current StoredMetadata so the LLM produces a revision
    rather than a fresh component.
    """

    data_collection_id: str | None = None
    dashboard_id: str | None = None
    prompt: str = Field(min_length=1, max_length=2000)
    component_type: ComponentType | None = None
    current: dict[str, Any] | None = None

    @property
    def needs_routing(self) -> bool:
        """True when the server has to pick the type and/or the collection."""
        return self.component_type is None or (
            self.data_collection_id is None and self.component_type != "text"
        )

    @model_validator(mode="after")
    def _dashboard_required_for_routing(self) -> "ComponentFromPromptRequest":
        if self.needs_routing and not self.dashboard_id:
            raise ValueError(
                "dashboard_id is required when component_type or data_collection_id is left "
                "for the server to choose (pin both to skip routing; only component_type='text' "
                "needs no data_collection_id)"
            )
        return self


class AnalyzeRequest(BaseModel):
    dashboard_id: str
    prompt: str = Field(min_length=1, max_length=2000)
    selected_component_id: str | None = None
    # Currently-active InteractiveFilter dicts from the client — threshold
    # resolution computes quantiles on the *filtered* data the user sees.
    filters: list[dict[str, Any]] = Field(default_factory=list)
    # Defaults to "mutate" so existing clients keep the behaviour they
    # were written against; the read-only surface opts in explicitly.
    mode: AnalyzeMode = "mutate"


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
    # Read-only analysis additions: `plan` once after the first turn (the
    # model's stated intent, shown before the minutes of waiting), and
    # `budget` each turn ({steps_used, tokens_used, seconds}) so the
    # countdown the model sees is also visible to the user.
    "plan",
    "budget",
    "report",
    # Whole-dashboard generation: `component` once per planned component
    # (GeneratedComponentEvent) and `dashboard` as the terminal payload
    # (GeneratedDashboardEvent), before `done`.
    "component",
    "dashboard",
    "error",
    "done",
]


class StreamEvent(BaseModel):
    """Wire format for a single SSE-style chunk over the streaming POST body."""

    type: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
