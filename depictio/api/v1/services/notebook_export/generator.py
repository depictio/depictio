"""From an :class:`ExportPlan` to a Quarto document (``.qmd``).

The endpoint gathers everything that needs Mongo, Delta or link resolution
into an ``ExportPlan``; this module only turns the plan into cells, so it
runs in tests with no infrastructure. The same pass that names cells also
produces the preflight the export modal shows.
"""

from __future__ import annotations

import pprint
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

import polars as pl

from depictio.models.models.analysis_state import (
    AnalysisState,
    NotebookPreflight,
    NotebookPreflightComponent,
    NotebookPreflightDC,
    NotebookPreflightStage,
)
from depictio.models.models.report_layer import ReportLayer, ReportSettings, ReportTile
from depictio.notebook.components import readable_name
from depictio.notebook.qmd_safe import comment as _qmd_comment
from depictio.notebook.qmd_safe import defuse, defuse_code, one_line
from depictio.notebook.qmd_safe import esc as _esc
from depictio.notebook.qmd_safe import typst_str as _typst_str
from depictio.notebook.report_runtime import (
    filters_placeholder,
    tile_close,
    tile_open,
    tile_ref,
)
from depictio.notebook.theme import palette_hex, resolve_primary, sans_stack

from .aggregations import agg_expr_source
from .cells import Cell, md_cell, render_qmd
from .classify import API_REASON, Classification, classify
from .names import NameAllocator, slug
from .pdf_typst import TYPST_TILE_DONE, typst_preamble
from .predicates import PredicateSource, emit_filter_expr, emit_predicate, is_region_filter
from .provenance import (
    EXPORT_DETAILS_ICON,
    PARAMS_ANCHOR,
    PROVENANCE_ICON,
    RUN_ICON,
    header_markdown,
)
from .quarto import QuartoFrontMatter, paper_brand, paper_brand_dark
from .reading_order import (
    ComponentUnit,
    MarkdownUnit,
    filter_icon_id,
    grid_columns,
    ordered_units,
    tab_display_name,
    tab_link_key,
)
from .report_chrome import (
    DARK_CSS,
    DIV_CLOSE,
    ORPHAN,
    REPORT_CSS,
    SURFACE_OPEN,
    TOC_SCOPE_JS,
    about_callout,
    about_callout_many,
    appbar_html,
    cell_open,
    drop_orphan_links,
    footer_html,
    grid_open,
    mark_css,
    methods,
    pdf_structures,
    stepper_markdown,
    title_logo_css,
)
from .report_theme import BRAND_DEFAULTS, CHROME_CSS, CHROME_JS, brand_rules
from .resources import script, style

# What a highlight can show (``highlightTile.ts``: ``HIGHLIGHTABLE_TYPES``).
_HIGHLIGHTABLE = frozenset({"figure", "advanced_viz"})

# SectionAccordion's TAB_LINK: a markdown link whose target is another tab.
# A target may hold one level of parentheses: `tab:Environment (CTD)`.
_TARGET = r"((?:[^()\n]|\([^()\n]*\))+)"
_TAB_LINK_RE = re.compile(r"\[([^\]]+)\]\(tab:" + _TARGET + r"\)")
_PARAMS_LINK_RE = re.compile(r"\[([^\]]+)\]\(params:[^)]*\)")
_SECTION_LINK_RE = re.compile(r"\[([^\]]+)\]\(section:" + _TARGET + r"\)")
_LEGEND_RE = re.compile(r"\{\{legend:([A-Za-z0-9_.-]+)\}\}")
# A text tile's inline icon, `![](icon:mdi:flask-outline)` (TextRenderer draws it).
INLINE_ICON_RE = re.compile(r"!\[[^\]]*\]\(icon:([a-z0-9-]+:[a-z0-9-]+)\)")

# One heading level per level of the thing itself, so the document outline (and
# with it the table of contents) reads the way the dashboard is built: the
# export's title, then a tab, then a section. The reading order gives the main
# tab level 1 and its siblings level 2, which put a main-tab section and a
# sibling *tab* at the same depth; these two constants flatten that — every tab
# is a tab, every section is a section, wherever it sits in the family.
RESULTS_LEVEL = 2
TAB_LEVEL = 3
SECTION_LEVEL = 4

# The tabs are the report's body, and they need something above them saying so:
# without it the first tab follows the filters as if it were more chrome, and
# the reader has no single heading to fold the whole dashboard away by.
RESULTS_HEADING = "Results"
RESULTS_ICON = "mdi:view-dashboard-outline"
# The filter panel's own marks: the panel itself, the summary at the top of it
# and the "Filter funnel" view behind its header button.
FILTERS_ICON = "mdi:filter-variant"
SUMMARY_ICON = "mdi:format-list-bulleted"
FUNNEL_ICON = "mdi:filter-check-outline"
# The PDF's appendices: every tab after the first, under one heading.
APPENDICES_HEADING = '::: {.content-visible when-format="typst"}\n## Appendices {#appendices}\n:::'


def _appendix_letter(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


#: A tile the layer keeps out of the PDF, wrapped so only the HTML shows it.
HTML_ONLY_OPEN = '::: {.content-visible when-format="html"}'
#: The same fold the other way round: only the PDF (typst) shows the content.
TYPST_ONLY_OPEN = '::: {.content-visible when-format="typst"}'
#: A page break in the PDF only: a large table's own page.
TYPST_PAGE_BREAK_MD = "`#pagebreak(weak: true)`{=typst}"

#: Rows from which a table starts a new PDF page: about a third of a page.
TABLE_PAGE_ROWS = 12

PAGE_BREAK_MD = (
    # The page break the layer asks for before a tile: a typst one in the PDF,
    # a CSS one in the HTML (Quarto's typst writer reads only the raw block).
    '::: {.content-visible when-format="html"}\n'
    '<div style="break-after:page"></div>\n'
    ":::\n\n"
    "`#pagebreak()`{=typst}"
)


# ── The live preview's DOM markers (contract #1457, §2) ──────────────────────
#
# Every HTML report carries them; the report editor patches the rendered page
# in the browser (``assets/preview_patch.js``). Pandoc fenced divs with
# attributes: pandoc's typst writer drops the attributes, so the PDF keeps its
# own layout. The fences nest, a part (6) holding tabs (5), a tab holding
# sections (4), a section holding the tiles' own ``:::`` placeholders (the
# runtime's contract, kept as it is) and ``#fig-``/``#tbl-`` floats.

PART_FENCE = "::::::"
TAB_FENCE = ":::::"
SECTION_FENCE = "::::"


def part_div(kind: str) -> str:
    """A part's marker div, opened (``intro``, ``conclusion``, ``appendix``)."""
    return f'{PART_FENCE} {{data-depictio-part="{kind}"}}'


def tab_div(tab_id: str) -> str:
    """A tab part's marker div, opened; the value is the tab's dashboard id."""
    return f'{TAB_FENCE} {{data-depictio-tab="{_esc(tab_id)}"}}'


def section_div(tab_id: str, title: str) -> str:
    """A section's marker div, opened: ``<tab_id>:<section title>``."""
    return f'{SECTION_FENCE} {{data-depictio-section="{_esc(f"{tab_id}:{title}")}"}}'


def tile_anchor_id(ref: str) -> str:
    """The HTML anchor of a tile, from its ``<tab_id>:<index>`` ref: a link to
    ``report.html#dpx-tile-...`` lands on the component."""
    return "dpx-tile-" + re.sub(r"[^A-Za-z0-9_-]", "-", ref)


def tile_anchors(refs: list[str]) -> str:
    """The anchors of a tile (one per card in a strip), as an HTML-only raw
    block: the PDF has no use for them, and a typst label on a marker block
    would be one more thing for its layout to place."""
    spans = "".join(f'<span id="{tile_anchor_id(r)}" class="dpx-anchor"></span>' for r in refs)
    return f"```{{=html}}\n{spans}\n```"


def caption_marked(caption: str) -> str:
    """The caption paragraph carrying the preview's caption marker."""
    return f'[{caption}]{{data-depictio-caption=""}}'


#: Nesting cap of the layer prose walk: no author JSON walks the interpreter's
#: recursion limit into a 500 (the export must always succeed).
_MAX_PROSE_DEPTH = 50


def _tiptap_markdown(node: dict[str, Any] | None, depth: int = 0) -> str:
    """TipTap JSON (the report layer's intro and conclusion) as markdown.

    One small helper, the only reader of that shape: paragraphs, headings,
    lists, quotes, code blocks, the marks a text editor writes and hard
    breaks; anything else degrades to its text. Total on any author JSON (an
    editor can PUT shapes this never wrote): nodes, marks, attrs and levels
    of the wrong type are ignored, nesting past ``_MAX_PROSE_DEPTH`` stops
    the walk. The result still goes through ``defuse`` (author markdown: its
    emphasis survives, a chunk or a shortcode typed into it does not), so
    nothing here has to be safe — only faithful.
    """
    if not isinstance(node, dict) or depth > _MAX_PROSE_DEPTH:
        return ""
    ntype = str(node.get("type") or "")

    def children(node: dict[str, Any]) -> list[Any]:
        content = node.get("content")
        return content if isinstance(content, list) else []

    def render_content(items: Any) -> str:
        if not isinstance(items, list):
            return ""
        return "".join(
            _tiptap_markdown(child, depth + 1) for child in items if isinstance(child, dict)
        )

    def inline(node: dict[str, Any]) -> str:
        text = str(node.get("text") or "")
        marks = node.get("marks")
        for mark in marks if isinstance(marks, list) else []:
            if not isinstance(mark, dict):
                continue
            mtype = str(mark.get("type") or "")
            if mtype == "bold":
                text = f"**{text}**" if text else text
            elif mtype == "italic":
                text = f"*{text}*" if text else text
            elif mtype == "strike":
                text = f"~~{text}~~" if text else text
            elif mtype == "code":
                text = f"`{text}`" if text else text
        return text

    if ntype == "text":
        return inline(node)
    if ntype == "hardBreak":
        return "\\\n"
    if ntype == "paragraph":
        return render_content(children(node)) + "\n\n"
    if ntype == "heading":
        attrs = node.get("attrs")
        raw = attrs.get("level") if isinstance(attrs, dict) else None
        level = 1 if isinstance(raw, bool) or not isinstance(raw, (int, float)) else int(raw)
        return f"{'#' * min(6, max(1, level + 1))} {one_line(render_content(children(node)))}\n\n"
    if ntype in ("bulletList", "orderedList"):
        lines = []
        for child in children(node):
            if not isinstance(child, dict) or child.get("type") != "listItem":
                continue
            body = render_content(child.get("content")).strip()
            marker = "-" if ntype == "bulletList" else "1."
            lines.extend(f"{marker} {line}" for line in body.split("\n") if line)
        return "\n".join(lines) + ("\n\n" if lines else "")
    if ntype == "blockquote":
        body = render_content(children(node)).strip()
        return "".join(f"> {line}\n" for line in body.split("\n") if line) + "\n" if body else ""
    if ntype == "codeBlock":
        # The code as it is: its lines are its meaning (not one-lined), and
        # the fence outlongs any backtick run inside, so the block never
        # closes early.
        body = "".join(str(c.get("text") or "") for c in children(node) if isinstance(c, dict))
        fence = "`" * (3 + len(max(re.findall(r"`+", body), default="", key=len)))
        return f"{fence}\n{body}\n{fence}\n\n"
    # Unknown block node: its content, if any, as the best approximation.
    return render_content(children(node))


def _layer_prose(node: dict[str, Any] | None) -> str:
    """The layer's TipTap prose as markdown, made inert, trailing space off."""
    return defuse(_tiptap_markdown(node)).rstrip("\n") + "\n"


def _cover_owner_names(project: dict[str, Any] | None) -> list[str]:
    """The project's owners as the cover's default authors."""
    owners = ((project or {}).get("permissions") or {}).get("owners") or []
    names = []
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        name = str(owner.get("username") or owner.get("email") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


# The closing part: what produced the data and the report, and what to cite.
METHODS_HEADING = "Methods and citations"

#: The element whose attributes carry the report's settings to its runtime.
SETTINGS_MARKER_ID = "depictio-report-settings"

#: Figures and tables without their number, when the report's settings say
#: so: Quarto numbers every float and has no option to stop, so the page takes
#: the "Figure 3: " off each caption once it has loaded (the PDF sets typst's
#: own ``numbering: none``).
UNNUMBER_SCRIPT = (
    "<script>document.querySelectorAll('.quarto-float figcaption').forEach(function(c){"
    "var n=c.firstChild;if(n&&n.nodeType===3)n.nodeValue=n.nodeValue.replace("
    "/^\\s*(?:Figure|Table)[\\s\\u00a0]+\\d+[:.]?\\s*/,'')});</script>"
)
METHODS_ICON = "mdi:book-open-variant"

# ``activeFilters.ts``: what the panel's summary prints for a filter's value.
_MAX_INLINE_VALUES = 2
_MAX_LABEL_CHARS = 28
_RANGE_TYPES = frozenset({"RangeSlider", "DateRangePicker", "DatePicker", "Timeline"})

# The chrome the three formats cannot get from Depictio's own stylesheets: the
# section rail, and the fold the live dashboard gets from Mantine's accordion.
# Inline rather than a linked asset, like every other asset in these exports —
# the file has to still work months later, off the network that served it — and
# strictly additive: without the script the headings, the colours, the icons and
# every number are all still there, they just do not fold.
NOTEBOOK_CHROME = style("notebook_chrome.css") + "\n" + script("notebook_chrome.js")


# Paper, the live app's default chrome (`chrome/variants/glass/glass.css`),
# laid over the chrome above: the report as the dashboard reads in the app.
# Every value is a `--gl-*` token of that stylesheet resolved for the light
# scheme against Mantine's palette (CSS can mix colours itself, so the
# hairlines keep the stylesheet's own `color-mix`). The body font and the
# primary come from the brand (`--dpx-font`, `--dpx-primary`,
# `--dpx-accent-fg`, set beside it). Strictly a restyle: no structure, no
# script, so a report without it is the classic look with every result intact.
PAPER_CHROME = style("paper_chrome.css")


def _css_value(value: str) -> str:
    """A brand font stack as a CSS value: nothing that could close the rule."""
    return re.sub(r"[;{}<>]", "", value).strip()


@dataclass
class DCPlan:
    dc_id: str
    tag: str
    wf_id: str | None = None
    dtypes: dict[str, pl.DataType] | None = None  # None = schema unknown at export
    initial_rows: int | None = None
    n_cols: int | None = None
    # The Delta commit the exported state pins this collection to; None reads
    # current data.
    version: int | None = None

    @property
    def columns(self) -> set[str] | None:
        return set(self.dtypes) if self.dtypes is not None else None

    def dtype(self, column: str) -> pl.DataType | None:
        return (self.dtypes or {}).get(column)


@dataclass
class StagePlan:
    """One active filter, and what it adds to each data collection."""

    index: str
    label: str
    column: str | None
    interactive_component_type: str | None
    value: Any
    source_dc_id: str | None
    # The identity the filter panel gives this control: an Iconify id and the
    # accent (``icon_color``/``color``) it tints the icon with.
    icon: str | None = None
    color: str | None = None
    # Cleaned filter entries (``clean_filter_payload`` shape, plus ``index``
    # and ``link`` flags) that become applicable to each DC at this stage —
    # the user's own filter where its DC matches, and any link-resolved ones.
    per_dc: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    rows_by_dc: dict[str, int | None] = field(default_factory=dict)


@dataclass
class ExportPlan:
    tabs: list[dict[str, Any]]
    project: dict[str, Any] | None
    state: AnalysisState
    stages: list[StagePlan]
    title: str
    # The dashboard's report layer (#1457), as stored on its main tab: the
    # export's intro, conclusion, cover and tile/tab placement. Raw dict, as
    # stored; ``NotebookBuilder`` validates it and falls back to a layer-less
    # export when it does not validate.
    report_layer: dict[str, Any] | None = None
    dcs: list[DCPlan] = field(default_factory=list)
    subtitle: str | None = None
    exported_by: str | None = None
    exported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    instance: str | None = None
    api_url: str = "https://depictio.example.org"
    warnings: list[str] = field(default_factory=list)
    # The browser-tab icon of the rendered report, as a data URI (the
    # endpoint resolves it; ``QuartoFrontMatter.favicon_data_uri``).
    favicon_data_uri: str | None = None
    # The Depictio that produced this file. A report outlives the deployment
    # it came from, and "which version wrote this" is the first question when
    # one of them disagrees with the live dashboard.
    depictio_version: str | None = None
    brand: dict[str, Any] | None = None
    # Per-tab overrides on top of ``brand``: each tab of a family is its own
    # dashboard_id with its own possible ``brand_theme``, keyed here so a
    # tab's own section of the export can carry its own identity rather than
    # the family's. Same shape as ``brand`` (``app_name``/``primary``/
    # ``logo_data_uri``).
    tab_brands: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Iconify id -> inline SVG markup, resolved once for every tab and
    # section icon the family uses (``icons.py``, network I/O — done in the
    # endpoint so this module stays infra-free). A missing id renders no
    # icon rather than breaking the export.
    icons: dict[str, str] = field(default_factory=dict)
    # A text tile's live values at export time, by its index: what
    # ``bulk_compute_cards`` answered under the exported filters
    # (``{name: value, "param:KEY": value}``). The document recomputes them
    # through the API when it runs, and falls back on these offline.
    text_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    # The report's look: ``paper`` (the live app's default chrome, from the
    # instance brand) or ``classic`` (Mantine's defaults, Plotly's own figures).
    theme: str = "paper"
    # The report host of the static runtime (``serverless/report.py``): every
    # tile is wrapped in a placeholder the runtime can draw into (its own
    # output stays inside as the fallback), the "Filters" part gets the
    # dashboard's controls, and the document ends with the one cell that
    # inlines the runtime and the manifest. Off: the document is exactly the
    # notebook it always was.
    embed_runtime: bool = False
    # A text tile's header logo (``logo`` / ``logo_dark``), inlined by the
    # endpoint: ``{index: {"light": data_uri, "dark": data_uri}}``. A logo
    # already given as a data URI on the tile is used as it is.
    logos: dict[str, dict[str, str]] = field(default_factory=dict)
    # The dashboard's own mark (its management-page icon when that is an
    # image, e.g. the nf-core logo), as a data URI: the header bar's.
    dashboard_logo: str | None = None
    # The Depictio wordmark, as a data URI: the "Powered by" mark of the
    # header bar and the footer, as the app header shows it.
    depictio_mark: str | None = None
    # Whether a reader of the file can open the live dashboard: the footer
    # links it only then (a private dashboard's URL is a login page).
    dashboard_public: bool = False
    # Also a PDF: the document carries a typst format beside the HTML one.
    pdf: bool = False
    # Code-mode figures as their author's code (the downloaded notebook, which
    # its reader runs), or through the API (``False``: the server-rendered
    # report, which never executes an author's Python outside the sandbox).
    author_code: bool = True
    # The PDF's colours: ``colour`` (tab colours on headings and in the
    # contents, tinted notes) or ``mono`` (print-friendly, the text colour).
    pdf_style: str = "colour"
    # The report editor's exact preview, not a download (#1457): the document
    # carries no export minute in its provenance (the day, not the minute —
    # the preview cache key must not move with the clock) and Quarto renders
    # it with ``embed-resources: false`` (``report.html`` beside a
    # ``report_files/`` directory), since the editor serves the files itself.
    # A downloaded report keeps the minute and embeds everything.
    preview: bool = False

    @property
    def dashboard_id(self) -> str:
        main = self.tabs[0] if self.tabs else {}
        return str(main.get("dashboard_id") or self.state.context.dashboard_id)

    @property
    def stem(self) -> str:
        return slug(self.title, max_len=60, fallback="dashboard")


@dataclass
class ComponentEntry:
    unit: ComponentUnit
    verdict: Classification
    name: str | None
    # A highlight drawn in place: the highlight's own metadata, while ``unit``
    # holds the figure it shows (its source tab and its own definition).
    highlight: dict[str, Any] | None = None
    # That highlight's own (tab id, index): the tile the report layer and the
    # editor know, while ``unit`` is what is drawn and mounted.
    own_ref: tuple[str, str] | None = None

    @property
    def layer_key(self) -> tuple[str, str]:
        """The (tab id, component id) the report layer keys this tile by."""
        if self.own_ref is not None:
            return self.own_ref
        return (
            str(self.unit.tab.get("dashboard_id") or ""),
            str(self.unit.meta.get("index") or ""),
        )


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_ATX_RE = re.compile(r"^(#{1,6})(?=\s|$)")


def demote_headings(markdown: str, floor: int) -> str:
    """Shift every ATX heading of ``markdown`` so the biggest one is ``floor``.

    Relative ranks are kept (capped at h6); fenced code is left alone. A text
    tile is a block inside a section, and its own headings must nest under it.
    """
    lines = markdown.split("\n")
    fence: str | None = None
    found: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)[0] * 3
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            h = _ATX_RE.match(line)
            if h:
                found.append((i, len(h.group(1))))
    if not found:
        return markdown
    shift = max(0, floor - min(lvl for _, lvl in found))
    if not shift:
        return markdown
    for i, lvl in found:
        lines[i] = "#" * min(6, lvl + shift) + lines[i][lvl:]
    return "\n".join(lines)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _comment(text: str) -> str:
    return _qmd_comment(_sentence(text))


def _author_line(value: Any) -> str:
    """An author's one-line markdown (a caption): kept, defused, on one line."""
    return defuse(one_line(str(value or ""))).strip()


def _fmt_value(value: Any) -> str:
    if isinstance(value, list):
        shown = ", ".join(str(v) for v in value[:6])
        if len(value) > 6:
            shown += f", … ({len(value)} values)"
        return shown
    return str(value)


def _exported_stamp(exported_at: datetime, *, date_only: bool = False) -> str:
    """The export's moment as the report's provenance prints it.

    To the minute for a report a reader downloads. The day alone for a
    preview: the preview cache key is the built document's hash, so the same
    report previewed twice — once at 10:59, once at 11:01 — must build to the
    same bytes, or every minute a new render would be queued.
    """
    if date_only:
        return f"{exported_at:%Y-%m-%d} UTC"
    return f"{exported_at:%Y-%m-%d %H:%M} UTC"


def _without_emptied_sections(
    out: list[tuple[MarkdownUnit | ComponentEntry, str | None]], emptied: set[int]
) -> list[tuple[MarkdownUnit | ComponentEntry, str | None]]:
    """``out`` without the sections the layer took every tile out of.

    ``emptied`` holds the positions of sections that lost a tile to the layer.
    One of them goes when no tile is left before the next section or tab: the
    report never prints a heading over nothing. A section the dashboard itself
    left empty stays as it is.
    """
    kept = []
    for i, item in enumerate(out):
        if i in emptied:
            j = i + 1
            while j < len(out):
                nxt = out[j][0]
                if isinstance(nxt, ComponentEntry) or nxt.kind in ("section", "tab"):
                    break
                j += 1
            if j >= len(out) or not isinstance(out[j][0], ComponentEntry):
                continue
        kept.append(item)
    return kept


class NotebookBuilder:
    def __init__(self, plan: ExportPlan) -> None:
        self.plan = plan
        self.layer = self._resolve_layer()
        # The report's own options (Report settings in the editor); their
        # defaults are the report as it was without them.
        self.settings: ReportSettings = self.layer.settings if self.layer else ReportSettings()
        self._tiles_by_ref: dict[tuple[str, str], ReportTile] = (
            {(t.tab_id, t.component_id): t for t in self.layer.tiles} if self.layer else {}
        )
        self._appendix_tab_ids: frozenset[str] = (
            frozenset(t.tab_id for t in self.layer.tabs if t.placement == "appendix")
            if self.layer
            else frozenset()
        )
        if self.layer is not None and self.layer.tabs:
            self._order_tabs_by_layer()
        self.names = NameAllocator()
        self.dc_by_id: dict[str, DCPlan] = {dc.dc_id: dc for dc in plan.dcs}
        self.df_names: dict[str, str] = {}
        self.final_names: dict[str, str] = {}
        # The final frame without a genome region: what cards (and figures that
        # draw no region column) read, as the server scopes them.
        self.region_free_names: dict[str, str] = {}
        for dc in plan.dcs:
            self.df_names[dc.dc_id] = self.names.claim("df", dc.tag, fallback="table")
            self.names.reserve(f"final_{self.df_names[dc.dc_id][3:]}")
            self.final_names[dc.dc_id] = f"final_{self.df_names[dc.dc_id][3:]}"
            self.region_free_names[dc.dc_id] = f"unregioned_{self.df_names[dc.dc_id][3:]}"
            self.names.reserve(self.region_free_names[dc.dc_id])
        self._entries: list[tuple[MarkdownUnit | ComponentEntry, str | None]] | None = None
        self.tab_anchors, self._anchor_by_tab_name = self._tab_anchors()
        self._section_anchor_seq: list[str] = []
        self._section_i = 0
        self.section_anchors = self._section_anchors()
        self._float_labels: set[str] = set()
        self._hero_cache: tuple[str, str, str | None] | None | bool = False

    def _resolve_layer(self) -> ReportLayer | None:
        """The plan's raw layer as a model, or ``None`` (export without it).

        The layer is author input read from Mongo, not a plan the export built
        itself, so a layer that does not validate — an older export's shape,
        a hand-edited document — falls back to the layer-less report with a
        warning in the preflight, not a failed export.
        """
        raw = self.plan.report_layer
        if not raw:
            return None
        try:
            return ReportLayer.model_validate(raw)
        except Exception:
            self.plan.warnings.append(
                "The dashboard's report layer could not be read and was left out of this export."
            )
            return None

    def _order_tabs_by_layer(self) -> None:
        """Reorder the plan's tabs: body tabs in the layer's order, appendix
        tabs after them (the conclusion goes between the two).

        The main tab stays the first body tab — it carries the layer and the
        cover, and the report opens on it. A tab the layer gives no order
        keeps its dashboard order, after the ordered ones; a tab the layer
        does not mention stays a body tab.
        """
        by_id = {t.tab_id: t for t in self.layer.tabs if self.layer}
        natural_of = {id(t): i for i, t in enumerate(self.plan.tabs)}

        def key(tab: dict[str, Any]) -> tuple[int, int, int, int]:
            cfg = by_id.get(str(tab.get("dashboard_id") or ""))
            natural = natural_of.get(id(tab), 0)
            if cfg is None or tab is self.plan.tabs[0]:
                # Unmentioned tabs (and the main tab) keep the dashboard order.
                return (0, 1, 0, natural)
            placement = 1 if cfg.placement == "appendix" else 0
            if cfg.order is None:
                return (placement, 1, 0, natural)
            return (placement, 0, cfg.order, 0)

        main, rest = self.plan.tabs[0], self.plan.tabs[1:]
        rest.sort(key=key)
        self.plan.tabs = [main, *rest]

    def _layer_tile(self, entry: ComponentEntry) -> ReportTile | None:
        """The layer's placement of one tile, by (tab id, component id)."""
        return self._tiles_by_ref.get(entry.layer_key)

    def _appendix_cut(self) -> int | None:
        """Where the appendix tabs start in the reading order, or ``None``.

        The layer's appendix tabs sit after the conclusion: their parts open
        with the Appendices heading, like the second-and-later tabs of a
        layer-less export, and keep their letter.
        """
        if not self._appendix_tab_ids:
            return None
        for i, (entry, _) in enumerate(self.entries()):
            if (
                isinstance(entry, MarkdownUnit)
                and entry.kind == "tab"
                and entry.dashboard_id in self._appendix_tab_ids
            ):
                return i
        return None

    def _cover_values(self) -> tuple[str, str | None, list[str], str]:
        """The title block's four fields.

        With a layer: the cover where set, the defaults where not — the
        dashboard's title, the project's name, the project's owners, the day
        of the export. Without one, the export's own provenance, as before.
        """
        plan = self.plan
        if self.layer is None:
            return (
                plan.title,
                plan.subtitle or f"Exported from Depictio on {plan.exported_at:%Y-%m-%d}",
                [plan.exported_by] if plan.exported_by else [],
                plan.exported_at.strftime("%Y-%m-%d"),
            )
        cover = self.layer.cover
        project = plan.project or {}
        title = (cover.title if cover and cover.title else plan.title) or "Report"
        subtitle = (
            (cover.subtitle if cover and cover.subtitle else None)
            or str(project.get("name") or "")
            or None
        )
        authors = (cover.authors if cover and cover.authors else None) or _cover_owner_names(
            project
        )
        date = (cover.date if cover and cover.date else plan.exported_at.strftime("%Y-%m-%d")) or ""
        return title, subtitle, authors, date

    def _intro_cell(self) -> Cell | None:
        """The layer's intro as the report's opening prose, or ``None``."""
        if self.layer is None or not self.layer.intro:
            return None
        return md_cell(_layer_prose(self.layer.intro))

    def _conclusion_cell(self) -> Cell | None:
        """The layer's conclusion, after the results, or ``None``."""
        if self.layer is None or not self.layer.conclusion:
            return None
        return md_cell(_layer_prose(self.layer.conclusion))

    def _section_anchors(self) -> dict[str, str]:
        """Each section heading's id, by name: what ``](section:Name)`` lands on.

        A name used by several tabs answers with the first; that is the one a
        persistent section is written under, and the one the reader meets first.
        """
        out: dict[str, str] = {}
        taken: set[str] = set(self.tab_anchors.values())
        for unit in ordered_units(self.plan.tabs):
            if not isinstance(unit, MarkdownUnit) or unit.kind != "section":
                continue
            base = "sec-" + slug(unit.text, max_len=48, fallback="section").replace("_", "-")
            anchor, n = base, 2
            while anchor in taken:
                anchor, n = f"{base}-{n}", n + 1
            taken.add(anchor)
            out.setdefault(unit.text.strip().lower(), anchor)
            self._section_anchor_seq.append(anchor)
        return out

    def _tab_anchors(self) -> tuple[dict[str, str], dict[str, str]]:
        """Each tab's heading id, and the tab names a ``](tab:Name)`` link may use.

        Every tab is a part of the one document, so a link that opened a tab in
        the viewer becomes a jump to that part's heading.
        """
        by_unit: dict[str, str] = {}
        by_name: dict[str, str] = {}
        taken: set[str] = set()
        docs = {str(t.get("dashboard_id") or ""): t for t in self.plan.tabs}
        for unit in ordered_units(self.plan.tabs):
            if not isinstance(unit, MarkdownUnit) or unit.kind != "tab":
                continue
            base = "tab-" + slug(unit.text, max_len=48, fallback="tab").replace("_", "-")
            anchor, n = base, 2
            while anchor in taken:
                anchor, n = f"{base}-{n}", n + 1
            taken.add(anchor)
            key = unit.dashboard_id or unit.text
            by_unit[key] = anchor
            doc = docs.get(unit.dashboard_id or "") or {}
            for name in (unit.text, doc.get("title"), doc.get("main_tab_name")):
                if name:
                    by_name.setdefault(str(name).strip().lower(), anchor)
        return by_unit, by_name

    def _rewrite_tab_links(self, text: str) -> str:
        """``[label](tab:Name)`` → ``[label](#tab-name)``; a link to a tab the
        document does not hold goes, label and all (``drop_orphan_links``)."""
        return drop_orphan_links(self._mark_tab_links(text))

    def _mark_tab_links(self, text: str) -> str:
        def sub(m: re.Match[str]) -> str:
            label, name = m.group(1), m.group(2)
            anchor = self._anchor_by_tab_name.get(name.strip().lower())
            return f"[{label}](#{anchor})" if anchor else ORPHAN

        return _TAB_LINK_RE.sub(sub, text)

    def _rewrite_links(self, text: str) -> str:
        """Every link a text tile can write, as a jump inside the document.

        ``tab:`` to the tab's part; ``section:`` to the section's heading;
        ``params:`` (the app opens its run-parameters dialog there) to the
        header's parameters block when the export has one. A link to a target
        the document does not hold goes, label and all: an orphan label reads
        as stray text (``drop_orphan_links``).
        """
        text = self._mark_tab_links(text)
        has_params = bool(
            ((self.plan.project or {}).get("template_origin") or {}).get("run_provenance")
        )

        def params(m: re.Match[str]) -> str:
            return f"[{m.group(1)}](#{PARAMS_ANCHOR})" if has_params else ORPHAN

        def section(m: re.Match[str]) -> str:
            anchor = self.section_anchors.get(m.group(2).strip().lower())
            return f"[{m.group(1)}](#{anchor})" if anchor else ORPHAN

        text = _PARAMS_LINK_RE.sub(params, text)
        return drop_orphan_links(_SECTION_LINK_RE.sub(section, text))

    def _inline_icons(self, text: str) -> str:
        """``![](icon:prefix:name)`` → the glyph as inline SVG (dropped when unknown)."""

        def sub(m: re.Match[str]) -> str:
            svg = self.plan.icons.get(m.group(1))
            if not svg:
                return ""
            return (
                '<span style="display:inline-flex;vertical-align:-0.125em;'
                f'margin-inline-end:0.2em">{svg}</span>'
            )

        return INLINE_ICON_RE.sub(sub, text)

    def _legend_html(self, column: str) -> str:
        """``{{legend:column}}``: a dot in each value's dashboard colour, then the value."""
        colors = self._category_colors().get(column) or {}
        return " ".join(
            f'<span style="white-space:nowrap"><span style="color:{_esc(c)}">\N{BLACK CIRCLE}'
            f"</span> {_esc(v)}</span>"
            for v, c in colors.items()
        )

    # ------------------------------------------------------------------ names
    def _stage_name(self, k: int, dc_id: str) -> str:
        return f"stage_{k}_{self.df_names[dc_id][3:]}"

    def entries(self) -> list[tuple[MarkdownUnit | ComponentEntry, str | None]]:
        """Reading-order units with their verdict and the name each cell defines."""
        if self._entries is not None:
            return self._entries
        out: list[tuple[MarkdownUnit | ComponentEntry, str | None]] = []
        current_tab: str | None = None
        # Sections the layer took a tile out of, by their place in `out`.
        section_at: int | None = None
        emptied: set[int] = set()
        for unit in ordered_units(self.plan.tabs):
            if isinstance(unit, MarkdownUnit):
                if unit.kind == "tab":
                    current_tab = unit.text
                    section_at = None
                elif unit.kind == "section":
                    section_at = len(out)
                out.append((unit, current_tab))
                continue
            highlight: dict[str, Any] | None = None
            own_ref: tuple[str, str] | None = None
            if unit.meta.get("component_type") == "highlight":
                source = self._highlight_source(unit.meta)
                if source is not None:
                    highlight = unit.meta
                    own_ref = (
                        str(unit.tab.get("dashboard_id") or ""),
                        str(unit.meta.get("index") or ""),
                    )
                    unit = replace(source, section=unit.section, persistent=unit.persistent)
            meta = unit.meta
            verdict = classify(meta)
            if verdict.kind == "code" and not self.plan.author_code:
                # The server never runs an author's Python itself: the report
                # asks Depictio for the figure, which runs that code in the
                # dashboard's own sandbox. The downloaded notebook keeps it.
                verdict = Classification(
                    "api",
                    "a code-mode figure, drawn by Depictio, which runs its author's code "
                    "in the dashboard's sandbox; " + API_REASON,
                    kind="code",
                    output="interactive",
                )
            dc_id = str(meta.get("dc_id") or "")
            if verdict.status == "code" and meta.get("component_type") not in ("text", "highlight"):
                if dc_id not in self.dc_by_id:
                    verdict = Classification(
                        "api",
                        "its data collection has no Delta table in this export "
                        "(e.g. a MultiQC report); re-rendered through the Depictio API",
                        kind=verdict.kind,
                        output="static" if meta.get("component_type") != "figure" else None,
                    )
            name = self._name_for(meta, verdict)
            cfg = self._tiles_by_ref.get(
                own_ref or (str(unit.tab.get("dashboard_id") or ""), str(meta.get("index") or ""))
            )
            if cfg is not None and not cfg.in_report:
                # The layer left the tile out of the report: it goes from the
                # reading order entirely, so the preflight lists what the
                # export will contain, and nothing else does.
                if section_at is not None:
                    emptied.add(section_at)
                continue
            out.append(
                (
                    ComponentEntry(
                        unit=unit, verdict=verdict, name=name, highlight=highlight, own_ref=own_ref
                    ),
                    current_tab,
                )
            )
        self._entries = _without_emptied_sections(out, emptied)
        return self._entries

    def _highlight_source(self, meta: dict[str, Any]) -> ComponentUnit | None:
        """The figure a highlight shows, on the tab it lives on (``highlightTile.ts``).

        The tab by id first, then by name; on it, the component by index, then a
        figure or advanced visualisation of that title. ``None`` when the
        highlight names nothing the family holds: it stays a pointer.
        """
        tabs = self.plan.tabs
        tab_id = str(meta.get("source_dashboard_id") or "").strip()
        name = str(meta.get("source_tab") or "").strip()
        tab = next((t for t in tabs if tab_id and str(t.get("dashboard_id")) == tab_id), None)
        if tab is None and name:
            key = tab_link_key(name)
            tab = next(
                (
                    t
                    for t in tabs
                    if key
                    in {
                        tab_link_key(tab_display_name(t)),
                        tab_link_key(str(t.get("title") or "")),
                    }
                    or str(t.get("dashboard_id")) == name
                ),
                None,
            )
        ref = str(meta.get("source_component") or "").strip()
        if tab is None or not ref:
            return None
        comps = [m for m in tab.get("stored_metadata") or [] if isinstance(m, dict)]
        key = tab_link_key(ref)

        def titled(m: dict[str, Any]) -> bool:
            return bool(m.get("title")) and tab_link_key(str(m["title"])) == key

        found = next((m for m in comps if str(m.get("index")) == ref), None) or next(
            (m for m in comps if m.get("component_type") in _HIGHLIGHTABLE and titled(m)), None
        )
        if found is None or found.get("component_type") not in _HIGHLIGHTABLE:
            return None
        merged = dict(found)
        for k in ("title", "subtitle", "caption"):
            if str(meta.get(k) or "").strip():
                merged[k] = meta[k]
        return ComponentUnit(meta=merged, tab=tab, section=None)

    def _name_for(self, meta: dict[str, Any], verdict: Classification) -> str | None:
        ctype = str(meta.get("component_type") or "")
        hint = meta.get("title") or meta.get("column_name") or meta.get("index")
        if verdict.status == "omitted" or ctype in ("text", "highlight"):
            return None
        if verdict.status == "api":
            return self.names.claim("viz", hint)
        prefix = {"figure": "fig", "card": "card", "table": "table"}.get(ctype, "tile")
        return self.names.claim(prefix, hint)

    # -------------------------------------------------------------- preflight
    def preflight(self, *, render_available: bool = False) -> NotebookPreflight:
        components: list[NotebookPreflightComponent] = []
        counts = {"code": 0, "api": 0, "omitted": 0, "snapshot": 0, "native": 0}
        for entry, tab in self.entries():
            if isinstance(entry, MarkdownUnit):
                continue
            meta = entry.unit.meta
            counts[entry.verdict.status] = counts.get(entry.verdict.status, 0) + 1
            if entry.verdict.output == "snapshot":
                counts["snapshot"] += 1
            if entry.verdict.native:
                counts["native"] += 1
            components.append(
                NotebookPreflightComponent(
                    index=str(meta.get("index") or ""),
                    title=meta.get("title"),
                    component_type=str(meta.get("component_type") or ""),
                    kind=entry.verdict.kind,
                    status=entry.verdict.status,  # type: ignore[arg-type]
                    output=entry.verdict.output,
                    reason=entry.verdict.reason,
                    name=entry.name,
                    tab=tab,
                    section=entry.unit.section,
                )
            )
        return NotebookPreflight(
            components=components,
            dcs=[
                NotebookPreflightDC(dc_id=dc.dc_id, tag=dc.tag, rows=dc.initial_rows)
                for dc in self.plan.dcs
            ],
            stages=[
                NotebookPreflightStage(index=s.index, label=s.label, rows_by_dc=s.rows_by_dc)
                for s in self.plan.stages
            ],
            warnings=list(self.plan.warnings),
            render_available=render_available,
            counts={**counts, "stages": len(self.plan.stages), "dcs": len(self.plan.dcs)},
        )

    # ------------------------------------------------------------------ build
    def build(self) -> str:
        cells: list[Cell] = []
        if self.plan.pdf:
            # The PDF's page, first in the body: a raw typst block, which only
            # the typst writer reads. Not a format option: it holds the marks
            # as text, too long for the command line Quarto passes those on.
            cells.append(md_cell(f"````{{=typst}}\n{self._typst_preamble()}\n````"))
        cells.append(self._imports_cell())
        cells.append(self._theme_cell())
        cells.append(self._connection_cell())
        cells.append(self._metric_card_cell())
        cells.append(md_cell(self._header()))
        # The layer's intro: the report's opening prose, before any results,
        # inside its part marker (always present, empty without prose).
        cells.append(md_cell(part_div("intro")))
        intro = self._intro_cell()
        if intro is not None:
            cells.append(intro)
        cells.append(md_cell(PART_FENCE))
        cells.append(self._state_cell())
        cells.append(self._grouping_cell())
        cells.extend(self._data_cells())
        cells.extend(self._funnel_cells())
        cells.extend(self._group_cells())
        cells.extend(self._panel_cells())
        cells.extend(self._tile_cells())
        if self.plan.embed_runtime:
            cells.append(self._runtime_cell())
        # The layer's conclusion, last of the narrative; the appendix parts
        # follow it, then the provenance, as in a paper. Both carry their part
        # markers, always present (empty when the layer sets nothing).
        cells.append(md_cell(part_div("conclusion")))
        conclusion = self._conclusion_cell()
        if conclusion is not None:
            cells.append(conclusion)
        cells.append(md_cell(PART_FENCE))
        cells.append(md_cell(part_div("appendix")))
        cells.extend(self._appendix_cells())
        cells.append(md_cell(PART_FENCE))
        methods_md = self._methods()[0] if self.settings.methods else ""
        if methods_md:
            cells.append(md_cell(methods_md))
        if self.plan.pdf:
            params = self._pdf_parameters()
            if params:
                cells.append(md_cell(params))
        return render_qmd(cells, front_matter=self.front_matter().to_yaml())

    def _pdf_parameters(self) -> str:
        """The run's parameters as the PDF's last part: the target of every
        ``[Settings](params:…)`` link, which the page opens as a fold of its
        header, a page has no fold for."""
        origin = (self.plan.project or {}).get("template_origin") or {}
        entries = origin.get("run_provenance") if isinstance(origin, dict) else None
        if not entries:
            return ""
        from depictio.notebook.typst import table as typst_table

        rows = sorted(
            (e for e in entries if isinstance(e, dict)),
            key=lambda e: not bool(e.get("highlight")),
        )
        df = pl.DataFrame(
            {
                "Group": [str(e.get("group") or "") for e in rows],
                "Parameter": [str(e.get("key") or "") for e in rows],
                "Value": ["null" if e.get("value") is None else str(e.get("value")) for e in rows],
            }
        )
        return (
            ':::: {.content-visible when-format="typst"}\n'
            f"## Run parameters {{#{PARAMS_ANCHOR}}}\n\n"
            f"{typst_table(df, rows=60)}\n::::"
        )

    # ------------------------------------------------------------ the chrome
    def _methods(self) -> tuple[str, list[dict[str, Any]]]:
        """The "Methods and citations" part (heading included) and its references."""
        if getattr(self, "_methods_cache", None) is not None:
            return self._methods_cache
        uses_multiqc = any(
            m.get("component_type") == "multiqc"
            for t in self.plan.tabs
            for m in t.get("stored_metadata") or []
            if isinstance(m, dict)
        )
        body, refs = methods(
            project=self.plan.project,
            depictio_version=self.plan.depictio_version,
            uses_multiqc=uses_multiqc,
            collections=[(dc.tag, dc.initial_rows) for dc in self.plan.dcs],
        )
        if body:
            # A heading of its own, not one of the folding parts: the footer
            # after it must stay in view whatever the reader folded.
            accent = self._accent()
            body = (
                f"{'#' * RESULTS_LEVEL} {self._icon_html(METHODS_ICON, accent)}"
                f'<span class="dpx-hc" style="--dpx-hc:{accent}">{METHODS_HEADING}</span> '
                "{#methods}\n\n" + body
            )
        self._methods_cache = (body, refs)
        return self._methods_cache

    def _heading_marks(self) -> tuple[dict[str, str], dict[str, str]]:
        """Each heading label with its colour and its icon's SVG (as the HTML
        draws them): what the PDF draws its headings with."""
        icons = self.plan.icons
        colors: dict[str, str] = {k: self._accent() for k in ("filters", "results", "methods")}
        marks: dict[str, str] = {
            "filters": icons.get(FILTERS_ICON, ""),
            "results": icons.get(RESULTS_ICON, ""),
            "methods": icons.get(METHODS_ICON, ""),
        }
        seq = iter(self._section_anchor_seq)
        for unit in ordered_units(self.plan.tabs):
            if not isinstance(unit, MarkdownUnit):
                continue
            if unit.kind == "tab":
                brand = self.plan.tab_brands.get(unit.dashboard_id or "") or self.plan.brand or {}
                accent = palette_hex(unit.color, brand.get("primary") or "")
                anchor = self.tab_anchors.get(unit.dashboard_id or unit.text)
            else:
                accent = palette_hex(unit.color, "")
                anchor = next(seq, None)
            if not anchor:
                continue
            if accent:
                colors[anchor] = accent
            if unit.icon and icons.get(unit.icon):
                marks[anchor] = icons[unit.icon]
        return colors, {k: v for k, v in marks.items() if v}

    def _heading_colors(self) -> dict[str, str]:
        return self._heading_marks()[0]

    def _cover_fields(self) -> list[tuple[str, str]]:
        """The cover's record, from the export's own data only."""
        plan = self.plan
        project = plan.project or {}
        exported = _exported_stamp(plan.exported_at, date_only=plan.preview)
        if plan.exported_by:
            exported += f" by {plan.exported_by}"
        if plan.instance:
            exported += f" from {plan.instance}"
        pipelines = []
        for wf in project.get("workflows") or []:
            if not isinstance(wf, dict) or not wf.get("name"):
                continue
            catalog = wf.get("catalog") if isinstance(wf.get("catalog"), dict) else {}
            engine = wf.get("engine") if isinstance(wf.get("engine"), dict) else {}
            name = f"{catalog['name']}/{wf['name']}" if catalog.get("name") else str(wf["name"])
            if wf.get("version"):
                name += f" {wf['version']}"
            if engine.get("name"):
                name += f" ({engine['name']})"
            pipelines.append(name)
        origin = (
            project.get("template_origin")
            if isinstance(project.get("template_origin"), dict)
            else {}
        )
        tabs = [
            u.text
            for u in ordered_units(plan.tabs)
            if isinstance(u, MarkdownUnit) and u.kind == "tab"
        ]
        tab_line = ", ".join(tabs[:8]) + (f" and {len(tabs) - 8} more" if len(tabs) > 8 else "")
        rows = [r for dc in plan.dcs if (r := dc.initial_rows) is not None]
        data = f"{len(plan.dcs)} data collection" + ("" if len(plan.dcs) == 1 else "s")
        if rows:
            data += f", {sum(rows):,} rows"
        state = (
            "; ".join(f"{s.label}: {self._filter_value_text(s)}" for s in plan.stages)
            or "No filter active: every tile reads the whole data"
        )
        return [
            ("Project", str(project.get("name") or "")),
            ("Pipeline", ", ".join(pipelines)),
            ("Template", str(origin.get("template_id") or "")),
            ("Tabs", f"{len(tabs)}: {tab_line}" if tabs else ""),
            ("Data read", data if plan.dcs else ""),
            ("Exported state", state),
            ("Exported", exported),
            ("Depictio", plan.depictio_version or ""),
            ("Live dashboard", self._dashboard_url() if plan.dashboard_public else ""),
        ]

    def _cover_statement(self) -> str:
        plan = self.plan
        tabs = [
            u for u in ordered_units(plan.tabs) if isinstance(u, MarkdownUnit) and u.kind == "tab"
        ]
        out = f"A static report of the interactive Depictio dashboard “{plan.title}”"
        out += f", live at {self._dashboard_url()}." if plan.dashboard_public else "."
        if len(tabs) > 1:
            out += (
                f" Its {tabs[0].text.lower()} is the report; each other tab follows as an appendix."
            )
        return out

    def _typst_preamble(self) -> str:
        plan = self.plan
        hero = self.hero
        colors, icons = self._heading_marks()
        title, subtitle, _authors, _date = self._cover_values()
        return typst_preamble(
            title=title,
            subtitle=subtitle,
            primary=self._accent(),
            style=plan.pdf_style,
            dashboard_mark=plan.dashboard_logo,
            title_logo=hero[1] if hero else None,
            depictio_mark=plan.depictio_mark,
            provenance=self._cover_fields(),
            heading_colors=colors,
            heading_icons=icons,
            statement=self._cover_statement(),
            contents=self.settings.toc,
            landscape=self.settings.landscape,
            numbering=self.settings.numbering,
        )

    def _dashboard_url(self) -> str:
        return f"{self.plan.api_url.rstrip('/')}/dashboard/{self.plan.dashboard_id}"

    def _accent(self) -> str:
        return palette_hex((self.plan.brand or {}).get("primary"), "#228be6")

    def _settings_marker(self) -> str:
        """The settings the report's runtime reads in the page: where an
        advanced viz draws its controls (``ReportRuntime``)."""
        return (
            f'<div id="{SETTINGS_MARKER_ID}" hidden '
            f'data-viz-controls="{_esc(self.settings.viz_controls, quote=True)}"></div>'
        )

    def _appbar(self) -> str:
        """The header bar: the dashboard's mark and "Powered by" Depictio.

        The name stays off the bar whenever the title block under it says it
        already (as text, or as the dashboard's logo): one place per name. No
        tab breadcrumb either: the first part's own heading follows."""
        plan = self.plan
        main = plan.tabs[0] if plan.tabs else {}
        accent = palette_hex(str(main.get("icon_color") or "") or None, self._accent())
        h1 = plan.title
        bar_name = None if self.hero is not None or h1.strip() == plan.title.strip() else h1
        return appbar_html(
            title=bar_name,
            logo=plan.dashboard_logo,
            logo_dark=None,
            accent=accent,
            has_mark=bool(plan.depictio_mark),
            # Paper has a dark theme, and with it Quarto's scheme toggle.
            scheme_toggle=self.paper,
        )

    @property
    def hero(self) -> tuple[str, str, str | None] | None:
        """The first tab's header tile when it carries a logo: ``(index, light, dark)``.

        That logo names the dashboard (the app draws it in place of the tile's
        title, at the top of the first tab), so in the report it is the title
        block: the H1 shows it, and the tile does not draw it again."""
        if self._hero_cache is not False:
            return self._hero_cache  # type: ignore[return-value]
        found: tuple[str, str, str | None] | None = None
        seen_tab = False
        for unit in ordered_units(self.plan.tabs):
            if isinstance(unit, MarkdownUnit):
                if unit.kind == "tab" and seen_tab:
                    break
                if unit.kind == "section":
                    break
                seen_tab = seen_tab or unit.kind == "tab"
                continue
            meta = unit.meta
            if meta.get("component_type") != "text" or unit.section:
                break
            # Only the tab's first tile is its header: a logo further down
            # illustrates something else.
            light, dark = self._text_logo_uris(meta)
            if light:
                found = (str(meta.get("index") or ""), light, dark)
            break
        self._hero_cache = found
        return found

    def _footer(self) -> str:
        """The report's foot: provenance, the way back to the source."""
        plan = self.plan
        project = plan.project or {}
        licence = next(
            (str(project[k]) for k in ("license", "licence", "data_license") if project.get(k)),
            None,
        )
        citation = next(
            (str(project[k]) for k in ("citation", "how_to_cite") if project.get(k)), None
        )
        html = footer_html(
            exported_at=_exported_stamp(plan.exported_at, date_only=plan.preview),
            exported_by=plan.exported_by,
            instance=plan.instance,
            version=plan.depictio_version,
            dashboard_url=self._dashboard_url() if plan.dashboard_public else None,
            project=str(project.get("name") or "") or None,
            licence=licence,
            citation=citation,
            data_url=str(project.get("data_management_platform_project_url") or "") or None,
            has_mark=bool(plan.depictio_mark),
        )
        return html

    @property
    def paper(self) -> bool:
        return self.plan.theme != "classic"

    def _primary(self) -> tuple[str, str]:
        """The instance primary as (shade 6, shade 7): the accent and its ink."""
        return resolve_primary((self.plan.brand or {}).get("primary"))

    def front_matter(self) -> QuartoFrontMatter:
        plan = self.plan
        brand = plan.brand or {}
        title, subtitle, authors, date = self._cover_values()
        return QuartoFrontMatter(
            title=title,
            subtitle=subtitle,
            author=", ".join(authors) or None,
            date=date,
            # A downloaded report inlines everything (it must still work
            # months later, off the network); the preview does not — its
            # files are served beside it (``report_files/``, the editor's
            # iframe), which keeps the render and the frame light.
            embed_resources=not plan.preview,
            toc=self.settings.toc,
            code_tools=self.settings.code,
            papersize="us-letter" if self.settings.paper == "letter" else "a4",
            # The dashboard's own mark on the browser tab when it has one (the
            # nf-core apple), the app's otherwise.
            favicon_data_uri=plan.dashboard_logo or plan.favicon_data_uri,
            before_body=self._appbar() + self._settings_marker(),
            after_body=self._footer() + ("" if self.settings.numbering else UNNUMBER_SCRIPT),
            pdf=self.plan.pdf,
            extra=(
                {"references": refs}
                if self.settings.methods and (refs := self._methods()[1])
                else {}
            ),
            brand=(
                paper_brand(
                    primary=self._primary()[0],
                    font_family=brand.get("font_family"),
                    headings_font_family=brand.get("headings_font_family"),
                    rules=brand_rules("light"),
                    extra_defaults=BRAND_DEFAULTS,
                )
                if self.paper
                else None
            ),
            # The reader's scheme: Paper's dark page when they prefer it.
            brand_dark=(
                paper_brand_dark(
                    primary=self._primary()[0],
                    font_family=brand.get("font_family"),
                    headings_font_family=brand.get("headings_font_family"),
                    rules=brand_rules("dark"),
                    extra_defaults=BRAND_DEFAULTS,
                )
                if self.paper
                else None
            ),
        )

    def _imports_cell(self) -> Cell:
        return Cell(
            "import datetime\n"
            "\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import plotly.express as px\n"
            "import plotly.graph_objects as go\n"
            "import polars as pl\n"
            "from IPython.display import HTML\n"
            "from depictio.notebook.qmd_safe import esc as html_text\n"
            "from depictio.notebook.qmd_safe import inert_outputs\n"
            "from depictio.notebook import (\n"
            "    DepictioClient,\n"
            "    fill_text,\n"
            "    funnel_figure,\n"
            "    funnel_rest,\n"
            "    funnel_stage,\n"
            "    StaticCard,\n"
            "    init_tables,\n"
            "    set_page_orientation,\n"
            "    set_static_width,\n"
            "    show_table,\n"
            "    static_card_row,\n"
            "    static_figures,\n"
            "    use_document_renderer,\n"
            "    use_theme,\n"
            ")\n"
            "from polars import col, lit\n"
            "\n"
            + _comment(
                "No output reads as Quarto markup: a title or a value that spells a "
                "shortcode is printed as text"
            )
            # Assigned to a throwaway: the call returns a bool, and a bare
            # expression at the end of a cell is that cell's output — the report
            # would open on the word "True".
            + "\n_ = inert_outputs()\n"
            + _comment(
                "One copy of plotly.js for the whole document, and no MathJax request "
                "per figure. Executed as a notebook, every figure otherwise embeds its "
                "own ~5 MB copy of the library, which is what a self-contained HTML "
                "export is made of: 35 figures came to 170 MB, of which 2.5 MB was data"
            )
            + "\n_ = use_document_renderer()\n"
            + _comment(
                "Tables as sortable, searchable, paginated tables (itables, with DataTables "
                "inlined once so the report stays self-contained); plain HTML tables with "
                "every row when itables is not installed"
            )
            + "\n_ = init_tables()"
        )

    def _theme_cell(self) -> Cell:
        """The report's look, for what the front matter's theme cannot reach.

        Quarto styles the page; the figures are Plotly's and the font is a
        file. ``use_theme`` registers Paper as the Plotly template every
        figure here is drawn in (and lays it over the ones Depictio renders,
        as the app does), and prints the ``<style>`` that embeds Inter, so
        the report needs no font request.
        """
        if not self.paper:
            return Cell(
                "#| output: asis\n"
                + _comment("The classic look: Plotly's own figures, the system font")
                + '\nprint(use_theme("classic"))'
            )
        brand = self.plan.brand or {}
        kwargs = f"primary={self._primary()[0]!r}"
        if brand.get("font_family"):
            kwargs += f", font_family={brand['font_family']!r}"
        return Cell(
            "#| output: asis\n"
            + _comment(
                "Depictio's Paper look, with this instance's primary colour: every figure "
                'below is drawn in it, and Inter is embedded. use_theme("classic") for '
                "Plotly's own"
            )
            + f'\nprint(use_theme("paper", {kwargs}))'
        )

    def _connection_cell(self) -> Cell:
        return Cell(
            _comment(
                "Reads DEPICTIO_API_URL and DEPICTIO_API_TOKEN, or ~/.depictio/CLI.yaml. "
                "Offline: set DEPICTIO_DATA_DIR to a folder of <dc_id>.parquet files"
            )
            + "\nclient = DepictioClient()\n"
            + f"DASHBOARD_ID = {self.plan.dashboard_id!r}"
        )

    def _metric_card_cell(self) -> Cell:
        # A dashboard card is a number with a label; the honest notebook
        # equivalent of that is a bare print, but a report reads better as a
        # tile. IPython's HTML object is what the Jupyter kernel Quarto runs
        # displays as markup, and it carries `_repr_html_` for card_row().
        body = '''def metric_card(title, value):
    """The card look, as inline HTML: a label over a big number."""
    if value is None:
        text = "\N{EM DASH}"
    elif isinstance(value, bool):
        text = str(value)
    elif isinstance(value, float):
        text = f"{value:,.2f}" if not value.is_integer() else f"{value:,.0f}"
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        text = str(value)
    if static_figures():
        # A page with no browser (the PDF): the card as the PDF draws one.
        return StaticCard(title, text)
    return HTML(
        f'<div class="dpx-card" style="display:inline-block;min-width:11rem;margin:0 0.5rem 0.5rem 0;'
        f'padding:0.85rem 1.1rem;border:1px solid #e3e3e8;border-radius:12px;'
        f'font-family:inherit;background:#fafafa">'
        f'<div class="dpx-card-title" style="font-size:0.78rem;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:0.02em;margin-bottom:0.3rem">{html_text(title)}</div>'
        f'<div class="dpx-card-value" style="font-size:1.65rem;font-weight:650;color:#111827">{html_text(text)}</div>'
        f'</div>'
    )


def card_row(cards):
    """Several cards on one row, as an even CSS grid.

    The column count is fixed by how many cards there are rather than left to
    `auto-fit`, which fits as many as the page happens to be wide enough for
    and strands the remainder: up to four cards share one line, as the
    dashboard's strip draws them; more run four (or three) to a line.
    `_repr_html_()` is the standard rich-display hook (IPython's HTML and Depictio's
    own components both implement it): calling it directly gets the actual
    card look, the same HTML each object would show if displayed bare —
    `.html` on a Depictio component is a different thing, an embeddable tile.
    """
    if static_figures():
        # The PDF: a strip of cards, each with its icon, value and numbers.
        from IPython.display import Markdown

        return Markdown(static_card_row(cards, mono=__MONO__))
    n = len(cards)
    cols = n if n <= 4 else (4 if n % 4 == 0 else 3)
    # One slot per card, in the row's order: the report editor's preview
    # takes each card's thumbnail from its own slot.
    items = "".join(f'<div class="dpx-card-slot">{c._repr_html_()}</div>' for c in cards)
    return HTML(
        f'<div class="dpx-cards" style="display:grid;grid-template-columns:'
        f'repeat({cols},minmax(0,1fr));gap:0.75rem;margin:0 0 0.5rem">{items}</div>'
    )'''
        plan = getattr(self, "plan", None)
        body = body.replace("__MONO__", repr(getattr(plan, "pdf_style", "") == "mono"))
        return Cell(body)

    def _header(self) -> str:
        # The instance's primary, as the one variable the chrome's brand-aware
        # rules read. A separate block rather than a placeholder inside
        # NOTEBOOK_CHROME: that constant is full of CSS and JS braces, and
        # nothing there is worth making it a format string over.
        accent = palette_hex((self.plan.brand or {}).get("primary"), "#228be6")
        root = f"--dpx-primary: {accent};"
        chrome = NOTEBOOK_CHROME
        if self.paper:
            brand = self.plan.brand or {}
            root += f" --dpx-accent-fg: {self._primary()[1]};"
            if brand.get("font_family"):
                root += f" --dpx-font: {_css_value(brand['font_family'])};"
            if brand.get("headings_font_family"):
                root += f" --dpx-headings-font: {_css_value(brand['headings_font_family'])};"
            chrome += "\n" + PAPER_CHROME
        return (
            f"<style>:root {{ {root} }}</style>\n"
            + chrome
            + "\n"
            + REPORT_CSS
            + (DARK_CSS if self.paper else "")
            + TOC_SCOPE_JS
            + CHROME_CSS
            + CHROME_JS
            + mark_css(self.plan.depictio_mark)
            + (title_logo_css(self.hero[1], self.hero[2]) if self.hero else "")
            + "\n\n"
            + self._state_line()
            + header_markdown(
                title=self.plan.title,
                subtitle=self.plan.subtitle,
                project=self.plan.project,
                exported_by=self.plan.exported_by,
                exported_at=self.plan.exported_at,
                date_only=self.plan.preview,
                instance=self.plan.instance,
                api_url=self.plan.api_url,
                dashboard_id=self.plan.dashboard_id,
                stem=self.plan.stem,
                state_version=self.plan.state.version,
                warnings=self.plan.warnings,
                params_icon=self.plan.icons.get(PROVENANCE_ICON, ""),
                details_rows=self._export_details() if self.settings.export_details else None,
                details_icon=self.plan.icons.get(EXPORT_DETAILS_ICON, ""),
                run_icon=self.plan.icons.get(RUN_ICON, ""),
                how_to_run=self.settings.how_to_run,
            )
        )

    def _state_line(self) -> str:
        """ "Exported state": the filters the export was taken under, one line,
        when there are any (the full view is the Filters part)."""
        stages = self.plan.stages
        if not stages:
            return ""
        bits = [f"<b>{_esc(s.label)}</b> {_esc(self._filter_value_text(s))}" for s in stages]
        pins = self.plan.state.pins
        pinned = pins.as_of_version or pins.definition_version
        tail = f" · as of dashboard version {_esc(str(pinned))}" if pinned else ""
        return (
            '<p class="dpx-state-line">Exported state: '
            + " · ".join(bits)
            + tail
            + ' · <a href="#filters">filters</a></p>\n\n'
        )

    def _export_details(self) -> list[tuple[str, str]]:
        """Where this file came from: the server, the project, the dashboard.

        The header's table answers "what am I looking at"; this answers "what
        produced it" — the ids a reader needs to find the same objects again
        through the API, and the versions they need when the file and the live
        dashboard disagree.
        """
        plan = self.plan
        project = plan.project or {}
        server = plan.instance or plan.api_url
        if plan.depictio_version:
            server = f"{server} · Depictio {plan.depictio_version}"
        tabs = plan.tabs or []
        dashboard = f"{plan.title}\n{plan.dashboard_id}"
        if len(tabs) > 1:
            dashboard += f"\n{len(tabs)} tabs"
        collections = "\n".join(
            f"{dc.tag} · {dc.dc_id}"
            + (f" · {dc.initial_rows:,} rows" if dc.initial_rows is not None else "")
            for dc in plan.dcs
        )
        state = f"v{plan.state.version} · {len(plan.stages)} filter"
        state += "" if len(plan.stages) == 1 else "s"
        pins = plan.state.pins
        if pins.as_of_version or pins.definition_version:
            state += f"\nas of dashboard version {pins.as_of_version or pins.definition_version}"
        elif pins.data_versions:
            state += f"\n{len(pins.data_versions)} collection(s) pinned to a past commit"
        return [
            ("Server", server),
            ("Project", "\n".join(x for x in (project.get("name"), project.get("_id")) if x)),
            ("Dashboard", dashboard),
            ("Data collections", collections),
            ("Analysis state", state),
            ("Notebook", "Quarto document (.qmd)"),
            ("Exported", _exported_stamp(plan.exported_at, date_only=plan.preview)),
        ]

    def _state_cell(self) -> Cell:
        state = self.plan.state.model_dump(mode="json", exclude_none=True)
        literal = pprint.pformat(state, width=88, sort_dicts=False)
        # Tagged `parameters`: `quarto render -P depictio_state:'{...}'` (Papermill's
        # convention, which Quarto's Jupyter engine follows) injects a cell after
        # this one, and everything below reads the state from there.
        return Cell(
            "#| tags: [parameters]\n"
            + _comment(
                "The analysis state as exported: filters, funnel order, groups, pins. Every "
                "tile below reads it when the document runs, the funnel stages computed in "
                "code and the tiles Depictio renders alike: edit it, or render with "
                "`quarto render -P depictio_state:...`, to change what they show"
            )
            + f"\ndepictio_state = {literal}"
        )

    def _grouping_cell(self) -> Cell:
        return Cell(
            _comment(
                "What a code-mode figure is executed with on the dashboard: keyword arguments "
                "it spreads into px (`**depictio_group_kwargs`), keys it adds to a group_by, "
                "and the dashboard's colour per category value. "
                + (
                    "The exported state colours by "
                    + (
                        "the selection groups"
                        if self._grouping()[0] == "groups"
                        else f"the column {self._grouping()[1]!r}"
                    )
                    + ", so a figure that spreads them is coloured the same way; each figure "
                    "cell passes the values for its own data collection"
                    if self._grouping()[0] != "none"
                    else "The exported state is ungrouped"
                )
            )
            + "\ndepictio_group_kwargs = "
            + pprint.pformat(self._group_kwargs(None)[0], width=88, sort_dicts=False)
            + "\ndepictio_group_by = "
            + repr(self._group_kwargs(None)[1])
            + "\ndepictio_category_colors = "
            + pprint.pformat(self._category_colors(), width=88, sort_dicts=True)
        )

    # -------------------------------------------------------------- grouping
    def _grouping(self) -> tuple[str, str | None]:
        """``("groups" | "column" | "none", column)``: what the exported state colours by."""
        state = self.plan.state
        if state.color_by.kind == "groups" and any(g.values for g in state.groups):
            return "groups", None
        if state.color_by.kind == "column" and state.color_by.column_name:
            return "column", state.color_by.column_name
        return "none", None

    def _group_defs(self) -> list[dict[str, Any]]:
        from depictio.api.v1.services.figure.groups import sanitize_group_defs

        return sanitize_group_defs(
            [
                {
                    "name": g.name,
                    "column_name": g.column_name,
                    "values": list(g.values),
                    "color": g.color,
                    "dc_id": g.dc_id,
                }
                for g in self.plan.state.groups
                if g.values
            ]
        )

    def _group_kwargs(self, dc: DCPlan | None) -> tuple[dict[str, Any], list[str]]:
        """``(depictio_group_kwargs, depictio_group_by)`` as the server hands them over.

        Mirrors the code-mode handover in ``build_figure_preview``
        (``_grouped_kwargs({})`` / ``_column_kwargs({})`` over
        ``services/figure/groups.py``): empty when ungrouped, or when ``dc``
        does not carry the column the colouring needs, which is what the
        server hands a figure whose frame lacks it.
        """
        from depictio.api.v1.services.figure.groups import (
            GROUP_COLUMN,
            MAX_FACET_CATEGORIES,
            apply_column_coloring_kwargs,
            apply_facet_kwargs,
            apply_group_coloring_kwargs,
        )

        kind, column = self._grouping()
        state = self.plan.state
        facet = state.display_mode == "facet"
        if kind == "groups":
            defs = self._group_defs()
            if dc is not None and dc.columns is not None:
                defs = [g for g in defs if g["column_name"] in dc.columns]
            if not defs:
                return {}, []
            kwargs = apply_group_coloring_kwargs({}, defs, include_other=state.show_other)
            n = len(defs) + (1 if state.show_other else 0)
            if facet and n <= MAX_FACET_CATEGORIES:
                kwargs = apply_facet_kwargs(kwargs, GROUP_COLUMN)
            return kwargs, [GROUP_COLUMN]
        if kind == "column" and column:
            if dc is not None and dc.columns is not None and column not in dc.columns:
                return {}, []
            color_map = self._category_colors().get(column) or {}
            kwargs = apply_column_coloring_kwargs({}, column, color_map)
            if facet and color_map and len(color_map) <= MAX_FACET_CATEGORIES:
                kwargs = apply_facet_kwargs(kwargs, column)
            return kwargs, [column]
        return {}, []

    def _group_annotation_lines(self, dc: DCPlan, target: str) -> list[str]:
        """Source for the server's ``group_annotation_expr`` on ``target``.

        First matching group wins, rows in none are ``Other`` (dropped when the
        state hides it); membership uses the same categorical predicate as the
        filters. A group captured on another collection is only reproduced
        where this one carries its column: the server's cross-collection
        translation of group values is not.
        """
        from depictio.api.v1.services.figure.groups import GROUP_COLUMN, OTHER_LABEL

        branches = []
        for g in self._group_defs():
            if dc.columns is not None and g["column_name"] not in dc.columns:
                continue
            src = emit_predicate(
                "MultiSelect", g["column_name"], g["values"], dc.dtype(g["column_name"])
            )
            if src is None or src.prelude:
                continue
            branches.append((src.expr, g["name"]))
        if not branches:
            return []
        chain = "pl"
        for expr, name in branches:
            chain += f".when({expr}).then(pl.lit({name!r}))"
        lines = [
            f"{target} = {target}.with_columns(",
            f"    {chain}.otherwise(pl.lit({OTHER_LABEL!r})).alias({GROUP_COLUMN!r})",
            ")",
        ]
        if not self.plan.state.show_other:
            lines.append(f"{target} = {target}.filter(pl.col({GROUP_COLUMN!r}) != {OTHER_LABEL!r})")
        return lines

    def _category_colors(self) -> dict[str, dict[str, str]]:
        """``{column: {value: colour}}`` across the family, the main tab first and
        each tab laid over it — what ``effective_category_colors`` hands a code
        figure on the server, family-wide since the document has one namespace."""
        merged: dict[str, dict[str, str]] = {}
        for tab in self.plan.tabs:
            layer = tab.get("category_colors")
            if not isinstance(layer, dict):
                continue
            for column, values in layer.items():
                if isinstance(values, dict) and values:
                    merged.setdefault(str(column), {}).update(
                        {str(k): str(v) for k, v in values.items()}
                    )
        return merged

    def _data_cells(self) -> list[Cell]:
        cells = []
        for dc in self.plan.dcs:
            shape = ""
            if dc.initial_rows is not None:
                shape = f": {dc.initial_rows:,} rows"
                if dc.n_cols is not None:
                    shape += f", {dc.n_cols} columns"
                shape += " at export time"
            if dc.version is not None:
                shape += f", read at Delta commit {dc.version} as the exported version pins it"
            pin = f", version={dc.version}" if dc.version is not None else ""
            cells.append(
                Cell(
                    _comment(f'Data collection "{dc.tag}"{shape}')
                    + f"\n{self.df_names[dc.dc_id]} = client.data({dc.dc_id!r}{pin})"
                )
            )
        return cells

    # ---------------------------------------------------------------- funnel
    @staticmethod
    def _filter_value_text(stage: StagePlan) -> str:
        """A filter's value the way the panel's summary writes it.

        ``activeFilters.ts``: a range as ``low – high``, up to two selected
        values inline, and anything longer as a count — the panel does not put
        a wall of values in front of the reader, and neither should the export.
        """
        value = stage.value
        kind = str(stage.interactive_component_type or "")

        def scalar(v: Any) -> str:
            if isinstance(v, bool):
                return "on" if v else "off"
            return str(v)

        def truncate(text: str) -> str:
            return text if len(text) <= _MAX_LABEL_CHARS else text[: _MAX_LABEL_CHARS - 1] + "…"

        if isinstance(value, (list, tuple)):
            present = [v for v in value if v is not None and v != ""]
            if kind in _RANGE_TYPES and len(present) == 2:
                return truncate(f"{scalar(present[0])} \N{EN DASH} {scalar(present[1])}")
            if not present:
                return ""
            if len(present) > _MAX_INLINE_VALUES:
                return f"{len(present)} selected"
            return truncate(", ".join(scalar(v) for v in present))
        if value is None or value == "":
            return ""
        return truncate(scalar(value))

    def _filters_summary_html(self, stages: list[StagePlan]) -> str:
        """The panel's own summary of what is filtered, as static HTML.

        Same shape as ``ActiveFilterSummary``: a count, then one line per
        filter — the control's icon in its own colour, its title, its value
        dimmed. A list rather than pills, for the same reason the panel uses
        one: filter values are long and pills wrap into a ragged block.
        """
        rows = []
        for stage in stages:
            accent = palette_hex(stage.color, "#228be6")
            icon = self._icon_html(stage.icon, accent)
            value = self._filter_value_text(stage)
            rows.append(
                '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;min-width:0">'
                + (icon or "")
                # The weight from the stylesheet: Quarto 1.9 turns an inline
                # numeric `font-weight` into a typst string the PDF refuses.
                + f'<span class="dpx-filter-name" style="font-size:0.8rem">{_esc(stage.label)}</span>'
                + (
                    f'<span style="font-size:0.8rem;color:#868e96;overflow-wrap:anywhere">'
                    f"{_esc(value)}</span>"
                    if value
                    else ""
                )
                + "</div>"
            )
        count = f"{len(stages)} filter{'' if len(stages) == 1 else 's'} active"
        return (
            f'<div style="font-size:0.78rem;color:#868e96;margin-bottom:2px">{count}</div>'
            + "".join(rows)
        )

    @staticmethod
    def _stage_title(position: int, stage: StagePlan) -> str:
        """The filter's own name, the one the panel shows next to its icon."""
        return stage.label or stage.column or f"Filter {position}"

    def _funnel_figure_cell(self, stages: list[StagePlan]) -> Cell:
        """The dashboard's own funnel view, rebuilt as a Plotly figure.

        Same trace as ``FunnelView``: one horizontal funnel per data
        collection, labelled with the row count and its share of the unfiltered
        table, stages top to bottom in the order they were applied. Emitted as
        code rather than a picture so the reader can reorder the stages and see
        the intermediate counts move, which is the whole point of the funnel.

        One collection at a time, chosen from a dropdown, which is the one
        thing the app does not need to do: it groups every collection into a
        single band, and on one shared x-axis a table of 48 rows next to one of
        6,900 is a sliver with no room for its label. Showing them one at a
        time keeps the app's own proportions and every value readable, without
        turning the section into a wall of small charts.

        Each stage names its filter *and* its value down the left, so the
        funnel is also the reminder of what was filtered.
        """
        labels = ["0. Unfiltered"]
        for position, stage in enumerate(stages, start=1):
            value = self._filter_value_text(stage)
            short = value if len(value) <= 24 else value[:23] + "…"
            name = self._stage_title(position, stage)
            label = f"{position}. {name} = {short}" if short else f"{position}. {name}"
            # One line, no control character: a stage is an axis label, and a
            # vertical tab in one fails the PDF's figure export outright.
            labels.append(one_line(label))

        frames = []
        for dc in self.plan.dcs:
            names = [self.df_names[dc.dc_id]] + [
                self._stage_name(k, dc.dc_id) for k in range(1, len(stages) + 1)
            ]
            frames.append(f"    ({dc.tag!r}, [{', '.join(f'{n}.height' for n in names)}]),")

        body = (
            _comment(
                "Depictio's filter funnel: rows left after each stage, per data collection, "
                "counted from the stage frames above. Reorder the stages to see the "
                "intermediate counts move"
            )
            + f"\n_stages = {pprint.pformat(labels, width=88)}"
            + "\n_series = [\n"
            + "\n".join(frames)
            + "\n]"
            + "\nfig_funnel = funnel_figure(_stages, _series)"
            + "\nfig_funnel"
        )
        return Cell(body)

    def _funnel_cells(self) -> list[Cell]:
        cells: list[Cell] = []
        stages = self.plan.stages
        accent = palette_hex((self.plan.brand or {}).get("primary"), "#228be6")

        def part(title: str, icon: str, level: int, kind: str, **opts: Any) -> str:
            return self._heading(
                level=level,
                text=title,
                accent=accent,
                icon=self._icon_html(icon, accent),
                kind=kind,
                **opts,
            )

        # One line, folded: the report opens on its results, and the filters
        # are a click away. What the line says is all a reader needs before
        # deciding to open it: whether the view is filtered at all.
        filters_opts: dict[str, Any] = {
            "folded": True,
            "note": (f"{len(stages)} active" if stages else "none active"),
        }

        if not stages:
            cells.append(
                md_cell(
                    part("Filters", FILTERS_ICON, RESULTS_LEVEL, "filters", **filters_opts)
                    + " {#filters}"
                    + "\n\nNo filter was active when this notebook was exported: "
                    "every tile below reads the whole table."
                )
            )
        else:
            # Two parts, the same two the filter panel has: what is filtered,
            # then what it cost. The panel answers both questions in one place
            # and so should the export.
            cells.append(
                md_cell(
                    part("Filters", FILTERS_ICON, RESULTS_LEVEL, "filters", **filters_opts)
                    + " {#filters}"
                    + "\n\n*Each stage applies one filter on top of the previous one, in the "
                    "order the funnel view showed. Reordering stages changes the intermediate "
                    "counts, never the final one. The stages read their filters from "
                    "`depictio_state` when the document runs, so editing it, or rendering with "
                    "`quarto render -P depictio_state:...`, re-filters every tile.*"
                )
            )
            cells.append(
                md_cell(
                    part("Active filters", SUMMARY_ICON, TAB_LEVEL, "section")
                    + "\n\n"
                    + self._filters_summary_html(stages)
                )
            )
        if self.plan.embed_runtime:
            # The dashboard's own controls, drawn here by the runtime: the
            # summary above is what was exported, the panel what the page
            # shows now. Empty (and invisible) without the runtime.
            cells.append(md_cell(filters_placeholder(self.entry_tab_id)))
        prev = dict(self.df_names)
        # Each stage's call per collection, for the region-free frames below.
        stage_calls: dict[str, list[str]] = {dc.dc_id: [] for dc in self.plan.dcs}
        for k, stage in enumerate(stages, start=1):
            lines: list[str] = []
            head = f'Stage {k}, "{stage.label}"'
            if stage.interactive_component_type:
                head += f" ({stage.interactive_component_type})"
            if stage.value is not None:
                head += f": {_fmt_value(stage.value)}"
            counts = []
            for dc in self.plan.dcs:
                n = stage.rows_by_dc.get(dc.dc_id)
                if n is not None:
                    counts.append(f"{dc.tag} → {n:,} rows")
            if counts:
                head += ". After this stage: " + "; ".join(counts)
            lines.append(_comment(head))
            lines.append(
                f"# Read from depictio_state (stage {k} of its funnel order). As exported, it is:"
            )
            run: list[str] = []
            for dc in self.plan.dcs:
                name = self._stage_name(k, dc.dc_id)
                self.names.reserve(name)
                entries = stage.per_dc.get(dc.dc_id) or []
                applied = False
                literal = [f"{name} = {prev[dc.dc_id]}"]
                for entry in entries:
                    src = self._entry_source(dc, entry)
                    if src is None:
                        column = entry.get("column_name")
                        literal.append(
                            f"'{column}' is not a column of {dc.tag}: the server skips this "
                            "filter here, and so does the notebook"
                        )
                        continue
                    if entry.get("link"):
                        literal.append(
                            f"values resolved at export time through the cross-collection "
                            f"link {entry.get('index')!r}"
                        )
                    literal.extend(src.as_lines(name))
                    applied = True
                    fexpr = entry.get("filter_expr")
                    if fexpr:
                        literal.append(f"{name} = {name}.filter({emit_filter_expr(str(fexpr))})")
                if not applied and not entries:
                    literal[-1] += f"  (this filter does not touch {dc.tag})"
                lines.extend(f"#   {line}" for line in literal)
                links = [
                    {k2: v for k2, v in e.items() if k2 not in ("link",)}
                    for e in entries
                    if e.get("link")
                ]
                call = (
                    f"{name} = funnel_stage({prev[dc.dc_id]}, depictio_state, {k}, "
                    f"dc_id={dc.dc_id!r}"
                )
                if links:
                    call += (
                        f",\n    links={pprint.pformat(links, width=80)},"
                        f"\n    resolved_for={ {'index': stage.index, 'value': stage.value}!r},\n"
                    )
                run.append(call + ")")
                stage_calls[dc.dc_id].append(call)
                prev[dc.dc_id] = name
            cells.append(Cell("\n".join(lines + run)))
        final_lines = [
            _comment(
                "Every tile below reads this frame: the last funnel stage, plus any filter "
                "depictio_state holds beyond the exported stages"
            )
        ]
        for dc in self.plan.dcs:
            final_lines.append(
                f"{self.final_names[dc.dc_id]} = funnel_rest({prev[dc.dc_id]}, depictio_state, "
                f"{len(stages)}, dc_id={dc.dc_id!r})"
            )
        cells.append(Cell("\n".join(final_lines)))
        if self._region_stages():
            region_lines = [
                _comment(
                    "The same stages without the genome region: a region is a place to look, "
                    "not a subset to summarise, so cards (and figures that draw none of its "
                    "columns) read this frame, as on the dashboard"
                )
            ]
            for dc in self.plan.dcs:
                name = self.region_free_names[dc.dc_id]
                region_lines.append(f"{name} = {self.df_names[dc.dc_id]}")
                for call in stage_calls[dc.dc_id]:
                    # `x = funnel_stage(prev, ...` -> `name = funnel_stage(name, ..., region=False)`
                    rest = call.split("funnel_stage(", 1)[1].split(",", 1)[1]
                    rest = rest.rstrip().rstrip(",")
                    region_lines.append(f"{name} = funnel_stage({name},{rest}, region=False)")
                region_lines.append(
                    f"{name} = funnel_rest({name}, depictio_state, {len(stages)}, "
                    f"dc_id={dc.dc_id!r}, region=False)"
                )
            cells.append(Cell("\n".join(region_lines)))
        if stages:
            cells.append(
                md_cell(
                    part("Funnel", FUNNEL_ICON, TAB_LEVEL, "section")
                    + "\n\nRows left after each stage, and what share of the unfiltered "
                    "table that is, counted when the document runs. Pick the data collection "
                    "from the dropdown."
                )
            )
            cells.append(self._funnel_figure_cell(stages))
        return cells

    def _entry_source(self, dc: DCPlan, entry: dict[str, Any]) -> PredicateSource | None:
        column = str(entry.get("column_name") or "")
        itype = entry.get("interactive_component_type")
        if dc.columns is not None and column not in dc.columns and itype != "__link_no_match__":
            return None
        return emit_predicate(
            itype,
            column,
            entry.get("value"),
            dc.dtype(column),
            slider_mode=entry.get("slider_mode"),
            case_sensitive=entry.get("case_sensitive"),
            match_mode=entry.get("match_mode"),
            source=entry.get("source") or (entry.get("metadata") or {}).get("source"),
        )

    def _region_stages(self) -> set[str]:
        """The stages that are half of a genome region (or residue range) pair."""
        cached = getattr(self, "_region_stages_cache", None)
        if cached is not None:
            return cached
        by_index = {str(f.get("index")): f for f in self.plan.state.filters_as_payload()}
        self._region_stages_cache: set[str] = {
            s.index
            for s in self.plan.stages
            if is_region_filter(by_index.get(s.index))
            or any(is_region_filter(e) for entries in s.per_dc.values() for e in entries)
        }
        return self._region_stages_cache

    def _tile_frame(self, meta: dict[str, Any], dc: DCPlan) -> str:
        """The frame a code tile reads: the final one, or the one without the
        region when the server keeps the region off this component
        (``region_scope.scope_region_filters``)."""
        final = self.final_names[dc.dc_id]
        if not self._region_stages():
            return final
        from depictio.api.v1.region_scope import scope_region_filters

        region = [{"source": "genome_selection", "column_name": c} for c in self._region_columns()]
        ctype = str(meta.get("component_type") or "")
        if scope_region_filters(region, ctype, meta):
            return final
        return self.region_free_names[dc.dc_id]

    def _region_columns(self) -> set[str]:
        return {
            str(s.column) for s in self.plan.stages if s.index in self._region_stages() and s.column
        }

    # ---------------------------------------------------------------- groups
    def _pick_dc(self, dc_id: str | None) -> DCPlan | None:
        if dc_id and dc_id in self.dc_by_id:
            return self.dc_by_id[dc_id]
        return self.plan.dcs[0] if self.plan.dcs else None

    def _group_cells(self) -> list[Cell]:
        groups = self.plan.state.groups
        if not groups:
            return []
        cells = [
            md_cell(
                "## Selection groups\n\nGroups saved in the viewer, each as its own frame "
                "over the final stage. A group whose filter was active in the viewer is "
                "already part of the funnel above; it is repeated here so it can be used "
                "on its own."
            )
        ]
        for g in groups:
            dc = self._pick_dc(g.dc_id)
            name = self.names.claim("group", g.name)
            active = "filter active" if g.filter_active else "filter off"
            head = _comment(
                f'Selection group "{g.name}" ({active}): {len(g.values)} values of {g.column_name}'
            )
            if dc is None:
                cells.append(Cell(head + f"\n{name} = None  # no data collection in this export"))
                continue
            if dc.columns is not None and g.column_name not in dc.columns:
                cells.append(
                    Cell(
                        head
                        + f"\n{name} = {self.final_names[dc.dc_id]}  # '{g.column_name}' is not "
                        f"a column of {dc.tag}: nothing to select"
                    )
                )
                continue
            src = emit_predicate(
                "MultiSelect", g.column_name, list(g.values), dc.dtype(g.column_name)
            )
            body = [head, f"{name} = {self.final_names[dc.dc_id]}"]
            if src is not None:
                body.extend(src.as_lines(name))
            cells.append(Cell("\n".join(body)))
        return cells

    def _panel_cells(self) -> list[Cell]:
        panels = self.plan.state.split_panels
        if not panels:
            return []
        cells = [
            md_cell(
                "## Split panels\n\nThe viewer was split into small multiples; each panel is "
                "the final stage narrowed by its own constraints."
            )
        ]
        for p in panels:
            name = self.names.claim("panel", p.name)
            dc_hint = None
            for c in p.constraints:
                dc_hint = (c.metadata.dc_id if c.metadata else None) or dc_hint
            dc = self._pick_dc(dc_hint)
            body = [_comment(f'Panel "{p.name}"')]
            if dc is None:
                body.append(f"{name} = None  # no data collection in this export")
                cells.append(Cell("\n".join(body)))
                continue
            body.append(f"{name} = {self.final_names[dc.dc_id]}")
            for c in p.constraints:
                column = c.column_name or (c.metadata.column_name if c.metadata else None)
                if not column:
                    continue
                if dc.columns is not None and column not in dc.columns:
                    body.append(f"# '{column}' is not a column of {dc.tag}: constraint skipped")
                    continue
                src = emit_predicate(
                    c.interactive_component_type or "MultiSelect", column, c.value, dc.dtype(column)
                )
                if src is not None:
                    body.extend(src.as_lines(name))
            cells.append(Cell("\n".join(body)))
        return cells

    # ----------------------------------------------------------------- tiles
    def _tile_cells(self) -> list[Cell]:
        """The results part: the body tabs, in the report's own order.

        Without a layer this is every tab of the family, the second and every
        later one an appendix of the PDF. With one, it is the body tabs only,
        in the layer's order; the appendix tabs follow the conclusion, and
        ``build`` places them (``_appendix_cells``).
        """
        cells: list[Cell] = [md_cell(self._results_header_html())]
        self._section_i = 0
        cut = self._appendix_cut()
        body = self.entries() if cut is None else self.entries()[:cut]
        self._walk_tiles(body, cells, appendices=(cut is None))
        return cells

    def _appendix_cells(self) -> list[Cell]:
        """The layer's appendix tabs, after the conclusion: one part each,
        lettered, under the Appendices heading (the PDF only)."""
        cut = self._appendix_cut()
        if cut is None:
            return []
        cells: list[Cell] = []
        self._walk_tiles(self.entries()[cut:], cells, appendices=True, from_appendix=0)
        return cells

    def _walk_tiles(
        self,
        entries: list[tuple[MarkdownUnit | ComponentEntry, str | None]],
        cells: list[Cell],
        *,
        appendices: bool,
        from_appendix: int | None = None,
    ) -> None:
        """Lay one run of the reading order out, heading by heading.

        ``appendices`` marks the run's later tabs as the PDF's appendices;
        ``from_appendix`` letters every tab of the run, for the appendix run
        of a layered report (its first tab is Appendix A, not an unfolded
        body tab). The run continues the section anchors where the last one
        stopped (``_section_i``), so the two runs of a layered report never
        hand the same anchor to two headings.
        """
        pending: list[ComponentEntry] = []
        # The layer's own sections, per tab: tiles the author moved out of
        # their section, kept for the end of that tab's part.
        moved: dict[str, list[ComponentEntry]] = {}
        moved_order: list[str] = []
        tab_doc: dict[str, Any] = self.plan.tabs[0] if self.plan.tabs else {}
        # The preview's tab and section marker divs: open around each part's
        # heading, closed by the next heading of the same kind or the run's end.
        open_tab = False
        open_section = False

        def close_divs(*, tab: bool = False) -> None:
            nonlocal open_section, open_tab
            if open_section:
                cells.append(md_cell(SECTION_FENCE))
                open_section = False
            if tab and open_tab:
                cells.append(md_cell(TAB_FENCE))
                open_tab = False

        def flush() -> None:
            # The run of tiles between two headings, laid out row by row as
            # the dashboard's grid draws them; a tile the layer moved to its
            # own section leaves for that section's part.
            in_place: list[ComponentEntry] = []
            for e in pending:
                cfg = self._layer_tile(e)
                if cfg is not None and cfg.section and cfg.section.strip():
                    name = cfg.section.strip()
                    if name not in moved:
                        moved[name] = []
                        moved_order.append(name)
                    moved[name].append(e)
                else:
                    in_place.append(e)
            self._emit_rows(cells, in_place, tab_doc)
            pending.clear()

        def flush_moved() -> None:
            nonlocal open_section
            for name in moved_order:
                group = moved[name]
                if not group:
                    continue
                if open_section:
                    cells.append(md_cell(SECTION_FENCE))
                    open_section = False
                cells.append(md_cell(section_div(str(tab_doc.get("dashboard_id") or ""), name)))
                open_section = True
                cells.append(
                    md_cell(
                        self._markdown_unit_html(
                            MarkdownUnit(level=SECTION_LEVEL, text=name, kind="section"),
                            tab=tab_doc,
                        )
                    )
                )
                self._emit_rows(cells, group, tab_doc)
                group.clear()
                cells.append(md_cell(SECTION_FENCE))
                open_section = False
            # Both, or the next tab's tile joins a name `flush` still counts
            # as seen and is never laid out.
            moved_order.clear()
            moved.clear()

        tabs_seen = 0
        appendices_seen = 0
        for entry, _tab in entries:
            if isinstance(entry, MarkdownUnit):
                flush()
                # The first tab opens unfolded, every other one folded: the
                # report opens on its overview, not on every plot at once.
                if entry.kind == "tab":
                    close_divs()
                    flush_moved()
                    close_divs(tab=True)
                    cells.append(md_cell(tab_div(str(entry.dashboard_id or ""))))
                    open_tab = True
                    tabs_seen += 1
                    tab_doc = next(
                        (
                            t
                            for t in self.plan.tabs
                            if str(t.get("dashboard_id") or "") == (entry.dashboard_id or "")
                        ),
                        tab_doc,
                    )
                if entry.kind == "section":
                    close_divs()
                    cells.append(
                        md_cell(section_div(str(tab_doc.get("dashboard_id") or ""), entry.text))
                    )
                    open_section = True
                # In the PDF the first tab is the report and every other one an
                # appendix, under a heading of their own (the page keeps its tabs).
                appendix = None
                if appendices and self.plan.pdf and entry.kind == "tab":
                    n = tabs_seen - 2 if from_appendix is None else from_appendix + appendices_seen
                    if from_appendix is not None:
                        appendices_seen += 1
                    if n >= 0:
                        appendix = _appendix_letter(n)
                        if n == 0:
                            cells.append(md_cell(APPENDICES_HEADING))
                cells.append(
                    md_cell(
                        self._markdown_unit_html(
                            entry,
                            folded=(
                                entry.kind == "tab" and (tabs_seen > 1 or from_appendix is not None)
                            ),
                            tab=tab_doc,
                            appendix=appendix,
                        )
                    )
                )
                if entry.kind == "tab" and self.plan.embed_runtime:
                    # A tab with filters of its own gets them in its part: the
                    # Filters part draws the entry tab's only.
                    tid = entry.dashboard_id or ""
                    if (
                        tid
                        and tid != self.entry_tab_id
                        and any(
                            isinstance(m, dict) and m.get("component_type") == "interactive"
                            for m in tab_doc.get("stored_metadata") or []
                        )
                    ):
                        cells.append(md_cell(filters_placeholder(tid)))
                continue
            pending.append(entry)
        flush()
        close_divs()
        flush_moved()
        close_divs(tab=True)

    def _tile_order_key(self, entry: ComponentEntry) -> tuple[int, int]:
        """The layer's order for a tile; unordered tiles keep their place (a
        stable sort, so equal keys keep the reading order)."""
        cfg = self._layer_tile(entry)
        if cfg is not None and cfg.order is not None:
            return (0, cfg.order)
        return (1, 0)

    def _emit_rows(
        self, cells: list[Cell], entries: list[ComponentEntry], tab_doc: dict[str, Any]
    ) -> None:
        """A run of tiles as grid rows, the layer's order within the run."""
        if not entries:
            return
        cols = grid_columns(tab_doc) or 12
        for row in self._grid_rows(sorted(entries, key=self._tile_order_key), cols):
            cells.extend(self._row_cells(row, cols))

    # ------------------------------------------------------------ grid rows
    @staticmethod
    def _layout_of(entry: ComponentEntry) -> dict[str, Any]:
        source = entry.highlight if entry.highlight is not None else entry.unit.meta
        layout = (source or {}).get("layout") or {}
        if entry.highlight is not None and not layout:
            layout = entry.unit.meta.get("layout") or {}
        return layout if isinstance(layout, dict) else {}

    def _grid_rows(self, entries: list[ComponentEntry], cols: int) -> list[list[ComponentEntry]]:
        """Tiles that share a row of the dashboard's grid, in order.

        A row is a run of tiles at the same ``y`` whose widths fit the grid;
        a tile with no position stands alone, except a run of cards, which
        the dashboard draws as a strip. A tile the layer puts at full width
        stands alone too, and the rest of its row keeps sharing it.
        """
        rows: list[list[ComponentEntry]] = []
        for entry in entries:
            lay = self._layout_of(entry)
            y, w = lay.get("y"), lay.get("w")
            last = rows[-1] if rows else None
            if last and not (self._full_width(entry) or self._full_width(last[-1])):
                prev = self._layout_of(last[-1])
                if y is not None and prev.get("y") == y and isinstance(w, (int, float)):
                    used = sum(int(self._layout_of(e).get("w") or cols) for e in last)
                    if used + int(w) <= cols:
                        last.append(entry)
                        continue
                if (
                    y is None
                    and prev.get("y") is None
                    and self._is_card(entry)
                    and all(self._is_card(e) for e in last)
                ):
                    last.append(entry)
                    continue
            rows.append([entry])
        return rows

    def _full_width(self, entry: ComponentEntry) -> bool:
        """The layer asks for this tile across the whole page (cards excepted:
        a card stays in its strip)."""
        if self._is_card(entry):
            return False
        cfg = self._layer_tile(entry)
        if cfg is not None and cfg.full_width is not None:
            return cfg.full_width
        return self.settings.tile_width == "full"

    @staticmethod
    def _is_card(entry: ComponentEntry) -> bool:
        return (
            str(entry.unit.meta.get("component_type") or "") == "card"
            and entry.verdict.status != "omitted"
        )

    def _row_cells(self, row: list[ComponentEntry], cols: int) -> list[Cell]:
        if len(row) > 1 and all(self._is_card(e) for e in row):
            return self._card_row_cells(row)
        if len(row) == 1:
            return self._entry_cells(row[0], in_row=False)
        widths = [int(self._layout_of(e).get("w") or 1) for e in row]
        out = [md_cell(grid_open(widths))]
        for entry, w in zip(row, widths, strict=True):
            out.append(md_cell(cell_open()))
            if self.plan.pdf:
                # Its share of the column: the PDF draws its figure that wide.
                out.append(Cell(f"set_static_width({int(720 * w / sum(widths))})"))
            out.extend(self._entry_cells(entry, in_row=True))
            out.append(md_cell(DIV_CLOSE))
        out.append(md_cell(DIV_CLOSE))
        if self.plan.pdf:
            out.append(Cell("set_static_width(None)"))
        return out

    def _card_row_cells(self, row: list[ComponentEntry]) -> list[Cell]:
        """A strip of cards: one row cell, one note for their descriptions."""
        out: list[Cell] = []
        # One placeholder for the strip (its output is one cell), as the
        # preview's marker and, with the runtime, the cards' mount point.
        refs = [self._tile_ref(e) for e in row]
        out.append(md_cell(tile_anchors(refs)))
        out.append(md_cell(tile_open(refs)))
        render_names: list[str] = []
        pdf_names: list[str] = []
        for e in row:
            cell, render_name = self._tile_cell(e, show=False)
            out.extend(self._maybe_hide_pdf(e, [cell]))
            render_names.append(render_name)
            if self._tile_in_pdf(e):
                pdf_names.append(render_name)
        if self.plan.pdf and len(pdf_names) < len(render_names):
            # A strip the PDF only partly carries prints twice: every card on
            # the page, only the kept ones on paper (none kept: no PDF row).
            out.append(md_cell(HTML_ONLY_OPEN))
            out.append(self._row_cell(render_names))
            out.append(md_cell(DIV_CLOSE))
            if pdf_names:
                out.append(md_cell(TYPST_ONLY_OPEN))
                out.append(self._row_cell(pdf_names))
                out.append(md_cell(DIV_CLOSE))
        else:
            out.append(self._row_cell(render_names))
        out.append(md_cell(tile_close()))
        about = about_callout_many(
            [
                (
                    str(e.unit.meta.get("title") or e.unit.meta.get("index") or ""),
                    str(e.unit.meta.get("description") or ""),
                    str(e.unit.meta.get("index") or ""),
                )
                for e in row
            ],
            rewrite=self._rewrite_links,
        )
        if about:
            out.append(md_cell(about))
        return out

    # The tiles a report numbers as figures, and as tables.
    _TABLE_TYPES = frozenset({"table"})
    _UNNUMBERED = frozenset({"text", "card", "interactive", "highlight"})

    def _float_label(self, entry: ComponentEntry) -> str | None:
        """``fig-<index>`` / ``tbl-<index>``: the tile's Quarto cross-reference.

        From the component's own index (a UUID5 of its tag, stable across
        exports), so a reference to it survives a re-export. A highlight is
        labelled by its own index, the figure it shows already is."""
        meta = entry.unit.meta
        ctype = str(meta.get("component_type") or "")
        if ctype in self._UNNUMBERED or entry.verdict.status == "omitted":
            return None
        own = entry.highlight if entry.highlight is not None else meta
        ident = re.sub(r"[^a-z0-9-]+", "-", str(own.get("index") or "").lower()).strip("-")
        if not ident:
            return None
        prefix = "tbl" if ctype in self._TABLE_TYPES else "fig"
        label, n = f"{prefix}-{ident}", 2
        while label in self._float_labels:
            label, n = f"{prefix}-{ident}-{n}", n + 1
        self._float_labels.add(label)
        return label

    def _data_badge(self, meta: dict[str, Any]) -> str:
        """Where the tile's data came from: its collection, the rows it read,
        and as of when (the pinned commit, else the export)."""
        if not self.settings.provenance:
            return ""
        text = self._data_badge_text(meta)
        return f'<span class="dpx-asof">{_esc(text)}</span>' if text else ""

    def _dc_rows(self, meta: dict[str, Any]) -> int | None:
        """The rows the tile's collection holds in the exported state."""
        dc = self.dc_by_id.get(str(meta.get("dc_id") or ""))
        if dc is None:
            return None
        rows = dc.initial_rows
        for stage in self.plan.stages:
            got = stage.rows_by_dc.get(dc.dc_id)
            if got is not None:
                rows = got
        return rows

    def _starts_a_pdf_page(self, entry: ComponentEntry) -> bool:
        """A table the PDF prints long (``TABLE_PAGE_ROWS`` rows or more, of
        the page size it shows) opens a page of its own, so it is not cut
        after a few lines at the foot of one."""
        meta = entry.unit.meta
        if not (self.plan.pdf and self.settings.table_page_break):
            return False
        if str(meta.get("component_type") or "") != "table":
            return False
        rows = self._dc_rows(meta)
        if rows is None:
            return False
        page = int(meta.get("page_size") or 100)
        return min(rows, page) >= TABLE_PAGE_ROWS

    def _data_badge_text(self, meta: dict[str, Any]) -> str:
        dc = self.dc_by_id.get(str(meta.get("dc_id") or ""))
        tag = dc.tag if dc else str(meta.get("data_collection_tag") or "")
        if not tag:
            return ""
        bits = [f"Data: {tag}"]
        if dc is not None:
            rows = self._dc_rows(meta)
            if rows is not None:
                bits.append(f"{rows:,} rows")
            if dc.version is not None:
                bits.append(f"commit v{dc.version}")
        bits.append(f"as of {self.plan.exported_at:%Y-%m-%d}")
        return " · ".join(bits)

    def _entry_cells(self, entry: ComponentEntry, *, in_row: bool = False) -> list[Cell]:
        """One tile: its highlight line, the tile (numbered when it is a figure
        or a table, with its caption), then its "About this component"."""
        out: list[Cell] = []
        meta = entry.unit.meta
        ctype = str(meta.get("component_type") or "")
        cfg = self._layer_tile(entry)
        if cfg is not None and cfg.page_break_before:
            # The layer asks for a fresh page before this tile: a typst page
            # break in the PDF, a CSS one in the HTML.
            out.append(md_cell(PAGE_BREAK_MD))
        elif not in_row and self._starts_a_pdf_page(entry):
            # A large table opens its own PDF page (the report's settings).
            out.append(md_cell(TYPST_PAGE_BREAK_MD))
        if entry.highlight is not None:
            out.append(self._highlight_note(entry))
        tile: Cell | list[Cell] = self._tile_cell(entry)  # type: ignore[assignment]
        assert isinstance(tile, Cell)
        if (
            cfg is not None
            and cfg.orientation != "auto"
            and tile.kind == "code"
            and not tile.authored
        ):
            # The layer's page for this tile in the PDF; the call holds for
            # this cell's output only. An author's own code is left as written.
            tile = Cell(f"set_page_orientation({cfg.orientation!r})\n{tile.body}")
        if self._mountable(entry):
            # The preview's tile marker (contract §2), in every report — and,
            # when the runtime is embedded, its placeholder at the same time:
            # the cell's own output inside it is the fallback, the caption and
            # the note stay the document's. Text and highlight tiles stay
            # unwrapped: they are the narrative, and the runtime never mounts
            # them.
            own = tile_ref(*entry.own_ref) if entry.own_ref is not None else None
            tile = [
                md_cell(tile_open([self._tile_ref(entry)], as_ref=own)),
                tile,
                md_cell(tile_close()),
            ]
        elif meta.get("index"):
            # Prose gets its own marker, which the runtime never looks at, so
            # the editor's preview can still hide and move it (contract §2).
            ref = _esc(self._tile_ref(entry))
            tile = [md_cell(f'::: {{data-depictio-prose="{ref}"}}'), tile, md_cell(DIV_CLOSE)]
        tiles = tile if isinstance(tile, list) else [tile]
        if meta.get("index"):
            tiles = [md_cell(tile_anchors([tile_ref(*entry.layer_key)])), *tiles]
        if ctype == "text":
            surface = str(meta.get("surface") or "")
            if surface == "card":
                accent = palette_hex(str(meta.get("accent") or "") or None, "")
                if not in_row:
                    out.append(md_cell(SURFACE_OPEN))
                out.append(md_cell(cell_open("dpx-surface-card", accent or None)))
                out.extend(tiles)
                out.append(md_cell(DIV_CLOSE))
                if not in_row:
                    out.append(md_cell(DIV_CLOSE))
            else:
                out.extend(tiles)
            return self._maybe_hide_pdf(entry, out)
        label = self._float_label(entry)
        if label is None:
            out.extend(tiles)
            if self.plan.pdf:
                # No caption to read the tile's failure mark: clear it here.
                out.append(md_cell(TYPST_TILE_DONE))
        else:
            # A MultiQC tile has no title: its plot or module names it, as the
            # reader would ("general_stats" -> "General statistics").
            title = str(meta.get("title") or "").strip() or readable_name(
                meta.get("selected_plot") or meta.get("selected_module")
            )
            caption_bits = []
            if title:
                caption_bits.append(f"**{_esc(title)}**.")
            if entry.highlight is None:
                # The layer's caption replaces the tile's own (an empty string
                # drops it); without one, the tile's, as before.
                own_caption = (
                    cfg.caption
                    if cfg is not None and cfg.caption is not None
                    else meta.get("caption")
                )
                if str(own_caption or "").strip():
                    caption_bits.append(self._rewrite_links(_author_line(str(own_caption))))
            badge = self._data_badge(meta)
            if badge and self.plan.pdf:
                # The PDF's badge is typst: it stays silent under a tile that
                # could not be drawn (``dpx-asof``).
                caption_bits.append(
                    f'[{badge}]{{.content-visible when-format="html"}}'
                    f"`#dpx-asof({_typst_str(self._data_badge_text(meta).replace('`', ''))})`"
                    "{=typst}"
                )
            elif badge:
                caption_bits.append(badge)
            caption = " ".join(caption_bits) or _esc(ctype)
            out.append(md_cell(f"::: {{#{label}}}"))
            out.extend(tiles)
            # The caption inside a span the preview patches (contract §2): the
            # last paragraph of the float stays the caption Quarto reads, and
            # the span's attribute is dropped by the typst writer.
            out.append(md_cell(f"{caption_marked(caption)}\n\n:::"))
        about = about_callout(
            str(meta.get("description") or ""),
            name=str(meta.get("title") or ""),
            rewrite=self._rewrite_links,
        )
        if about:
            out.append(md_cell(about))
        return self._maybe_hide_pdf(entry, out)

    def _maybe_hide_pdf(self, entry: ComponentEntry, cells: list[Cell]) -> list[Cell]:
        """A tile the layer keeps out of the PDF, wrapped so only the HTML
        shows it (no PDF is built, no wrapper: the tile stays as it was)."""
        cfg = self._layer_tile(entry)
        if self.plan.pdf and cfg is not None and not cfg.in_pdf:
            return [md_cell(HTML_ONLY_OPEN), *cells, md_cell(DIV_CLOSE)]
        return cells

    def _tile_in_pdf(self, entry: ComponentEntry) -> bool:
        """Whether the PDF carries this tile (the layer's say, kept by default)."""
        cfg = self._layer_tile(entry)
        return cfg is None or cfg.in_pdf

    # ---------------------------------------------------------- the runtime
    @property
    def entry_tab_id(self) -> str:
        """The tab the state was captured on: the runtime's entry tab."""
        return str(self.plan.state.context.dashboard_id or self.plan.dashboard_id)

    @staticmethod
    def _tile_ref(entry: ComponentEntry) -> str:
        return tile_ref(
            str(entry.unit.tab.get("dashboard_id") or ""), str(entry.unit.meta.get("index") or "")
        )

    @staticmethod
    def _mountable(entry: ComponentEntry) -> bool:
        """Every tile the runtime could draw. Text and highlight tiles stay the
        document's own prose: the narrative is Quarto's. Whether a placeholder
        is actually drawn is the runtime's call, from the manifest's tiers."""
        return str(entry.unit.meta.get("component_type") or "") not in (
            "text",
            "highlight",
        ) and bool(entry.unit.meta.get("index"))

    def runtime_config(self) -> dict[str, Any]:
        """The report's look, for the runtime: the tiles take the document's
        primary colour and type rather than the instance's defaults."""
        brand = self.plan.brand or {}
        return {
            "brand": {
                k: v
                for k, v in {
                    "primary": self._primary()[0] if self.paper else brand.get("primary"),
                    # The report's own type: Inter (embedded once, by the theme
                    # cell) in front of the brand's or the app's UI stack.
                    "font_family": sans_stack(brand.get("font_family"))
                    if self.paper
                    else brand.get("font_family"),
                }.items()
                if v
            }
            or None
        }

    def _runtime_cell(self) -> Cell:
        config = self.runtime_config()
        return Cell(
            "#| output: asis\n"
            + _comment(
                "The dashboard's own renderers, embedded once: every tile above is drawn by "
                "them from the dashboard's data (the same manifest a static export bundles), "
                "and follows the filter panel, in this page, with no server. Each tile's "
                "output above stays as its fallback: shown when the runtime cannot draw it, "
                "when scripts are blocked, or when this prints nothing (no API, or not the "
                "dashboard's owner)"
            )
            + f"\nprint(client.report_runtime({self.entry_tab_id!r}, depictio_state, "
            f"config={config!r}))"
        )

    def _icon_html(self, icon_id: str | None, color_hex: str) -> str:
        svg = self.plan.icons.get(icon_id or "") if icon_id else None
        if not svg:
            return ""
        # No pixel box around the glyph: the SVG is sized in `em`, so it takes
        # the heading's own size, and the -0.125em shift drops it onto the text
        # baseline — the same two rules @iconify/react applies in the app. A
        # fixed 16px flex box (what this used to be) fought both: it clipped
        # the glyph and floated it off the line.
        return (
            f'<span style="display:inline-flex;align-items:center;vertical-align:-0.125em;'
            f"font-size:0.9em;line-height:1;margin-inline-end:0.28em;"
            f'color:{color_hex or "inherit"}">{svg}</span>'
        )

    def _heading(
        self,
        *,
        level: int,
        text: str,
        accent: str,
        icon: str,
        kind: str,
        folded: bool = False,
        note: str = "",
        tab_id: str | None = None,
        printed_text: str | None = None,
    ) -> str:
        """One heading line: a real ATX heading, decorated inline.

        ``printed_text`` is the heading's text in the PDF when it differs from
        the page's (an appendix there: "Appendix A — MultiQC").

        The `#`s have to stay: the table of contents, the anchor links and (in
        Quarto) the section wrappers the fold script reads are all built from
        them, and a block-level `<div>` in front would take the line out of
        markdown parsing entirely. So the icon, the colour and the marker the
        script keys on all ride *inside* the line as inline HTML.
        """
        fold = ' data-dpx-fold="closed"' if folded else ""
        # A tab's part names its dashboard tab: the combined file's "Show this
        # tab in the report" lands on it.
        tab = f' data-depictio-tab="{_esc(tab_id)}"' if tab_id else ""
        mark = f'<span data-dpx-accent="{accent}" data-dpx-kind="{kind}"{fold}{tab}>{icon}</span>'
        # The colour as a custom property the page's stylesheet reads, not a
        # `color:` of its own: Quarto turns an inline colour into a typst fill,
        # and the PDF colours its headings itself (``pdf_typst``, by label),
        # so its monochrome style can leave them in the text colour.
        shown = _esc(text)
        if printed_text and printed_text != text:
            shown = (
                f'[{shown}]{{.content-visible when-format="html"}}'
                f'[{_esc(printed_text)}]{{.content-visible when-format="typst"}}'
            )
        title = (
            f'<span class="dpx-hc" style="--dpx-hc:{accent}">{shown}</span>' if accent else shown
        )
        # The page's muted aside ("none active"); a printed heading has no
        # aside, so the PDF leaves it out rather than read it as the title.
        aside = (
            f' [<span class="dpx-h-note">{_esc(note)}</span>]'
            '{.content-visible when-format="html"}'
            if note
            else ""
        )
        return f"{'#' * max(1, min(6, level))} {mark}{title}{aside}"

    def _markdown_unit_html(
        self,
        unit: MarkdownUnit,
        *,
        folded: bool = False,
        tab: dict[str, Any] | None = None,
        appendix: str | None = None,
    ) -> str:
        if unit.kind == "section":
            return self._section_header_html(unit, tab=tab)
        return self._tab_header_html(unit, folded=folded, appendix=appendix)

    def _results_header_html(self) -> str:
        """The one heading every tab hangs off: the dashboard itself."""
        accent = palette_hex((self.plan.brand or {}).get("primary"), "")
        return "\n\n".join(
            [
                self._heading(
                    level=RESULTS_LEVEL,
                    text=RESULTS_HEADING,
                    accent=accent,
                    icon=self._icon_html(RESULTS_ICON, accent),
                    kind="results",
                ),
                "*One part per tab of the dashboard, in the order the tabs are shown.*",
            ]
        )

    def _section_filter_bar(self, unit: MarkdownUnit, tab: dict[str, Any] | None) -> str:
        """The section's own filter bar (``filter_bar: true``), as exported:
        each control with its icon and the value it held, "All" when unset."""
        if not tab:
            return ""
        spec = next(
            (
                g
                for g in tab.get("grid_sections") or []
                if isinstance(g, dict) and str(g.get("name") or "") == unit.text
            ),
            None,
        )
        if not spec or not spec.get("filter_bar"):
            return ""
        controls = [
            m
            for m in tab.get("stored_metadata") or []
            if isinstance(m, dict)
            and m.get("component_type") == "interactive"
            and str(m.get("section") or "") == unit.text
        ]
        if not controls:
            return ""
        by_index = {s.index: s for s in self.plan.stages}
        chips = []
        for m in controls:
            stage = by_index.get(str(m.get("index") or ""))
            value = self._filter_value_text(stage) if stage else "All"
            color = palette_hex(
                str(m.get("custom_color") or m.get("icon_color") or m.get("color") or "") or None,
                "",
            )
            label = str(m.get("strip_label") or m.get("title") or m.get("column_name") or "")
            chips.append(
                '<span class="dpx-filterchip">'
                + self._icon_html(filter_icon_id(m), color)
                + f"<b>{_esc(label)}</b> <i>{_esc(value)}</i></span>"
            )
        return (
            '::: {.content-visible when-format="html"}\n<div class="dpx-filterbar">'
            + "".join(chips)
            + "</div>\n:::"
        )

    def _section_header_html(self, unit: MarkdownUnit, *, tab: dict[str, Any] | None = None) -> str:
        # The live grid's own section chrome (SectionAccordion / SectionIcon):
        # icon and title in the section's colour, over a body the reader can
        # fold, behind that colour's rail. Unset stays neutral rather than
        # picking a hue on the author's behalf, exactly as the app does.
        accent = palette_hex(unit.color, "")
        parts = [
            self._heading(
                level=SECTION_LEVEL,
                text=unit.text,
                accent=accent,
                icon=self._icon_html(unit.icon, accent),
                kind="section",
                # The dashboard's own default: a section it opens folded, the
                # report opens folded too.
                folded=unit.collapsed,
            )
            + self._next_section_anchor()
        ]
        lines = []
        if unit.description:
            lines.append(f"*{self._rewrite_tab_links(_esc(unit.description))}*")
        if unit.persistent:
            # Written once, here; on the dashboard it is on every tab.
            but = ", ".join(_esc(t) for t in unit.exclude_tabs)
            lines.append(
                "*On the dashboard this section is shown on every tab"
                + (f" but {but}" if but else "")
                + ".*"
            )
        if lines:
            # Markdown's hard break, not ``<br>``: a typst page drops raw HTML,
            # and the two sentences would run into each other there.
            parts.append("\\\n".join(lines))
        bar = self._section_filter_bar(unit, tab)
        if bar:
            parts.append(bar)
        return "\n\n".join(parts)

    def _next_section_anchor(self) -> str:
        if self._section_i >= len(self._section_anchor_seq):
            return ""
        anchor = self._section_anchor_seq[self._section_i]
        self._section_i += 1
        return f" {{#{anchor}}}"

    def _tab_header_html(
        self, unit: MarkdownUnit, *, folded: bool = False, appendix: str | None = None
    ) -> str:
        # Each tab of a multi-tab family is its own dashboard_id with its own
        # possible brand_theme override — the live sidebar shows a different
        # icon/colour per tab, so the export's per-tab part gets its own
        # resolved identity too, not just the document's.
        brand = self.plan.tab_brands.get(unit.dashboard_id or "") if unit.dashboard_id else None
        fallback = (brand or self.plan.brand or {}).get("primary") or ""
        accent = palette_hex(unit.color, fallback)
        anchor = self.tab_anchors.get(unit.dashboard_id or unit.text)
        parts = [
            self._heading(
                level=TAB_LEVEL,
                text=unit.text,
                accent=accent,
                icon=self._icon_html(unit.icon, accent),
                kind="tab",
                folded=folded,
                tab_id=unit.dashboard_id,
                printed_text=f"Appendix {appendix} — {unit.text}" if appendix else None,
            )
            + (f" {{#{anchor}}}" if anchor else "")
        ]
        # A tab's description that is the document's subtitle (the main tab's,
        # as a rule) is already printed under the title.
        if unit.description and unit.description.strip() != (self.plan.subtitle or "").strip():
            parts.append(f"*{self._rewrite_tab_links(_esc(unit.description))}*")
        # Only a tab that actually overrides the instance brand shows a mark of
        # its own. A tab without an override resolves to the same brand as the
        # document, and printing it would repeat the header's logo under every
        # single tab.
        logo = (brand or {}).get("logo_data_uri")
        if logo == (self.plan.brand or {}).get("logo_data_uri"):
            logo = None
        if logo:
            app_name = _esc((brand or {}).get("app_name") or "")
            parts.append(
                f'<img src="{logo}" alt="{app_name}" style="height:22px;width:auto;opacity:0.85" />'
            )
        return "\n\n".join(parts)

    def _row_cell(self, render_names: list[str]) -> Cell:
        # card_row() calls `_repr_html_()` on each element (an HTML object from
        # metric_card, or a DepictioComponent), so it lays them out without
        # needing to know what kind of card each one is.
        items = ", ".join(render_names)
        return Cell(f"card_row([{items}])")

    def _tile_cell(self, entry: ComponentEntry, *, show: bool = True) -> Cell | tuple[Cell, str]:
        meta = entry.unit.meta
        ctype = str(meta.get("component_type") or "")
        title = str(meta.get("title") or meta.get("index") or ctype)
        if ctype == "text":
            return self._text_cell(
                meta, entry.unit.section, tab_id=str(entry.unit.tab.get("dashboard_id") or "")
            )
        if ctype == "highlight":
            return self._highlight_cell(meta, title)
        if entry.verdict.status == "omitted":
            return md_cell(
                f"> **{_esc(title)}** is not in this notebook: {_esc(entry.verdict.reason)}."
            )
        if entry.verdict.status == "api":
            cell = self._api_cell(entry, title, show=show)
            return cell if show else (cell, entry.name or self.names.claim("viz", title))
        dc = self.dc_by_id[str(meta.get("dc_id") or "")]
        final = self._tile_frame(meta, dc)
        name = entry.name or self.names.claim("tile", title)
        fexpr = meta.get("filter_expr")
        source = final
        prelude: list[str] = []
        if fexpr:
            prelude.append(f"_scoped = {final}.filter({emit_filter_expr(str(fexpr))})")
            source = "_scoped"
        if ctype == "card":
            agg = str(meta.get("aggregation") or "")
            column = str(meta.get("column_name") or "")
            expr = agg_expr_source(column, agg) or "pl.lit(None)"
            body = [
                _comment(f'Card "{title}": {agg} of {column} over the filtered rows'),
                *prelude,
                f"{name} = {source}.select({expr}).item()",
            ]
            if show:
                # `name` stays the raw scalar; the metric_card() call is a
                # bare expression purely for display, same as before grouping
                # existed.
                body.append(f"metric_card({title!r}, {name})")
                return Cell("\n".join(body))
            # Grouped: `name` still stays the raw scalar, but the row cell
            # after this one needs an actual object to lay out, so the html
            # gets its own name here instead of being a bare expression.
            html_name = self.names.claim("card_html", title)
            body.append(f"{html_name} = metric_card({title!r}, {name})")
            return Cell("\n".join(body)), html_name
        if ctype == "table":
            columns = [c for c in (meta.get("columns") or []) if isinstance(c, str)]
            page = int(meta.get("page_size") or 100)
            select = f".select({columns!r})" if columns else ""
            body = [
                _comment(f'Table "{title}": the first {page} filtered rows, all of them shown'),
                *prelude,
                f"{name} = {source}{select}.head({page})",
                # The dashboard's colours for a column's values, as chips.
                f"show_table({name}, colors=depictio_category_colors)"
                if self._category_colors()
                else f"show_table({name})",
            ]
            return Cell("\n".join(body))
        if ctype == "figure":
            return self._figure_cell(meta, name, source, prelude, title)
        return md_cell(f"> **{_esc(title)}** ({_esc(ctype)}) has no code path yet.")

    def _highlight_note(self, entry: ComponentEntry) -> Cell:
        """A highlight drawn in place: where its figure lives, then its caption.

        The dashboard shows the figure itself on the tab that highlights it, so
        the document does too, rather than pointing at the tab's part. The
        figure is the same one that tab draws (its definition, its data); the
        line below says so, and links there.
        """
        tab = entry.unit.tab
        anchor = self.tab_anchors.get(str(tab.get("dashboard_id") or "")) or self.tab_anchors.get(
            tab_display_name(tab)
        )
        name = _esc(tab_display_name(tab))
        where = f"[{name}](#{anchor})" if anchor else f"**{name}**"
        # The highlight's own caption: the figure, drawn from its own tab's
        # definition, carries the source's.
        caption = self._rewrite_tab_links(_author_line((entry.highlight or {}).get("caption")))
        line = f"*From the {where} tab.*"
        return md_cell(line + (f" {caption}" if caption else ""))

    def _highlight_cell(self, meta: dict[str, Any], title: str) -> Cell:
        source = str(meta.get("source_component") or "a figure")
        tab = str(meta.get("source_tab") or "").strip()
        where = f"the **{_esc(tab)}** tab" if tab else "another tab"
        line = f"> **{_esc(title)}** shows *{_esc(source)}* from {where}, drawn in that tab's part."
        caption = self._rewrite_tab_links(_author_line(meta.get("caption")))
        return md_cell(line + (f"\n>\n> {caption}" if caption else ""))

    def _text_cell(
        self, meta: dict[str, Any], section: str | None = None, *, tab_id: str = ""
    ) -> Cell:
        # The author's markdown, kept as markdown but with no Quarto construct
        # left in it (``qmd_safe.defuse``): a fence or a shortcode in a text
        # tile is shown as the text it is, never run.
        title = defuse(one_line(str(meta.get("title") or ""))).strip()
        body = defuse(str(meta.get("body") or "")).strip()
        # On the dashboard a section's narration tile sits *under* the section
        # header, so repeating the name there reads as a caption. Stacked in a
        # document the two headings land on consecutive lines and read as a
        # mistake, so the tile keeps its prose and drops the echo.
        if title and section and title.lower() == section.strip().lower():
            title = ""
        order = meta.get("order")
        try:
            level = int(order) if order is not None else SECTION_LEVEL + 1
        except (TypeError, ValueError):
            level = SECTION_LEVEL + 1
        # A text tile sits *inside* a section, so it can never outrank one: the
        # dashboards write `order: 2` meaning "second-biggest heading on my
        # tile", which used to land it at h2, above the section holding it and
        # level with the tabs in the table of contents.
        level = max(SECTION_LEVEL + 1, min(6, level))
        parts = []
        hero = self.hero
        is_hero = hero is not None and str(meta.get("index") or "") == hero[0]
        # The first tab's header tile: its logo is the document's title now,
        # so the tile keeps only its prose.
        logo = "" if is_hero else self._text_logo(meta)
        if is_hero:
            title = ""
        if logo:
            # The tile's header logo stands in for its title, as on the
            # dashboard (the title is its alt text).
            parts.append(logo)
        elif title:
            parts.append(f"{'#' * level} {title}")
        if body:
            # Headings a tile writes inside itself rank under its section too:
            # `### Data & QC` in a tile's body used to close the section and
            # the tab around it, and listed itself among the tabs.
            parts.append(demote_headings(body, level + 1 if title else level))
        text = "\n\n".join(parts) or "*(empty text tile)*"
        if self.plan.pdf:
            # The PDF draws the stepper and the fact lists itself.
            accent = palette_hex(str(meta.get("accent") or "") or None, self._accent())
            text = pdf_structures(
                text,
                lambda icon: self.plan.icons.get(icon),
                accent=accent,
                mono=self.plan.pdf_style == "mono",
            )
        text = stepper_markdown(
            text,
            lambda icon: self._inline_icons(f"![](icon:{icon})"),
            rewrite_link=self._rewrite_links,
        )
        text = self._inline_icons(self._rewrite_links(text))
        legends = {
            f"legend:{c}": self._legend_html(c) for c in dict.fromkeys(_LEGEND_RE.findall(text))
        }
        values = meta.get("values") if isinstance(meta.get("values"), dict) else {}
        if not values and "{{param:" not in text:
            for key, html in legends.items():
                text = text.replace("{{" + key + "}}", html)
            return md_cell(text)
        # Live values: computed by Depictio under the state above when the
        # document runs, printed as the tile's own markdown (`output: asis`), so
        # headings and links stay the document's. The values the export saw
        # stand in when the API is out of reach.
        index = str(meta.get("index") or "")
        tab_id = tab_id or self.plan.dashboard_id
        formats = {
            str(k): str(v.get("format"))
            for k, v in values.items()
            if isinstance(v, dict) and v.get("format")
        }
        fallback = self.plan.text_values.get(index) or {}
        lines = [
            "#| output: asis",
            _comment(
                f"Text tile {index!r}: its live values ({', '.join(values) or 'run parameters'}) "
                "are computed by Depictio under the state above; offline, the values at "
                "export time stand in"
            ),
            "print(",
            "    fill_text(",
            f"        {text!r},",
            f"        client.text_values({tab_id!r}, {index!r}, depictio_state, "
            f"fallback={fallback!r}),",
            f"        formats={formats!r},",
            f"        legends={legends!r},",
            "    )",
            ")",
        ]
        return Cell("\n".join(lines))

    def _text_logo_uris(self, meta: dict[str, Any]) -> tuple[str | None, str | None]:
        """A text tile's header logo, light and dark, as data URIs (inlined)."""
        given = self.plan.logos.get(str(meta.get("index") or "")) or {}
        light = given.get("light") or meta.get("logo")
        dark = given.get("dark") or meta.get("logo_dark")
        light = light if isinstance(light, str) and light.startswith("data:image/") else None
        dark = dark if isinstance(dark, str) and dark.startswith("data:image/") else None
        return light, dark

    def _text_logo(self, meta: dict[str, Any]) -> str:
        """A text tile's header logo, light and dark, as inline images."""
        light, dark = self._text_logo_uris(meta)
        if not light:
            return ""
        alt = _esc(str(meta.get("title") or ""), quote=True)
        if not dark:
            return f'<img class="dpx-hero-logo" src="{light}" alt="{alt}" />'
        return (
            f'<img class="dpx-hero-logo dpx-light-only" src="{light}" alt="{alt}" />'
            f'<img class="dpx-hero-logo dpx-dark-only" src="{dark}" alt="{alt}" />'
        )

    def _api_cell(self, entry: ComponentEntry, title: str, *, show: bool = True) -> Cell:
        meta = entry.unit.meta
        tab_id = str(entry.unit.tab.get("dashboard_id") or self.plan.dashboard_id)
        kind = entry.verdict.kind or str(meta.get("component_type") or "component")
        name = entry.name or self.names.claim("viz", title)
        if entry.verdict.output == "snapshot":
            handles = (
                "It is not drawn with Plotly, so the cell shows a static snapshot of the "
                "real renderer; `.image` is that PNG, `.data` the data"
            )
        elif entry.verdict.native and entry.verdict.output == "interactive":
            handles = "`.figure` is the figure drawn here, `.data` the data"
        elif entry.verdict.native:
            handles = "`.data` is the data it is drawn from"
        elif entry.verdict.output == "interactive":
            handles = "`.figure` is the Plotly figure, `.data` the data"
        else:
            handles = "`.data` is the data behind it"
        verb = "drawn here from its data" if entry.verdict.native else "rendered by Depictio"
        head = _comment(
            f'"{title}" ({kind}) is {verb} with the state above: {entry.verdict.reason}. {handles}'
        )
        body = (
            head + f"\n{name} = client.component({tab_id!r}, {str(meta.get('index'))!r}, "
            "state=depictio_state)"
        )
        # `show=False` is a card folded into a row: the assignment above still
        # defines `name`, it just isn't shown as this cell's own output — the
        # row cell after it displays all of them together via card_row().
        if show:
            body += f"\n{name}"
        return Cell(body)

    def _figure_cell(
        self, meta: dict[str, Any], name: str, source: str, prelude: list[str], title: str
    ) -> Cell:
        # classify() only sends a figure here in code mode: the author wrote
        # this figure's Python themselves, so showing it back is showing
        # their own code, not a guess. A UI-built figure is classified "api"
        # instead and goes through _api_cell, so it renders through
        # client.component(...) rather than a reconstructed px.* call.
        from depictio.api.v1.services.figure.groups import (
            CODE_GROUP_BY,
            CODE_GROUP_KWARGS,
            GROUP_COLUMN,
        )

        code = str(meta.get("code_content") or "").rstrip()
        code_lines = ["    " + line if line.strip() else "" for line in code.split("\n")]
        # The server hands the grouping over only to code that names it, and
        # annotates the frame only then (`code_group_optin`).
        opts_in = any(n in code for n in (CODE_GROUP_KWARGS, CODE_GROUP_BY, GROUP_COLUMN))
        dc = self.dc_by_id.get(str(meta.get("dc_id") or ""))
        kind, _column = self._grouping()
        lines = [
            _comment(f'Figure "{title}", code mode: the author\'s code, verbatim'),
            *prelude,
        ]
        call = f"{name} = _make_{name}({source})"
        if opts_in and kind != "none" and dc is not None:
            kwargs, by = self._group_kwargs(dc)
            frame = source
            if kind == "groups" and kwargs:
                annotate = self._group_annotation_lines(dc, "_grouped")
                if annotate:
                    lines += [
                        _comment("Each row labelled with its selection group, as the server does"),
                        f"_grouped = {source}",
                        *annotate,
                    ]
                    frame = "_grouped"
                else:
                    kwargs, by = {}, []
            call = (
                f"{name} = _make_{name}(\n    {frame},\n"
                f"    depictio_group_kwargs={pprint.pformat(kwargs, width=80, sort_dicts=False)},\n"
                f"    depictio_group_by={by!r},\n)"
            )
        # The cell is the author's (``Cell.authored``: emitted as written), so
        # what the generator adds around their code is defused here instead.
        head = defuse_code("\n".join(lines))
        lines = [
            head,
            f"def _make_{name}(df, depictio_group_kwargs=depictio_group_kwargs, "
            "depictio_group_by=depictio_group_by):",
            *code_lines,
            "    return fig",
            "",
            defuse_code(call),
            name,
        ]
        return Cell("\n".join(lines), authored=True)


def generate_qmd(plan: ExportPlan) -> str:
    return NotebookBuilder(plan).build()
