"""Comment threads pinned to a dashboard component, optionally carrying an annotation.

A thread hangs off an :class:`Anchor`: the tab, the component (or the tab
itself), and the view the author was looking at (filters and selection).
Clicking a thread restores that view on today's data.

Threads are internal to a project's editors and owners. An annotation is a
thread that also carries a shape drawn in data coordinates (a range, a
reference line, marked points, an arrow note). Its ``published`` switch lets
viewers see the shape and its label, never the discussion.

What an anchor cannot do yet is bring back the *exact* state: a later save can
change the component and a re-ingest can change its data. The anchor records
cheap fingerprints of both (a hash of the component's definition, the latest
aggregation hash of every data collection it reads) so the viewer can say
"changed since this comment" instead of silently showing something else.
``version_id`` and ``pins`` are reserved for dashboard and dataset versioning;
they stay empty until that lands.

Agents are first-class authors: a thread written by an agent is always on
behalf of a user, starts as ``proposed`` and needs a human review before it
counts, and before its annotation can be published. The text of a comment is
data, never an instruction for an agent.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_BODY_CHARS = 4000
MAX_LABEL_CHARS = 120
MAX_REASON_CHARS = 1000
MAX_POINT_IDS = 5000
MAX_REGION_VERTICES = 1000
MAX_COMMENTS_PER_THREAD = 500
MAX_EVIDENCE_ITEMS = 20
MAX_VARIANT_CHARS = 200

# Mantine palette names: annotations pick a theme colour, never a raw value, so
# they follow light and dark mode like the rest of the viewer.
AnnotationColor = Literal[
    "blue",
    "cyan",
    "teal",
    "green",
    "lime",
    "yellow",
    "orange",
    "red",
    "pink",
    "grape",
    "violet",
    "indigo",
    "gray",
]

ThreadStatus = Literal["open", "resolved", "proposed", "rejected"]
AnnotationKind = Literal["range", "line", "points", "note"]

# Keys of a stored component that do not change what a comment on it is about.
_FINGERPRINT_IGNORED_KEYS = frozenset({"layout", "last_updated", "parent_index"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def component_fingerprint(component: dict[str, Any] | None) -> str | None:
    """Stable hash of a component's stored definition.

    Layout coordinates are left out: moving or resizing a tile does not change
    what a comment on it is about.
    """
    if not component:
        return None
    relevant = {k: v for k, v in component.items() if k not in _FINGERPRINT_IGNORED_KEYS}
    digest = hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode())
    return digest.hexdigest()[:16]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewState(_Strict):
    """What the author saw: the filters applied and the selection made.

    Kept as the viewer's own payloads (the same shapes as the ``#filters=``
    share link) rather than re-modelled here, so the viewer can restore them
    without a translation layer that would drift.
    """

    filters: list[dict[str, Any]] = Field(default_factory=list)
    selection: dict[str, Any] | None = None


class Anchor(_Strict):
    """Where a thread points."""

    dashboard_id: str
    """The tab the component lives on (a main dashboard or a child tab)."""
    component_index: str | None = None
    """``None`` pins the thread to the tab itself rather than one component."""
    component_title: str | None = None
    """Shown when the component is gone, and used to re-attach after an import."""
    view_state: ViewState | None = None

    # Fingerprints, filled in by the API at creation time.
    component_hash: str | None = None
    data_hashes: dict[str, str] = Field(default_factory=dict)

    # Reserved for dashboard / dataset versioning. Always empty for now.
    version_id: str | None = None
    pins: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Annotation geometry, in data coordinates so it survives resizing and redraws
# ---------------------------------------------------------------------------
AxisValue = float | int | str
"""A numeric value, a category, or a date string, as Plotly takes it."""


class XRange(_Strict):
    """A band across the x axis, drawn behind the data."""

    kind: Literal["x_range"] = "x_range"
    x0: AxisValue
    x1: AxisValue


class YRange(_Strict):
    """A band across the y axis, drawn behind the data."""

    kind: Literal["y_range"] = "y_range"
    y0: float
    y1: float


class RefLine(_Strict):
    """A dashed reference line, drawn in front of the data."""

    kind: Literal["ref_line"] = "ref_line"
    axis: Literal["x", "y"]
    value: AxisValue


class PointCoord(_Strict):
    x: AxisValue
    y: AxisValue
    trace: int | None = None
    """Index of the trace the point belongs to, when the figure has several."""
    index: int | None = Field(default=None, ge=0)
    """Index of the point in its trace's data, kept for traces drawn away from
    their data x/y (box, violin, bar) to find the drawn mark again."""


class BoxRegion(_Strict):
    """The rectangle a box selection covered."""

    shape: Literal["box"] = "box"
    x0: AxisValue
    x1: AxisValue
    y0: AxisValue
    y1: AxisValue


class LassoRegion(_Strict):
    """The polygon a lasso selection traced, one vertex per ``x``/``y`` pair."""

    shape: Literal["lasso"] = "lasso"
    x: list[AxisValue] = Field(min_length=3, max_length=MAX_REGION_VERTICES)
    y: list[AxisValue] = Field(min_length=3, max_length=MAX_REGION_VERTICES)

    @model_validator(mode="after")
    def _same_length(self) -> LassoRegion:
        if len(self.x) != len(self.y):
            raise ValueError("lasso x and y need the same number of vertices")
        return self


SelectionRegion = Annotated[BoxRegion | LassoRegion, Field(discriminator="shape")]


class MarkedPoints(_Strict):
    """Points, bars or table rows to circle or outline.

    Rows are identified by the component's selection column when it has one
    (``column`` + ``ids``), which survives re-sorting and re-ingest. Charts
    without one (bars, histograms) fall back to plain coordinates.
    ``region`` keeps the area the selection gesture covered, drawn as a
    shaded background behind the points.
    """

    kind: Literal["points"] = "points"
    column: str | None = None
    ids: list[str | int | float] = Field(default_factory=list, max_length=MAX_POINT_IDS)
    coords: list[PointCoord] = Field(default_factory=list, max_length=MAX_POINT_IDS)
    region: SelectionRegion | None = None

    @model_validator(mode="after")
    def _something_marked(self) -> MarkedPoints:
        if not self.ids and not self.coords:
            raise ValueError("marked points need ids or coords")
        if self.ids and not self.column:
            raise ValueError("ids need the column they come from")
        return self


class ArrowNote(_Strict):
    """A numbered note with an arrow pointing at a data point.

    ``x``/``y`` are the arrow head in data coordinates; ``ax``/``ay`` offset
    the label from it in pixels, so the label keeps its place on resize.
    """

    kind: Literal["arrow_note"] = "arrow_note"
    x: AxisValue
    y: AxisValue
    ax: float = -40
    ay: float = -40


Geometry = Annotated[
    XRange | YRange | RefLine | MarkedPoints | ArrowNote, Field(discriminator="kind")
]

_GEOMETRY_KINDS: dict[str, frozenset[str]] = {
    "range": frozenset({"x_range", "y_range"}),
    "line": frozenset({"ref_line"}),
    "points": frozenset({"points"}),
    "note": frozenset({"arrow_note"}),
}


class AnnotationStyle(_Strict):
    opacity: float | None = Field(default=None, ge=0, le=1)
    dash: Literal["solid", "dash", "dot"] | None = None
    width: float | None = Field(default=None, gt=0, le=10)
    fill_opacity: float | None = Field(default=None, ge=0, le=1)
    """Opacity of a marked-points region; 0 draws no background."""


class Annotation(_Strict):
    """The shape a thread carries."""

    kind: AnnotationKind
    geometry: Geometry
    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    color: AnnotationColor = "yellow"
    style: AnnotationStyle = Field(default_factory=AnnotationStyle)
    published: bool = False
    """Visible to viewers of the dashboard (shape and label only)."""
    variant: str | None = Field(default=None, min_length=1, max_length=MAX_VARIANT_CHARS)
    """The view of the component the shape was drawn on, for components showing
    one of several plots (e.g. a MultiQC dataset). A shape with a variant is
    drawn only on that view; ``None`` draws it on every view."""

    @model_validator(mode="after")
    def _geometry_matches_kind(self) -> Annotation:
        if self.geometry.kind not in _GEOMETRY_KINDS[self.kind]:
            raise ValueError(
                f"a {self.kind!r} annotation cannot use a {self.geometry.kind!r} geometry"
            )
        return self


class AnnotationPatch(_Strict):
    """Partial update of a thread's annotation."""

    geometry: Geometry | None = None
    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_CHARS)
    color: AnnotationColor | None = None
    style: AnnotationStyle | None = None
    published: bool | None = None


# ---------------------------------------------------------------------------
# Authors: humans, and agents acting on behalf of one
# ---------------------------------------------------------------------------
class AgentInfo(_Strict):
    name: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    run_id: str | None = Field(default=None, max_length=120)
    on_behalf_of: str | None = None
    """User id of the person who launched the agent. Set by the API."""


class Author(_Strict):
    kind: Literal["human", "agent"] = "human"
    user_id: str
    email: str | None = None
    agent: AgentInfo | None = None

    @model_validator(mode="after")
    def _agent_iff_agent_kind(self) -> Author:
        if (self.kind == "agent") != (self.agent is not None):
            raise ValueError("agent details are required for, and only for, an agent author")
        return self


class Evidence(_Strict):
    """A structured claim an agent backs its comment with, for one-click checks."""

    claim: str = Field(min_length=1, max_length=MAX_BODY_CHARS)
    query: str | None = Field(default=None, max_length=MAX_BODY_CHARS)
    values: dict[str, Any] | list[Any] | None = None
    view_state: ViewState | None = None


class Review(_Strict):
    decision: Literal["accepted", "rejected"]
    by: str
    at: datetime
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)


# ---------------------------------------------------------------------------
# Stored documents
# ---------------------------------------------------------------------------
class Comment(_Strict):
    id: str
    author: Author
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    deleted: bool = False


class CommentThread(BaseModel):
    id: str
    project_id: str
    parent_dashboard_id: str
    """The main tab of the dashboard family, for tab-wide listing and cascade deletes."""
    anchor: Anchor
    annotation: Annotation | None = None
    number: int | None = None
    """Per-tab number of the annotation, shown as a numbered dot in the chart and drawer."""
    status: ThreadStatus = "open"
    review: Review | None = None
    evidence: list[Evidence] | None = None
    dedupe_key: str | None = None
    run_id: str | None = None
    created_by: Author
    created_at: datetime
    updated_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    human_edited: bool = False
    """A human changed an agent's annotation: the "modified" review outcome, kept for evaluation."""
    comments: list[Comment] = Field(default_factory=list)

    @property
    def is_agent_proposal(self) -> bool:
        return self.created_by.kind == "agent" and (
            self.review is None or self.review.decision != "accepted"
        )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
def _not_blank(v: str | None) -> str | None:
    if v is not None and not v.strip():
        raise ValueError("comment body must not be blank")
    return v


class ThreadCreate(_Strict):
    anchor: Anchor
    body: str | None = Field(default=None, max_length=MAX_BODY_CHARS)
    """First comment. Optional when the thread carries an annotation."""
    annotation: Annotation | None = None
    evidence: list[Evidence] | None = Field(default=None, max_length=MAX_EVIDENCE_ITEMS)
    dedupe_key: str | None = Field(default=None, max_length=200)
    agent: AgentInfo | None = None
    """Set when an agent writes the thread on behalf of the calling user."""

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, v: str | None) -> str | None:
        return _not_blank(v)

    @model_validator(mode="after")
    def _has_content(self) -> ThreadCreate:
        if self.body is None and self.annotation is None:
            raise ValueError("a thread needs a comment or an annotation")
        if self.agent is not None and not self.agent.run_id:
            raise ValueError("an agent thread needs agent.run_id")
        if self.agent is not None and self.annotation is not None and self.annotation.published:
            raise ValueError("an agent annotation cannot be published before a human accepts it")
        return self


class CommentCreate(_Strict):
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("comment body must not be blank")
        return v


class CommentUpdate(CommentCreate):
    pass


class ThreadUpdate(_Strict):
    status: Literal["open", "resolved"] | None = None
    annotation: AnnotationPatch | None = None


class ThreadReview(_Strict):
    decision: Literal["accepted", "rejected"]
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
class Staleness(BaseModel):
    """How an anchor compares with the dashboard as it is now."""

    component_missing: bool = False
    component_changed: bool = False
    data_changed: bool = False


class ThreadOut(CommentThread):
    staleness: Staleness = Field(default_factory=Staleness)


class PublishedAnnotation(BaseModel):
    """What a viewer gets of a published annotation: the shape and its label."""

    thread_id: str
    dashboard_id: str
    component_index: str | None
    number: int | None
    kind: AnnotationKind
    geometry: Geometry
    label: str
    color: AnnotationColor
    style: AnnotationStyle
    variant: str | None = None


class CommentAccess(BaseModel):
    can_comment: bool
