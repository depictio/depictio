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

from pydantic import BaseModel, ConfigDict, Field

#: How a version came to exist. ``auto`` is an autosave (subject to
#: coalescing); ``explicit`` is a deliberate Save click or a named snapshot;
#: ``restore`` marks the state captured immediately after a restore;
#: ``import`` marks a YAML/JSON reimport, which is exactly when a rollback
#: point is most wanted.
VersionKind = Literal["auto", "explicit", "restore", "import"]

#: Shape of a ``DashboardVersion`` record. Bumped when ``TabSnapshot`` gains
#: fields, so a reader can tell a snapshot that predates a field (and so says
#: nothing about it) from one that recorded the field's default.
#:
#: - 1: layout, components, titles, icons, notes.
#: - 2: the presentation settings added since (sections, colours, brand,
#:      guide, funnel, panel/width defaults, autofit, tab group) and
#:      ``source_key``.
RECORD_SCHEMA_VERSION = 2

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

    Every field added after record schema 1 defaults to what ``DashboardData``
    defaults it to, so a schema-1 record still validates. Restore and preview
    read the stored dicts rather than this model, and write only the keys a
    stored tab actually holds: a schema-1 snapshot therefore leaves those
    settings as they are live instead of resetting them to these defaults.
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

    # ── Record schema 2 ──
    # Sidebar category of a child tab. Family structure, like `tab_order`.
    tab_group: Optional[str] = None
    # Section specs stay plain dicts: `FilterSectionSpec` forbids extras, and a
    # snapshot must still load after that model gains or drops a key.
    filter_sections: list[dict[str, Any]] = Field(default_factory=list)
    grid_sections: list[dict[str, Any]] = Field(default_factory=list)
    category_colors: Optional[dict[str, dict[str, str]]] = None
    funnel_filtering: bool = True
    filter_panel_default: Literal["open", "collapsed"] = "open"
    content_width_default: Literal["full", "wide", "comfortable", "compact"] = "full"
    show_tab_header: bool = True
    # Read from the main tab only, as the viewer does; a child tab's own copy
    # is never shown, so it is recorded at its default.
    show_guide: bool = True
    guide_intro: str = ""
    advanced_viz_controls: Literal["popover", "rail", "header"] = "popover"
    autofit: bool = True
    # The stored dict, not a `BrandTheme`: dumping the model would add every
    # unset key, and each key BrandTheme gains later would then move the hash
    # of every branded dashboard. The logo URLs in it name bytes that are not
    # versioned (they live in `branding_assets`), so restore keeps the live ones.
    brand_theme: Optional[dict[str, Any]] = None
    # Identity, not content: never hashed and never written onto a live tab.
    # Kept so a tab a restore recreates is still the one its YAML refreshes.
    source_key: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


#: Fields that name a tab rather than describe it. Restore matches tabs on
#: ``dashboard_id`` and never rewrites it; ``source_key`` belongs to the import
#: that made the tab, so only a recreated tab takes it back.
TAB_IDENTITY_FIELDS: frozenset[str] = frozenset({"dashboard_id", "source_key"})

#: Fields that place a tab in its family. Restore writes them, but a preview
#: leaves them live: the sidebar builds the tab strip from the live family, so a
#: past order or grouping would disagree with the tabs actually on screen.
TAB_STRUCTURE_FIELDS: frozenset[str] = frozenset({"tab_order", "is_main_tab", "tab_group"})

#: ``TabSnapshot`` as it was at record schema 1. Every later field is hashed only
#: when it differs from its default, so a family that uses none of them keeps
#: the hash it had before they existed: no spurious version on its first save
#: after an upgrade, and the timeline still finds its current version.
TAB_SCHEMA_1_FIELDS: frozenset[str] = frozenset(
    {
        "dashboard_id",
        "is_main_tab",
        "tab_order",
        "title",
        "subtitle",
        "main_tab_name",
        "tab_icon",
        "tab_icon_color",
        "icon",
        "icon_color",
        "icon_variant",
        "workflow_system",
        "notes_content",
        "stored_metadata",
        "left_panel_layout_data",
        "right_panel_layout_data",
    }
)


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

    #: Denormalised counts, stored rather than derived.
    #:
    #: The timeline lists versions far more often than it opens one, so the
    #: list endpoint projects ``tabs`` away — which means anything computed
    #: *from* ``tabs`` is unavailable exactly where it is displayed. These
    #: must therefore be real persisted fields: a ``@property`` would not be
    #: serialised by ``model_dump`` at all, and a fallback over the projected
    #: document would silently read zero.
    tab_count: int = 0
    component_count: int = 0

    #: Set on ``kind="restore"``: the version whose content was restored.
    parent_version_id: Optional[str] = None

    #: Schema version of this record itself, so a future shape change can be
    #: migrated rather than guessed at. See ``RECORD_SCHEMA_VERSION``.
    record_schema_version: int = RECORD_SCHEMA_VERSION

    model_config = ConfigDict(extra="forbid")

    def recount(self) -> "DashboardVersion":
        """Refresh the denormalised counts from ``tabs``. Returns self."""
        self.tab_count = len(self.tabs)
        self.component_count = sum(len(tab.stored_metadata) for tab in self.tabs)
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
