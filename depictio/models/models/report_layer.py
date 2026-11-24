"""The report layer: a dashboard's own export notes, cover and layout (#1457).

Notebook export renders a dashboard as a report. What that report says beyond
the tiles — its introduction, its conclusion, its cover, which tiles belong in
it and in which order — is authored once and kept on the dashboard as the
*report layer*, so it survives exports, versions and restores like the rest of
the dashboard's content.

It lives on the main tab (like ``shared_labels``), is written by one route
(``PUT /dashboards/report_layer/{id}``) and read by the notebook-export
generator. ``intro`` and ``conclusion`` hold TipTap JSON (the viewer's rich
text): a dict ``{"type": "doc", "content": [...]}``, kept as a plain dict so a
change to TipTap's shape never makes an older dashboard unloadable. ``state``
is the analysis state the report is drawn and exported at — the same
``AnalysisState`` the export request carries — so a reader gets the report the
author composed, not whatever filters their visit happens to hold.

``revision`` is bumped by every write: the editor sends the revision it read
back with its next save (``base_revision``), and a writer who read an older
one is refused with 409, the stored layer and who last wrote it, instead of
silently overwriting a colleague's text.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.models.models.analysis_state import AnalysisState


def _objectids_to_str(value: Any) -> Any:
    """ObjectIds back to strings, recursively."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {k: _objectids_to_str(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_objectids_to_str(v) for v in value]
    return value


#: The report's look, where a style exists: the PDF prints in colour or mono
#: (``pdf_style`` already means this to the export); ``None`` keeps the export
#: request's own choice.
ReportStyle = Literal["colour", "mono"]

#: Page orientation the PDF gives one tile. ``auto`` keeps the page as it is.
ReportOrientation = Literal["auto", "portrait", "landscape"]

#: Where a tab's part sits in the report: the body, or after it as an appendix.
ReportPlacement = Literal["body", "appendix"]


#: The PDF's paper.
ReportPaper = Literal["a4", "letter"]

#: How wide the report's tiles are by default: the dashboard's rows, or each
#: tile across the page.
ReportTileWidth = Literal["row", "full"]

#: Where an advanced visualisation draws its controls in the report.
ReportVizControls = Literal["popover", "rail", "header"]


class ReportSettings(BaseModel):
    """The report's own options, for the whole document. Every default is the
    report as it was before these existed, so a stored layer without them
    exports unchanged."""

    model_config = ConfigDict(extra="forbid")

    # PDF
    paper: ReportPaper = "a4"
    # The PDF's page; a tile's own orientation still turns its page.
    landscape: bool = False
    # Layout
    tile_width: ReportTileWidth = "row"
    viz_controls: ReportVizControls = "popover"
    # Parts of the document
    toc: bool = True
    export_details: bool = True
    how_to_run: bool = True
    methods: bool = True
    code: bool = True
    # Captions
    numbering: bool = True
    provenance: bool = True


class ReportCover(BaseModel):
    """The title block. ``None`` values fall back to the export's own defaults
    (dashboard title, project name, the project's owners, the export day)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    date: str | None = None


class ReportTile(BaseModel):
    """One tile's place in the report.

    ``tab_id`` + ``component_id`` name it (the tile's ``index``). Settings not
    given keep the export's defaults, so a dashboard whose layer only asks one
    tile to change still exports every other tile exactly as it did.
    """

    model_config = ConfigDict(extra="forbid")

    tab_id: str
    component_id: str
    # The tile's caption in the report, replacing its dashboard caption when
    # not None (an empty string prints no caption).
    caption: str | None = None
    in_report: bool = True
    in_pdf: bool = True
    # Explicit position of the tile among the report's tiles; ``None`` keeps
    # the dashboard's own reading order behind any ordered ones.
    order: int | None = None
    orientation: ReportOrientation = "auto"
    # Another section of the report to move the tile into; ``None`` keeps it
    # in its own.
    section: str | None = None
    page_break_before: bool = False
    # The whole width of the page, out of the dashboard row it shares with
    # other tiles; the rest of that row keeps sharing it. Cards keep their strip.
    full_width: bool = False


class ReportTab(BaseModel):
    """One tab's place in the report: its part's position, and whether the
    body or the appendix (after the conclusion) carries it."""

    model_config = ConfigDict(extra="forbid")

    tab_id: str
    placement: ReportPlacement = "body"
    order: int | None = None


class ReportLayer(BaseModel):
    """The whole layer, as stored on the main tab."""

    model_config = ConfigDict(extra="forbid")

    intro: dict[str, Any] | None = None
    conclusion: dict[str, Any] | None = None
    cover: ReportCover | None = None
    # The analysis state the report is drawn and exported at; ``None`` leaves
    # the export's request state in charge.
    state: AnalysisState | None = None
    # Bumped by every write; the editor's optimistic-concurrency token.
    revision: int = 0
    style: ReportStyle | None = None
    settings: ReportSettings = Field(default_factory=ReportSettings)
    tiles: list[ReportTile] = Field(default_factory=list)
    tabs: list[ReportTab] = Field(default_factory=list)
    # The GET seeded this layer's intro from the dashboard's notes; nothing
    # was written. The editor round-trips it so the generator can tell a real
    # intro from the standing note.
    seeded_from_notes: bool = False
    # Who last wrote it, for a 409's "ask them before overwriting".
    updated_by: Optional[str] = None
    # Naive UTC (PyMongo stores and reads BSON dates as naive UTC).
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _stored_objectids_load(cls, data: Any) -> Any:
        """A restore that rehydrated ids wrote ObjectIds into the stored layer
        (``updated_by``, tab ids, even TipTap text) and the dashboard stopped
        loading. Those documents must come back, values as strings."""
        return _objectids_to_str(data)


class ReportLayerPut(BaseModel):
    """The PUT body: the layer to write, and the revision it was read at.

    A ``base_revision`` that is not the stored layer's is refused with 409
    (the stored layer and its author come back with it), so two writers cannot
    overwrite each other's prose.
    """

    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(default=0, ge=0)
    layer: ReportLayer


class ReportPreviewRequest(BaseModel):
    """The body of the preview render: a plain POST, ``force`` to re-render.

    The preview of an unchanged report is served from the finished job of the
    last identical request; ``force`` queues a new one regardless.
    """

    model_config = ConfigDict(extra="forbid")

    force: bool = False


class ReportOutlineEntry(BaseModel):
    """One line of the report's outline: a tab part, a section, or a tile.

    A ``component`` entry carries the tile's own caption as the editor shows
    it, and the *layer's* settings for it — ``in_report`` says whether the
    report actually holds the tile (the outline lists excluded ones too, with
    ``in_report: False``), the rest is how the layer places it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["tab", "section", "component"]
    tab_id: str
    title: str
    level: int | None = None
    component_id: str | None = None
    component_type: str | None = None
    caption: str | None = None
    in_report: bool = True
    in_pdf: bool = True
    orientation: ReportOrientation = "auto"
    section: str | None = None
    page_break_before: bool = False
    full_width: bool = False
    order: int | None = None
    # A section's own look, as the dashboard draws its header: an Iconify id,
    # a Mantine palette name and the line under its title. Sections only.
    icon: str | None = None
    color: str | None = None
    description: str | None = None


class ReportOutlineTab(BaseModel):
    """One tab's part of the outline: what the layer says about its place, and
    the tab's own identity (its sidebar icon and the accent the report tints
    it with, as hex) so the editor draws it as the report does."""

    model_config = ConfigDict(extra="forbid")

    tab_id: str
    title: str
    placement: ReportPlacement = "body"
    order: int | None = None
    icon: str | None = None
    color: str | None = None
    entries: list[ReportOutlineEntry] = Field(default_factory=list)


class ReportCoverDefaults(BaseModel):
    """The cover's fields as the export fills them, ignoring the layer's cover.

    The dashboard's title, the project's name, the project's owners, the day
    of the export — what the cover shows wherever the layer sets nothing, and
    what the editor resets its fields to.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    date: str


class ReportOutline(BaseModel):
    """The report's shape, as the report editor page draws it.

    ``preview_available`` is whether a preview render can run on this
    deployment at all; ``preview_unavailable_reason`` is the sentence to show
    when it cannot, with the install hint.
    """

    model_config = ConfigDict(extra="forbid")

    dashboard_id: str
    title: str
    revision: int = 0
    tabs: list[ReportOutlineTab] = Field(default_factory=list)
    cover_defaults: ReportCoverDefaults
    preview_available: bool = False
    preview_unavailable_reason: str | None = None


def seed_intro_from_notes(notes_content: str) -> dict[str, Any] | None:
    """The dashboard's notes as a minimal TipTap document for the intro.

    A GET with nothing stored shows the author's notes as a starting point for
    the report's introduction (they wrote prose on the dashboard; the report
    should not start from an empty page). One paragraph per non-empty line;
    nothing is written — the editor saves it, or not. ``None`` when the notes
    are empty.
    """
    paragraphs = []
    for line in (notes_content or "").replace("\r\n", "\n").split("\n"):
        text = line.strip()
        if not text:
            continue
        paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": text}]})
    if not paragraphs:
        return None
    return {"type": "doc", "content": paragraphs}
