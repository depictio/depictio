"""Pydantic schemas for the AI endpoints.

Mirrors the prototype at `dev/litellm-prototype/schemas.py` and extends it
with the action types the analyze endpoint can return so the React side can
mutate filters and existing figures based on an LLM-generated plan.
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


class DashboardActions(BaseModel):
    """All side-effects the analyze flow may apply to the dashboard."""

    filters: list[FilterAction] = Field(default_factory=list)
    figure_mutations: list[FigureMutation] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Returned by `/ai/analyze` (prompt-driven analysis)."""

    answer: str
    steps: list[ExecutionStep]
    actions: DashboardActions = Field(default_factory=DashboardActions)


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
