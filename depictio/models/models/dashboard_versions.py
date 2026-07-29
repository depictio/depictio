"""Dashboard version-history records.

A dashboard save is a full-document overwrite, so until now the previous state
was simply discarded. These models back a version ledger stored in the
``dashboard_versions`` collection: one record per version, each holding a
complete snapshot of the whole tab family plus a stamp of the data each tab was
authored against.

Three deliberate shapes here:

**A version covers the whole tab family, not one tab.** Tabs are separate
top-level documents (``parent_dashboard_id`` points at the main tab), so a
per-document version could not express "a tab was added" or "a tab was
deleted" — the two changes most likely to need undoing. ``family_id`` is the
main tab's ``dashboard_id``.

**Snapshots carry content only.** ``permissions``, ``is_public``,
``project_id`` and ``_id`` are deliberately absent from ``TabSnapshot``. They
are always read from the live document, so restoring a months-old version can
never resurrect an access grant that was since revoked. Restore must not be a
privilege-escalation path.

**Data provenance is discriminated, not assumed.** Depictio's data collections
do not share one storage format, so "what data was this authored against"
has three different answers — see ``DataCollectionStamp``.

Plain ``BaseModel`` + dict upserts via pymongo, mirroring ``monitoring.py``;
not Beanie.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: How a version came to exist. ``auto`` is an autosave (subject to
#: coalescing); ``explicit`` is a deliberate Save click or a named snapshot;
#: ``restore`` marks the state captured immediately after a restore;
#: ``import`` marks a YAML/JSON reimport, which is exactly when a rollback
#: point is most wanted.
VersionKind = Literal["auto", "explicit", "restore", "import"]

#: Which mechanism can reproduce a data collection's past state.
#:
#: - ``delta``    — Delta Lake time travel (``table``, table+coordinates, the
#:                  ``image`` manifest, and joined/transformed derivatives).
#: - ``manifest`` — an immutable set of content-addressed objects plus an
#:                  as-of instant (``multiqc``, ``jbrowse2``). Nothing is
#:                  rewritten in place, so pinning the object set reproduces
#:                  the state exactly.
#: - ``asset``    — a single opaque blob pinned by content digest
#:                  (``geojson``, ``phylogeny``).
#: - ``none``     — no provenance recorded; the collection renders live and
#:                  the UI says so rather than implying fidelity.
DataVersionKind = Literal["delta", "manifest", "asset", "none"]


class TabSnapshot(BaseModel):
    """One tab's renderable content at capture time.

    Content only — see the module docstring. The dead Dash-era fields
    (``buttons_data``, ``stored_add_button``, ``stored_children_data``,
    ``tmp_children_data``, ``stored_edit_dashboard_mode_button``,
    ``stored_layout_data``) are excluded on purpose: they are still
    round-tripped through ``/save`` but nothing reads them, and including them
    would make every version diff look noisy.

    Note ``left_panel_layout_data`` / ``right_panel_layout_data`` are the
    layouts actually in use; ``stored_layout_data`` is the legacy one and is
    empty on every current dashboard.
    """

    dashboard_id: str
    is_main_tab: bool = True
    tab_order: int = 0
    title: str = ""
    subtitle: str = ""
    main_tab_name: Optional[str] = None
    tab_icon: Optional[str] = None
    tab_icon_color: Optional[str] = None
    icon: Optional[str] = None
    icon_color: Optional[str] = None
    icon_variant: Optional[str] = None
    workflow_system: str = "none"
    notes_content: str = ""
    stored_metadata: list[dict[str, Any]] = Field(default_factory=list)
    left_panel_layout_data: list[dict[str, Any]] = Field(default_factory=list)
    right_panel_layout_data: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class DataCollectionStamp(BaseModel):
    """What a dashboard version was authored against, for one data collection.

    Discriminated on ``version_kind`` because depictio's six data collection
    types do not share a storage format. Every mechanism-specific field is
    optional so a stamp stays valid when its collection's provenance is
    incomplete — which is the normal case, not an edge case: aggregations
    written before Delta provenance existed, and UI uploads, both carry no
    ``delta_version``.
    """

    dc_id: str
    dc_type: str = ""
    workflow_tag: str = ""
    data_collection_tag: str = ""
    version_kind: DataVersionKind = "none"

    # Schema at capture time, for compatibility checking on restore/preview.
    schema_hash: str = ""
    columns: list[dict[str, str]] = Field(default_factory=list)
    row_count: Optional[int] = None

    # version_kind == "delta"
    delta_version: Optional[int] = None
    aggregation_version: Optional[int] = None
    delta_commit_timestamp: Optional[datetime] = None

    # version_kind == "manifest"
    as_of: Optional[datetime] = None
    manifest_digest: Optional[str] = None
    s3_locations: list[str] = Field(default_factory=list)
    sample_count: Optional[int] = None

    # version_kind == "asset"
    asset_digest: Optional[str] = None
    asset_key: Optional[str] = None
    asset_bytes: Optional[int] = None

    #: Parts of this collection that are NOT covered by the stamp — e.g.
    #: ``["image_pixels"]`` for an image DC, whose manifest is versioned but
    #: whose underlying image blobs live at a user-supplied prefix with no
    #: content addressing. Recorded so the UI can state partial coverage
    #: instead of implying the whole collection is reproducible.
    unversioned_parts: list[str] = Field(default_factory=list)

    #: Why provenance is absent, when ``version_kind == "none"``. Surfaced
    #: verbatim in the compatibility report.
    reason: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class DashboardVersion(BaseModel):
    """One entry in a dashboard family's version timeline."""

    version_id: str = Field(..., description="uuid4 hex — the public handle")
    family_id: str = Field(..., description="Main tab's dashboard_id; the version's subject")
    project_id: str
    seq: int = Field(..., description="Monotonic per family; displayed as 'v12'")

    kind: VersionKind = "auto"
    label: Optional[str] = Field(default=None, description="User-assigned name")
    pinned: bool = Field(default=False, description="Pinned versions are never pruned")

    author_id: Optional[str] = None
    author_email: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    #: End of this version's coalescing window, fixed when the version is
    #: created. Anchored rather than sliding: a sliding window would let one
    #: long editing session collapse into a single unreviewable entry.
    coalesce_until: datetime = Field(default_factory=datetime.now)
    #: How many saves folded into this version. Rendered as "12 saves over 4 min".
    save_count: int = 1

    #: sha256 over the canonicalised tab list. Two consecutive saves with the
    #: same hash are the same state, so the second writes nothing — which is
    #: what keeps the async screenshot task's `last_saved_ts` rewrite out of
    #: the ledger without special-casing it.
    content_hash: str = ""

    tabs: list[TabSnapshot] = Field(default_factory=list)
    data_collections: list[DataCollectionStamp] = Field(default_factory=list)

    #: Denormalised counts, stored on the record rather than derived on read.
    #: The list endpoint projects ``tabs`` away — it is ~95% of a record's
    #: bytes — so a timeline row has nothing left to count from. Kept in step
    #: with ``tabs`` by the validator below rather than by each writer.
    tab_count: int = 0
    component_count: int = 0

    #: Set on ``kind="restore"``: the version whose content was restored.
    parent_version_id: Optional[str] = None

    #: Schema version of this record itself, so a future shape change can be
    #: migrated rather than guessed at.
    record_schema_version: int = 1

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _sync_counts(self) -> "DashboardVersion":
        """Derive the counts from ``tabs`` whenever the snapshot is present.

        A caller can never set them inconsistently, and a coalescing fold that
        replaces ``tabs`` gets the matching counts for free. Records read back
        from Mongo arrive with ``tabs`` projected away, so an explicit zero is
        only trusted when there is genuinely nothing to count.
        """
        if self.tabs:
            object.__setattr__(self, "tab_count", len(self.tabs))
            object.__setattr__(
                self, "component_count", sum(len(tab.stored_metadata) for tab in self.tabs)
            )
        return self


class DashboardVersionSummary(BaseModel):
    """Timeline row — everything except the snapshot payload.

    The drawer lists versions far more often than it opens one, and ``tabs``
    is ~95% of a record's bytes, so the list endpoint projects it away.
    """

    version_id: str
    family_id: str
    seq: int
    kind: VersionKind
    label: Optional[str] = None
    pinned: bool = False
    author_id: Optional[str] = None
    author_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    save_count: int = 1
    content_hash: str = ""
    tab_count: int = 0
    component_count: int = 0
    parent_version_id: Optional[str] = None
    #: Coarse per-version summary of data provenance, so the timeline can badge
    #: "3 collections pinned, 1 live" without shipping every stamp.
    data_version_kinds: dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")
