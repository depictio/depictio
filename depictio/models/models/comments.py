"""Comment threads and annotations pinned to a dashboard component.

Both hang off an :class:`Anchor`: the tab, the component, and the view the
author was looking at (filters and selection). Clicking a thread or an
annotation restores that view on today's data.

What an anchor cannot do yet is bring back the *exact* state: a later save can
change the component and a re-ingest can change its data. The anchor records
cheap fingerprints of both (a hash of the component's definition, the latest
aggregation hash of every data collection it reads) so the viewer can say
"changed since this comment" instead of silently showing something else.
``version_id`` and ``pins`` are reserved for dashboard and dataset versioning;
they stay empty until that lands, and an anchor without them simply cannot
travel back in time.

Annotations are a reader overlay: they are stored apart from the dashboard and
never enter its definition, so annotating needs no edit rights and a
dashboard save never drops them.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_BODY_CHARS = 4000
MAX_NOTE_CHARS = 2000
MAX_LABEL_CHARS = 120
MAX_POINT_IDS = 5000
MAX_COMMENTS_PER_THREAD = 500

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

ThreadStatus = Literal["open", "resolved"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def component_fingerprint(component: dict[str, Any] | None) -> str | None:
    """Stable hash of a component's stored definition.

    Layout coordinates are left out: moving or resizing a tile does not change
    what a comment on it is about.
    """
    if not component:
        return None
    relevant = {k: v for k, v in component.items() if k not in {"layout", "last_updated"}}
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
    """Where a thread or an annotation points."""

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
class XRange(_Strict):
    kind: Literal["x_range"] = "x_range"
    x0: float | str
    x1: float | str


class YRange(_Strict):
    kind: Literal["y_range"] = "y_range"
    y0: float
    y1: float


class Box(_Strict):
    kind: Literal["box"] = "box"
    x0: float | str
    x1: float | str
    y0: float
    y1: float


class Points(_Strict):
    """A set of rows, identified by the component's selection column."""

    kind: Literal["points"] = "points"
    column: str
    ids: list[str | int | float] = Field(min_length=1, max_length=MAX_POINT_IDS)


class GenomicRegion(_Strict):
    kind: Literal["region"] = "region"
    chrom: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> GenomicRegion:
        if self.end < self.start:
            raise ValueError("region end must not precede its start")
        return self


Geometry = Annotated[XRange | YRange | Box | Points | GenomicRegion, Field(discriminator="kind")]


# ---------------------------------------------------------------------------
# Stored documents
# ---------------------------------------------------------------------------
class Comment(_Strict):
    id: str
    author_id: str
    author_email: str | None = None
    body: str
    mentions: list[str] = Field(default_factory=list)
    """User ids mentioned in the body. Notifications read this."""
    created_at: datetime
    edited_at: datetime | None = None
    deleted: bool = False


class CommentThread(BaseModel):
    id: str
    project_id: str
    anchor: Anchor
    annotation_id: str | None = None
    status: ThreadStatus = "open"
    created_by: str
    created_at: datetime
    updated_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    comments: list[Comment] = Field(default_factory=list)


class Annotation(BaseModel):
    id: str
    project_id: str
    anchor: Anchor
    geometry: Geometry
    label: str
    note: str | None = None
    color: AnnotationColor = "yellow"
    author_id: str
    author_email: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
_MENTION = re.compile(r"^[0-9a-f]{24}$")


class _Body(_Strict):
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)
    mentions: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("comment body must not be blank")
        return v

    @field_validator("mentions")
    @classmethod
    def _object_ids(cls, v: list[str]) -> list[str]:
        bad = [m for m in v if not _MENTION.match(m)]
        if bad:
            raise ValueError(f"mentions must be user ids, got {bad[:3]}")
        return list(dict.fromkeys(v))


class ThreadCreate(_Body):
    anchor: Anchor
    annotation_id: str | None = None


class CommentCreate(_Body):
    pass


class CommentUpdate(_Body):
    pass


class ThreadStatusUpdate(_Strict):
    status: ThreadStatus


class AnnotationCreate(_Strict):
    anchor: Anchor
    geometry: Geometry
    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    color: AnnotationColor = "yellow"


class AnnotationUpdate(_Strict):
    geometry: Geometry | None = None
    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_CHARS)
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    color: AnnotationColor | None = None


class Staleness(BaseModel):
    """How an anchor compares with the dashboard as it is now."""

    component_missing: bool = False
    component_changed: bool = False
    data_changed: bool = False
