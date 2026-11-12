"""What a reader last saw of a dashboard family or a project.

A *reader mark* is a snapshot of the state a reader acknowledged: the
dashboard version they saw, the data each collection was at, and how far the
discussion had gone. The "changed since your last visit" view is the
difference between that snapshot and the current state.

It is per-reader state, never content: writing a mark records no dashboard
version and needs only viewer permission.

The data state is snapshotted rather than derived from a timestamp because
ingestion records no dashboard version, and because several of the clocks
involved are local (``Aggregation.aggregation_time``,
``MultiQCReport.processed_at`` and the ingestion runs use ``datetime.now``).
Comparing ids and commit numbers recorded from the same source is sturdy where
comparing a server clock to a local one is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScopeKind = Literal["dashboard", "project", "prefs"]
MarkMode = Literal["sticky", "previous_visit"]

#: Bounds that keep one mark document small whatever the dashboard holds.
MAX_TRACKED_COLLECTIONS = 200
MAX_TRACKED_REPORTS = 500
MAX_TRACKED_RUN_TAGS = 500
MAX_DISMISSED = 500


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DcSeenState(_Strict):
    """What one data collection was at when the reader saw it."""

    dc_type: str = ""
    #: Delta-backed collections: the commit and depictio's own counter.
    delta_version: int | None = None
    aggregation_version: int | None = None
    row_count: int | None = None
    #: MultiQC collections: every report id and the ``processed_at`` it had,
    #: so a report re-ingested in place (same id, new time) reads as refreshed.
    multiqc_reports: dict[str, str] = Field(default_factory=dict)
    #: Run tags already present, so a new run can be told from a refreshed one.
    run_tags: list[str] = Field(default_factory=list, max_length=MAX_TRACKED_RUN_TAGS)


class ReaderBaseline(_Strict):
    """The state a reader acknowledged. Also what an anonymous reader stores locally."""

    seen_at: datetime
    version_id: str | None = None
    version_seq: int | None = None
    version_content_hash: str | None = None
    dc_states: dict[str, DcSeenState] = Field(default_factory=dict)
    #: The newest comment time seen (comments are stored in UTC).
    comment_cursor_at: datetime | None = None
    #: The newest ingestion run start seen, read from the ingestion records'
    #: own clock and only ever compared with it.
    ingestion_cursor_at: datetime | None = None
    #: Project marks only: the run tags each workflow had registered.
    workflow_runs: dict[str, list[str]] = Field(default_factory=dict)


class DismissedComponent(_Strict):
    """A component the reader marked as seen on its own.

    It stays unmarked while both its definition and its collection's data are
    still what they were when dismissed.
    """

    fingerprint: str | None = None
    data_token: str | None = None


class ReaderMark(_Strict):
    user_id: str
    scope_kind: ScopeKind
    scope_id: str
    baseline: ReaderBaseline | None = None
    last_visit_at: datetime | None = None
    dismissed: dict[str, DismissedComponent] = Field(default_factory=dict)
    mark_mode: MarkMode | None = None
    updated_at: datetime


# ── request bodies ──────────────────────────────────────────────────────────


class ChangesRequest(_Strict):
    """Body of ``POST /dashboards/changes/{id}`` and ``POST /projects/changes/{id}``.

    A signed-in reader sends nothing: the server holds the mark. An anonymous
    reader sends the baseline it keeps in browser storage. ``since`` and
    ``before_run`` ask for the changes after a moment or after one ingestion,
    read-only, and never move a mark.
    """

    baseline: ReaderBaseline | None = None
    dismissed: dict[str, DismissedComponent] | None = Field(default=None)
    since: datetime | None = None
    before_run: str | None = Field(default=None, max_length=200)


class SeenRequest(_Strict):
    """Mark everything (no keys) or some components as seen."""

    component_keys: list[str] | None = Field(default=None, max_length=MAX_DISMISSED)


class PrefsRequest(_Strict):
    mark_mode: MarkMode


def component_key(tab_id: str, index: str) -> str:
    """The key a component is marked under: unique across a dashboard family."""
    return f"{tab_id}:{index}"
