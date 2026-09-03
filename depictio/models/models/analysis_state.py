"""The analysis state of a dashboard, as one serialisable object.

Today that state is scattered across the viewer: the active filters live in
``App.tsx``'s React state, the selection groups and the global colour-by in
``localStorage`` (``depictio:selection-groups:<family>``), the funnel stage
order in the funnel modal, and the split constraints are derived on the fly.
Nothing on the server can read any of it.

``AnalysisState`` is the contract that unifies them. The viewer builds it
(``packages/depictio-react-core/src/analysisState.ts``) and hands it to the
server whenever a feature needs the whole picture — notebook export and
component embeds first; the share link and version snapshots are the next
consumers. It is versioned: bump ``ANALYSIS_STATE_VERSION`` and add a
migration path when the shape changes, as the groups payload already does.

The committed JSON schema (``analysis_state.schema.json``) is the reviewable
artefact of a contract change: the TypeScript mirror pins against it, and a
test fails when the model drifts from the snapshot.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ANALYSIS_STATE_VERSION = 1


class AnalysisFilterMetadata(BaseModel):
    """The ``metadata`` block the viewer attaches to a filter.

    ``dc_id`` is what cross-DC link resolution keys on server-side: a filter
    without it is treated as global (applied wherever its column exists).
    """

    model_config = ConfigDict(extra="allow")

    dc_id: str | None = None
    column_name: str | None = None
    interactive_component_type: str | None = None
    selection_column: str | None = None
    filter_expr: str | None = None


class AnalysisFilter(BaseModel):
    """One entry of the viewer's ``InteractiveFilter[]`` (``api.ts``).

    Group projections travel here too, exactly as the render endpoints see
    them: ``source == "group_filter"`` and an index prefixed with
    ``__depictio_group__:``. Keeping them in the same list means the server
    never has to re-implement the viewer's ``groupsToFilters``.
    """

    model_config = ConfigDict(extra="allow")

    index: str
    value: Any = None
    column_name: str | None = None
    interactive_component_type: str | None = None
    source: str | None = None
    filter_expr: str | None = None
    metadata: AnalysisFilterMetadata | None = None


class AnalysisGroup(BaseModel):
    """A saved selection group (``SelectionGroup`` in ``selectionGroups.ts``)."""

    id: str
    name: str
    color: str
    dc_id: str | None = None
    column_name: str
    values: list[str] = Field(default_factory=list)
    created_at: int = 0
    filter_active: bool = False


class ColorBy(BaseModel):
    """The dashboard-global "Colour by" override."""

    kind: Literal["none", "groups", "column"] = "none"
    column_name: str | None = None


class FunnelState(BaseModel):
    """Funnel filtering: whether it is on, and the user's stage order.

    ``stage_order`` lists component indexes. An empty list means "the order
    the filters appear in ``AnalysisState.filters``", which is also what the
    funnel modal shows before the user reorders anything.
    """

    enabled: bool = True
    stage_order: list[str] = Field(default_factory=list)


class SplitPanel(BaseModel):
    """One cell of a split view (``PanelSpec`` in ``splitPanels.ts``).

    ``constraints`` are ordinary filters appended to the dashboard's own for
    that cell alone, so a panel serialises straight to a ``.filter(...)``.
    """

    name: str
    color: str | None = None
    constraints: list[AnalysisFilter] = Field(default_factory=list)


class AnalysisContext(BaseModel):
    """Where the state was captured."""

    dashboard_id: str
    family_id: str | None = None
    theme: Literal["light", "dark"] = "light"


class AnalysisState(BaseModel):
    """Everything the viewer knows about *how* the user is looking at the data."""

    version: Literal[1] = ANALYSIS_STATE_VERSION
    filters: list[AnalysisFilter] = Field(default_factory=list)
    groups: list[AnalysisGroup] = Field(default_factory=list)
    color_by: ColorBy = Field(default_factory=ColorBy)
    display_mode: Literal["color", "facet"] = "color"
    show_other: bool = True
    show_overall: bool = True
    compare_in_cards: bool = False
    funnel: FunnelState = Field(default_factory=FunnelState)
    split_panels: list[SplitPanel] = Field(default_factory=list)
    context: AnalysisContext

    def filters_as_payload(self) -> list[dict[str, Any]]:
        """The filters in the plain-dict shape the render endpoints consume."""
        return [f.model_dump(mode="json", exclude_none=True) for f in self.filters]


# ---------------------------------------------------------------------------
# Notebook export
# ---------------------------------------------------------------------------

NotebookFormat = Literal["marimo", "ipynb", "quarto"]

# How a component reaches the notebook: as explicit Polars/Plotly code, as a
# cell that re-renders it through the Depictio API with the exported state, or
# not at all (with a reason written for the reader).
NotebookInclusion = Literal["code", "api", "omitted"]


class NotebookExportRequest(BaseModel):
    state: AnalysisState
    format: NotebookFormat = "marimo"


class NotebookPreflightComponent(BaseModel):
    index: str
    title: str | None = None
    component_type: str
    kind: str | None = None
    status: NotebookInclusion
    reason: str | None = None
    name: str | None = None
    tab: str | None = None
    section: str | None = None


class NotebookPreflightDC(BaseModel):
    dc_id: str
    tag: str | None = None
    rows: int | None = None


class NotebookPreflightStage(BaseModel):
    index: str | None = None
    label: str | None = None
    rows_by_dc: dict[str, int | None] = Field(default_factory=dict)


class NotebookPreflight(BaseModel):
    """What an export will contain, before anything is generated."""

    components: list[NotebookPreflightComponent] = Field(default_factory=list)
    dcs: list[NotebookPreflightDC] = Field(default_factory=list)
    stages: list[NotebookPreflightStage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ipynb_available: bool = False
    render_available: bool = False
    counts: dict[str, int] = Field(default_factory=dict)


class NotebookRenderStatus(BaseModel):
    """A render job: where it is, and what it left behind when it is done.

    The job is the notebook being executed on a worker, which takes minutes —
    the client starts it, then asks this until it is ``ready`` or ``error``.
    """

    job_id: str
    status: Literal["queued", "running", "ready", "error"]
    phase: str | None = None
    filename: str | None = None
    size: int | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Component embed / figure extraction
# ---------------------------------------------------------------------------


class ComponentEmbedRequest(BaseModel):
    state: AnalysisState | None = None
    theme: Literal["light", "dark"] = "light"


class ComponentFigureResponse(BaseModel):
    """A component as a Plotly figure, or the job that will produce it."""

    status: Literal["ready", "pending", "unsupported", "error"]
    figure: dict[str, Any] | None = None
    job_id: str | None = None
    reason: str | None = None
    source: Literal["server", "extracted"] | None = None
