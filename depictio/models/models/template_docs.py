"""Docs page metadata for a pipeline template (``docs/page.yaml``).

A template's docs page is assembled from three sources. ``template.yaml`` and
the recipes give the reference tables (``gen_template_docs``); the dashboard
YAML gives the tab titles, icons, colours, sections, filters and components;
this file gives everything only a person can write: the question each tab
answers, what to look at in it, how to run the pipeline, where the data lives
and how the template was validated. ``gen_template_pages`` joins the three into
the docs page, the catalog card and the index row, so none of them is copied by
hand into the docs repository.

The file sits next to the template it describes::

    depictio/projects/nf-core/<pipeline>/<version>/docs/page.yaml

Markdown fields are inserted as written, so they can hold lists, code blocks
and admonitions.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TemplateStatus(str, Enum):
    """How far a template has been validated, from least to most trusted."""

    DRAFT = "draft"
    EXPERIMENTAL = "experimental"
    REVIEWED = "reviewed"
    CERTIFIED = "certified"


class CalloutPosition(str, Enum):
    """Where a callout lands on the page, by the section it follows."""

    INTRO = "intro"
    QUICK_START = "quick_start"
    REFERENCE = "reference"
    TABS = "tabs"
    RUNNING = "running"
    DATA_STRUCTURE = "data_structure"
    VALIDATION = "validation"


class _Strict(BaseModel):
    # A misspelt key would otherwise vanish from the page without a word.
    model_config = ConfigDict(extra="forbid")


class DocsCallout(_Strict):
    """An admonition (``!!! kind "title"``) placed after a page section."""

    kind: str = Field(default="info", description="Admonition type: info, note, tip, warning")
    title: str
    body: str = Field(..., description="Markdown body of the admonition")
    position: CalloutPosition = CalloutPosition.INTRO

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        allowed = {"info", "note", "tip", "warning", "abstract", "example", "success"}
        if v not in allowed:
            raise ValueError(f"callout kind must be one of {sorted(allowed)}, got {v!r}")
        return v


class DocsQuickStartTab(_Strict):
    """An extra tab in the Quick start block, besides the two every page gets."""

    label: str
    body: str = Field(..., description="Markdown body of the tab")


class DocsDashboardTab(_Strict):
    """Prose for one dashboard tab. ``title`` must match the dashboard YAML."""

    title: str = Field(
        ..., description="Tab title as in the dashboard YAML (main_tab_name for the main tab)"
    )
    summary: str | None = Field(
        default=None, description="One line for the intro list; None leaves the tab out of it"
    )
    question: str = Field(..., description="The question the tab answers, shown in italics")
    description: str = Field(..., description="Markdown under the screenshot, 2 to 4 sentences")
    filters: str | None = Field(
        default=None,
        description="Markdown that replaces the generated Filters line when it needs nuance",
    )
    conditional: str | None = Field(
        default=None,
        description="Markdown for a tab that only some runs produce; it has no screenshot",
    )
    filters_after: str | None = Field(
        default=None, description="Markdown after the components table, inside the collapsible"
    )
    after: str | None = Field(
        default=None, description="Markdown closing the tab block, e.g. a tip on when it appears"
    )
    image: str | None = Field(
        default=None, description="Screenshot slug when it differs from the title-derived one"
    )


class DocsResource(_Strict):
    label: str
    url: str
    note: str


class DocsPerson(_Strict):
    """A GitHub account shown under another name, e.g. an organisation."""

    github: str
    name: str


class DocsAuthorship(_Strict):
    """GitHub handles for each role; an empty reviewer list shows an open slot."""

    developers: list[str | DocsPerson] = Field(default_factory=list)
    reviewers: list[str | DocsPerson] = Field(default_factory=list)
    maintainers: list[str | DocsPerson] = Field(default_factory=list)
    reviewer_note: str | None = Field(
        default=None, description="Replaces the status-derived note under Reviewers"
    )


class TemplateDocs(_Strict):
    """Everything the docs page needs that the template and dashboards do not hold."""

    generate_page: bool = Field(
        default=True,
        description="False keeps a hand-written page; the card and index row stay generated",
    )
    page_title: str = Field(..., description="Page and banner title, e.g. 'Ribosome profiling'")
    status: TemplateStatus
    card_blurb: str = Field(..., description="One sentence on the catalog card")
    index_summary: str = Field(..., description="Short label in the nf-core index table")
    keywords: list[str] = Field(default_factory=list, description="Catalog search keywords")
    logo_branch: str = Field(
        default="master", description="nf-core repository branch the logo images are read from"
    )
    # Page prose: required only when the page is generated (see _page_fields).
    subtitle: str | None = Field(default=None, description="Banner subtitle, one sentence")
    intro: str | None = Field(default=None, description="Markdown lead-in, then the tab list")
    intro_bullets: list[str] = Field(
        default_factory=list, description="Markdown bullets listed after the tab bullets"
    )
    intro_after: str | None = Field(
        default=None, description="Markdown after the tab list (pinned sections, shared filters)"
    )
    quick_start: str | None = Field(
        default=None, description="Markdown under the 'depictio run' command"
    )
    run_vars: list[str] = Field(
        default_factory=list, description="--var NAME=value pairs shown in the quick start"
    )
    data_root: str | None = Field(
        default=None, description="--data-root shown in the quick start (default: a results dir)"
    )
    quick_start_tabs: list[DocsQuickStartTab] = Field(default_factory=list)
    trigger_body: str | None = Field(
        default=None,
        description="Markdown replacing the standard 'From the pipeline itself' tab body",
    )
    trigger_note: str | None = Field(
        default=None, description="Markdown closing the 'From the pipeline itself' tab"
    )
    quick_start_after: str | None = Field(
        default=None, description="Markdown after the quick start tabs"
    )
    reference: str | None = Field(
        default=None,
        description="Markdown before the generated reference tables; {use_count} and "
        "{tile_count} are replaced, and the standard use: sentence is then left out",
    )
    self_adapting_note: str | None = Field(
        default=None, description="Sentence appended to the standard 'Self-adapting layout' box"
    )
    tabs_intro: str | None = Field(default=None, description="Markdown before the dashboard tabs")
    tabs: list[DocsDashboardTab] = Field(default_factory=list)
    tabs_after: str | None = Field(default=None, description="Markdown after the tab blocks")
    running: str | None = Field(default=None, description="Markdown for 'Running the pipeline'")
    data_structure: str | None = Field(
        default=None, description="Markdown for 'Required data structure'"
    )
    validation: str | None = Field(default=None, description="Markdown for 'Validation runs'")
    results_note: str = Field(
        default="AWS test results", description="Note on the standard nf-co.re results link"
    )
    resources: list[DocsResource] = Field(
        default_factory=list, description="Links added after the standard ones"
    )
    callouts: list[DocsCallout] = Field(default_factory=list)
    authorship: DocsAuthorship = Field(default_factory=DocsAuthorship)

    @field_validator("tabs")
    @classmethod
    def _unique_titles(cls, v: list[DocsDashboardTab]) -> list[DocsDashboardTab]:
        titles = [t.title for t in v]
        dupes = sorted({t for t in titles if titles.count(t) > 1})
        if dupes:
            raise ValueError(f"duplicate tab titles: {dupes}")
        return v

    @model_validator(mode="after")
    def _page_fields(self) -> TemplateDocs:
        if not self.generate_page:
            return self
        required = (
            "subtitle", "intro", "quick_start", "reference", "tabs_intro",
            "running", "data_structure", "validation",
        )  # fmt: skip
        missing = [name for name in required if not getattr(self, name)]
        if not self.tabs:
            missing.append("tabs")
        if missing:
            raise ValueError(f"generate_page is true but these are empty: {missing}")
        return self
