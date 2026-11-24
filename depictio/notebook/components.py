"""Dashboard components as notebook objects.

A :class:`DepictioComponent` wraps one component of a dashboard, bound to an
analysis state (the filters, groups and funnel order the dashboard applied).
It fetches lazily, caches, and displays itself wherever a Jupyter kernel does
(a Quarto render, Quarto's editor integrations, JupyterLab):

* ``.figure`` — a ``plotly.graph_objects.Figure`` for figures, maps, MultiQC
  plots and the advanced visualisations (the server extracts the Plotly
  figure from its own React renderer for the kinds it does not draw in Python,
  and the kinds the app draws without Plotly are drawn here from their data,
  ``depictio.notebook.native``);
* ``.data`` — a ``polars.DataFrame`` (tables, filters, image rows, advanced-viz
  payloads) or a dict (cards);
* ``.html`` — the real React tile, self-contained, as an HTML document.

What a component shows by default is the closest thing to what the dashboard
shows: the figure where there is one, the DataFrame for a table, a small card
for a card, markdown for a text tile, an image grid, a JBrowse iframe.
"""

from __future__ import annotations

import base64
import html as _html
import json
import os
import re
import time
from typing import TYPE_CHECKING, Any

import polars as pl

from . import text as _text
from . import theme as _theme
from . import typst as _typst
from .qmd_safe import esc as _esc

if TYPE_CHECKING:  # pragma: no cover
    from .client import DepictioClient

HTML_MIME = "text/html"
MARKDOWN_MIME = "text/markdown"
PLAIN_MIME = "text/plain"
PLOTLY_MIME = "application/vnd.plotly.v1+json"
PNG_MIME = "image/png"

#: Set when the document is rendered to a page with no browser behind it (the
#: PDF, Quarto's typst): every figure then also carries a PNG and every table
#: a markdown copy, which is what such a page can hold.
STATIC_FIGURES_ENV = "DEPICTIO_STATIC_FIGURES"
#: Rows a table keeps on a static page; the HTML report has them all.
STATIC_TABLE_ROWS = 30


# What a MultiQC plot or module id reads as, where the id alone does not.
_READABLE: dict[str, str] = {
    "general_stats": "General statistics",
    "multiqc": "MultiQC",
    "fastqc": "FastQC",
    "advanced_viz": "Visualisation",
}


def readable_name(value: Any) -> str:
    """``general_stats`` -> "General statistics"; "Per Base N Content" stays."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in _READABLE:
        return _READABLE[text.lower()]
    if "_" in text and " " not in text:
        text = text.replace("_", " ")
        return text[:1].upper() + text[1:]
    return text


def _hex_color(color: str | None, fallback: str) -> str:
    """A Mantine palette name (shade 6) or a CSS colour (``theme.palette_hex``)."""
    return _theme.palette_hex(color, fallback)


#: "No argument given", where ``None`` is a value (a card with no value).
_MISSING: Any = object()


class StaticCard:
    """A code-mode card (``metric_card``) on a static page: a title over a value."""

    def __init__(self, title: str, text: str) -> None:
        self.title, self.text = title, text

    def _repr_markdown_(self) -> str:
        return _typst.kpis([self._typst_card_()])

    def _typst_card_(self, mono: bool = False) -> str:
        return _typst.kpi(title=self.title, value=self.text)


def static_card_row(cards: list[Any], mono: bool = False) -> str:
    """A strip of cards as the PDF draws it: each card's ``_typst_card_`` when
    it has one, its text otherwise."""
    out = []
    for card in cards:
        fn = getattr(card, "_typst_card_", None)
        if fn is not None:
            try:
                out.append(fn(mono))
                continue
            except Exception:  # noqa: BLE001 - a card that cannot be computed reads as one
                out.append(
                    _typst.kpi(
                        title=str(getattr(card, "title", "")),
                        value="–",
                        caption="Could not be computed for this report.",
                    )
                )
                continue
        html = getattr(card, "_repr_html_", lambda: "")() or ""
        out.append(_typst.kpi(title=str(getattr(card, "title", "")), value=html_text(html)))
    return _typst.kpis(out)


def static_figures() -> bool:
    """Whether this render wants static figures (``STATIC_FIGURES_ENV``)."""
    return os.environ.get(STATIC_FIGURES_ENV, "") not in ("", "0", "false")


#: A static figure's width in CSS pixels: a PDF page's text column is about
#: this wide at Plotly's 12 px labels, so the figure's text prints at the size
#: the body's does (8-9 pt) rather than shrunk from a 1000 px canvas.
STATIC_FIGURE_WIDTH = 720


_STATIC_WIDTH = {"px": STATIC_FIGURE_WIDTH}


def set_static_width(px: int | None = None) -> None:
    """The width static figures are drawn at from now on (``None``: the full
    column's). A row of tiles draws each at its share of the column, so its
    labels print at the same size as a full-width figure's."""
    _STATIC_WIDTH["px"] = int(px) if px else STATIC_FIGURE_WIDTH


#: A figure whose layout is wider than this width:height ratio prints on a
#: landscape page (``figure_orientation``).
LANDSCAPE_FIGURE_RATIO = 1.6


def figure_ratio(fig) -> float | None:
    """The figure's own layout width:height ratio, when the layout sets both."""
    layout = getattr(fig, "layout", None)
    width = getattr(layout, "width", None) if layout is not None else None
    height = getattr(layout, "height", None) if layout is not None else None
    if not width or not height:
        return None
    return width / height


def figure_orientation(ratio: float | None, override: str = "auto") -> str:
    """The page orientation a figure asks for: landscape when its layout is
    wider than ``LANDSCAPE_FIGURE_RATIO``:1, else portrait. ``override``
    (``"auto"``, ``"portrait"``, ``"landscape"``) wins when it is set."""
    if override in ("portrait", "landscape"):
        return override
    return "landscape" if ratio is not None and ratio > LANDSCAPE_FIGURE_RATIO else "portrait"


#: The page orientation the report's author set for the current cell's tile
#: (``set_page_orientation``); ``auto`` leaves it to ``figure_orientation`` and
#: ``typst.table``'s own rules.
_PAGE_ORIENTATION = {"value": "auto", "hooked": False}


def _reset_page_orientation(*_args: Any) -> None:
    _PAGE_ORIENTATION["value"] = "auto"


def set_page_orientation(orientation: str = "auto") -> None:
    """The PDF page orientation for this cell's figure or table.

    A report's author can ask a tile for a portrait or a landscape page; the
    export writes this call at the top of that tile's cell. Under IPython (the
    kernel Quarto runs) the override ends with the cell, since outputs are
    formatted before ``post_run_cell`` fires; elsewhere it holds until the next
    call, like ``set_static_width``.
    """
    value = orientation if orientation in ("portrait", "landscape") else "auto"
    _PAGE_ORIENTATION["value"] = value
    if _PAGE_ORIENTATION["hooked"]:
        return
    try:
        from IPython import get_ipython
    except ImportError:  # pragma: no cover - IPython ships with every kernel
        return
    shell = get_ipython()
    if shell is not None:
        shell.events.register("post_run_cell", _reset_page_orientation)
        _PAGE_ORIENTATION["hooked"] = True


def page_orientation() -> str:
    """The orientation ``set_page_orientation`` set for this cell."""
    return str(_PAGE_ORIENTATION["value"])


_BR_RE = re.compile(r"<br\s*/?>", re.I)
_MARKUP_RE = re.compile(r"<[^>]+>")
# Inter's average glyph is a little over half its size; a label's width in px
# is about this times its length times the font size.
_GLYPH = 0.58


def _axis_labels(fig, name: str) -> list[str]:
    """What a categorical axis prints: its ``ticktext`` when it sets one, else
    the string values its traces put on it. Empty for a numeric or date axis."""
    axis = fig.layout[name]
    if axis.type not in (None, "-", "category", "multicategory"):
        return []
    if axis.ticktext is not None and len(axis.ticktext):
        return [str(t) for t in axis.ticktext]
    letter, suffix = name[0], name[5:]
    seen: dict[str, None] = {}
    for trace in fig.data:
        if (getattr(trace, f"{letter}axis", None) or letter) != letter + suffix:
            continue
        values = getattr(trace, letter, None)
        if values is None:
            continue
        for v in values:
            if isinstance(v, str):
                seen.setdefault(v, None)
            elif axis.type != "category":
                return []  # numbers on an auto axis: not categorical
    labels = list(seen)
    if axis.type != "category" and labels:
        # Plotly reads ISO dates and numbers held as strings as such.
        if all(re.match(r"^-?[\d.]+$|^\d{4}-\d{2}-\d{2}", v) for v in labels):
            return []
    return labels


def fit_category_axes(fig, width: int) -> None:
    """Give a static figure's categorical axes room for their labels.

    In a browser a crowded axis is read by hovering; on paper its labels run
    into each other. A categorical x axis whose widest label does not fit its
    slot is turned to 45 degrees (90 when the slots are narrower than a line),
    its wrapped labels set on one line, the font made smaller only when even
    that does not fit; the figure grows by what the turned labels take, so the
    plot keeps its height. Every categorical axis gets ``automargin``. In place.
    """
    layout = fig.layout
    base = (layout.font.size if layout.font and layout.font.size else None) or 12
    margin = layout.margin
    side = (margin.l if margin.l is not None else 80) + (margin.r if margin.r is not None else 80)
    names = {"xaxis", "yaxis"}
    for trace in fig.data:
        for letter in ("x", "y"):
            ref = getattr(trace, f"{letter}axis", None)
            if ref:
                names.add(f"{letter}axis{ref[1:]}")
    extra = 0.0
    for name in sorted(names):
        try:
            axis = layout[name]
        except (KeyError, ValueError):
            continue
        labels = _axis_labels(fig, name)
        if not labels:
            continue
        axis.automargin = True
        if name[0] != "x" or (axis.tickangle not in (None, 0)):
            continue
        size = (axis.tickfont.size if axis.tickfont and axis.tickfont.size else None) or base
        lines = [_MARKUP_RE.sub("", part).strip() for lab in labels for part in _BR_RE.split(lab)]
        widest = max((len(t) for t in lines), default=0) * _GLYPH * size
        domain = axis.domain or (0, 1)
        slot = max(1.0, (width - side) * (domain[1] - domain[0]) * 0.9) / len(labels)
        if widest + 4 <= slot:
            continue
        flat = [
            " ".join(_MARKUP_RE.sub("", p).strip() for p in _BR_RE.split(lab)) for lab in labels
        ]
        flat = [t if len(t) <= 40 else t[:39] + "\u2026" for t in flat]
        angle = -45 if slot >= 1.7 * size else -90
        if angle == -90 and slot < 1.25 * size:
            size = max(7.0, slot / 1.25)
        if axis.ticktext is not None and len(axis.ticktext):
            axis.ticktext = flat
        elif any(_BR_RE.search(lab) for lab in labels) or flat != labels:
            axis.tickmode, axis.tickvals, axis.ticktext = "array", labels, flat
        axis.tickangle = angle
        axis.tickfont.size = size
        reach = max(len(t) for t in flat) * _GLYPH * size * (0.71 if angle == -45 else 1.0)
        extra = max(extra, reach - 2 * size)
    if extra > 0 and layout.height:
        layout.height = int(layout.height + min(extra, 240))


def figure_png(fig) -> str | None:
    """The figure as a base64 PNG (kaleido), or ``None`` when it cannot be drawn.

    In the report's type (Inter, then the system's sans), like the page around
    it. The figure's own layout width:height ratio holds when the layout sets
    both (``figure_ratio``), so a tile drawn wide and short on the dashboard
    prints wide and short instead of stretched to a default height.
    """
    try:
        import plotly.graph_objects as go

        fig = go.Figure(fig)
        fig.update_layout(font_family=_theme.sans_stack())
        width = _STATIC_WIDTH["px"]
        ratio = figure_ratio(fig)
        if ratio:
            fig.layout.width = width
            fig.layout.height = int(width / ratio)
        if not getattr(fig.layout, "height", None):
            fig.layout.height = 420
        fit_category_axes(fig, width)
        data = fig.to_image(format="png", width=width, height=int(fig.layout.height), scale=3)
    except Exception:  # noqa: BLE001 - no kaleido, no browser: the figure is left out
        return None
    return base64.b64encode(data).decode("ascii")


#: Columns a table keeps on a portrait page. The PDF turns the page for more
#: (``typst.table``); the HTML report's static table truncates here.
STATIC_TABLE_COLS = 8
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def html_text(markup: str) -> str:
    """Markup as one line of its text: what a static page keeps of an HTML-only tile."""
    text = _html.unescape(_TAG_RE.sub(" ", markup or ""))
    # A closing tag before punctuation ("<a>live dashboard</a>.") leaves no
    # space before it in the text.
    return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", " ".join(text.split()))


_SPACE_BEFORE_PUNCT_RE = re.compile(r" ([.,;:!?)])")


def table_markdown(df: pl.DataFrame, limit: int = STATIC_TABLE_ROWS) -> str:
    """A pipe table of the first ``limit`` rows, for a static page."""

    def cell(v: Any) -> str:
        text = "" if v is None else str(v)
        return text.replace("|", "\\|").replace("\n", " ")[:60]

    dropped = max(0, df.width - STATIC_TABLE_COLS)
    df = df.select(df.columns[:STATIC_TABLE_COLS]) if dropped else df
    cols = df.columns
    lines = [
        "| " + " | ".join(cell(c) for c in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in df.head(limit).iter_rows():
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    notes = []
    if df.height > limit:
        notes.append(f"first {limit} of {df.height:,} rows")
    if dropped:
        notes.append(f"first {STATIC_TABLE_COLS} of {STATIC_TABLE_COLS + dropped} columns")
    if notes:
        lines.append("")
        lines.append(f"*{'; '.join(notes).capitalize()}; the HTML report has the whole table.*")
    return "\n".join(lines)


# Advanced-viz kinds whose figure a Celery compute builds. Informational only:
# the ``component_figure`` endpoint decides per tile, building on the server
# every kind it has a builder for (these, plus the registered Python builders)
# and reading the rest off the React renderer, or snapshotting it.
SERVER_PLOTLY_KINDS = frozenset({"complex_heatmap", "upset_plot", "sankey"})

_HEX6_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_RGB_PREFIX_RE = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _hex_with_alpha(color: str | None, alpha: float) -> str:
    """Tint ``color`` to ``alpha``, mirroring the card strips' own
    ``hexWithAlpha`` (``depictio-react-core``'s ``metrics/format.ts``) so a
    card's secondary visualisation is tinted with its *own* accent colour
    instead of a fixed blue. Same teal fallback for a missing/unrecognised
    colour, so an unstyled card still reads as intentional.
    """
    fallback = f"rgba(69, 184, 172, {alpha})"
    if not color:
        return fallback
    m = _RGB_PREFIX_RE.match(color)
    if m:
        r, g, b = m.groups()
        return f"rgba({r}, {g}, {b}, {alpha})"
    cleaned = color.lstrip("#").strip()
    if not _HEX6_RE.match(cleaned):
        return fallback
    r, g, b = (int(cleaned[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _normalize_colors(obj: Any) -> Any:
    """``theme.normalize_colors``: a renderer's 8-digit hex as Python plotly's rgba."""
    return _theme.normalize_colors(obj)


def _figure_from_dict(fig_dict: dict[str, Any]):
    import plotly.graph_objects as go
    import plotly.io as pio

    # The figure is Plotly.js's own JSON, extracted from the live React
    # renderer; the schema it validates against there can be a little ahead
    # of the Python plotly package pinned here (e.g. a newer `legend`
    # property JS accepts and Python doesn't yet). skip_invalid drops what
    # Python's schema doesn't recognise rather than losing the whole figure
    # over one cosmetic property it has no way to honour anyway.
    fig_dict = _normalize_colors(fig_dict)
    try:
        return pio.from_json(json.dumps(fig_dict), skip_invalid=True)
    except Exception:
        return go.Figure(fig_dict, skip_invalid=True)


# plotly.js is a 5 MB library, and a figure's HTML asks for it by default.
# Quarto's ``embed-resources`` then inlines that request once per figure, so a
# report with 35 figures carried 35 copies of the library and came to 170 MB
# for 2.5 MB of data. The library belongs to the document, not to the figure:
# the export's setup cell activates plotly's ``notebook`` renderer, which emits
# one copy for the whole document, and JupyterLab loads its own — so a figure
# here only ever needs its own div.
PLOTLY_JS = False

# Plotly's notebook renderer hard-codes a MathJax CDN tag onto every figure it
# draws (``HtmlRenderer.to_mimebundle``: ``include_mathjax = "cdn"``), for TeX
# in axis titles. ``embed-resources`` inlines it, MathJax then lazy-loads
# ``[MathJax]/extensions/MathZoom.js`` from a path that is not in the file, and
# the reader of a supposedly self-contained report gets a "failed to load".
_MATHJAX_TAG_RE = re.compile(r'\s*<script src="[^"]*mathjax[^"]*"></script>', re.IGNORECASE)


def use_document_renderer() -> bool:
    """Draw figures once per document rather than once per figure.

    Activates plotly's ``notebook`` renderer, which emits one copy of
    plotly.js for the whole notebook instead of one per figure, and drops the
    MathJax request it would otherwise put on each of them: a dashboard
    figure's labels are data, never TeX.

    Returns whether the renderer was activated: it needs IPython, so a plain
    Python process (a script, a test) gets ``False`` and keeps plotly's default.
    """
    import plotly.io as pio

    if static_figures():
        # A page with no browser (the PDF): every bare figure is a PNG, in the
        # document's look, and no plotly.js is emitted for it to ignore.
        try:
            png = pio.renderers["png"]
            if not getattr(png, "_dpx_theme", False):
                png.width, png.scale = STATIC_FIGURE_WIDTH, 3
                inner_png = png.to_mimebundle

                def static_bundle(fig_dict, _inner=inner_png, _png=png):
                    import plotly.graph_objects as go

                    themed = _theme.apply_theme(fig_dict)
                    themed.setdefault("layout", {}).setdefault("font", {})["family"] = (
                        _theme.sans_stack()
                    )
                    fig = go.Figure(themed)
                    if not fig.layout.height:
                        fig.layout.height = 500  # kaleido's own default
                    _png.width = _STATIC_WIDTH["px"]
                    fit_category_axes(fig, _png.width)
                    return _inner(fig.to_dict())

                png.to_mimebundle = static_bundle
                png._dpx_theme = True
            pio.renderers.default = "png"
        except (KeyError, ValueError, ImportError):
            return False
        return True

    try:
        renderer = pio.renderers["notebook"]
    except (KeyError, ValueError):
        return False

    if not getattr(renderer, "_dpx_no_mathjax", False):
        inner = renderer.to_mimebundle

        def to_mimebundle(fig_dict, _inner=inner):
            # The document's look (Paper by default), applied where every
            # figure displayed bare passes: code-mode figures, the funnel.
            themed = _theme.apply_theme(fig_dict)
            bundle = _inner(themed)
            html = bundle.get(HTML_MIME)
            if isinstance(html, str):
                bundle[HTML_MIME] = _MATHJAX_TAG_RE.sub("", html)
            if static_figures():
                import plotly.graph_objects as go

                png = figure_png(go.Figure(themed))
                if png:
                    bundle[PNG_MIME] = png
            return bundle

        renderer.to_mimebundle = to_mimebundle
        renderer._dpx_no_mathjax = True

    try:
        pio.renderers.default = "notebook"
    except (ImportError, ValueError):
        return False
    # Plotly emits the library lazily, with the first figure displayed through
    # its renderer. Figures a component displays never go through it (their
    # bundle is built here), so a document whose figures all come from
    # Depictio carried no plotly.js at all and drew every one of them blank.
    # Emit it now, in this cell, ahead of every figure; plotly then drops the
    # renderer from its pending list, so a bare figure later adds no copy.
    try:
        from plotly.io._base_renderers import MimetypeRenderer

        pio.renderers._activate_pending_renderers(cls=MimetypeRenderer)
    except Exception:  # noqa: BLE001 - the lazy path still covers bare figures
        pass
    return True


# Whether tables draw through itables (DataTables: sort, search, pages), set by
# ``init_tables`` once the document has loaded the library.
_TABLES = {"interactive": False}

# Rows per page of an interactive table; every requested row is in it.
TABLE_PAGE_LENGTH = 25


def init_tables() -> bool:
    """Draw tables as sortable, searchable, paginated tables for the whole document.

    Uses ``itables`` in offline mode: DataTables is inlined once into the
    document (``connected=False``), so a self-contained report keeps working
    with no network. Needs a running kernel and ``itables`` installed; returns
    whether it is on. Without it, tables are plain HTML with every row.
    """
    if static_figures():
        return False  # a static page gets markdown tables (``table_markdown``)
    try:
        from IPython import get_ipython

        if get_ipython() is None:
            return False
        import itables

        itables.init_notebook_mode(all_interactive=False, connected=False)
    except Exception:  # noqa: BLE001 - plain HTML tables are the fallback
        return False
    _TABLES["interactive"] = True
    return True


_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def chip_columns(
    df: pl.DataFrame, colors: dict[str, dict[str, str]] | None
) -> dict[str, dict[str, str]]:
    """``{column: {value: colour}}`` for the columns of ``df`` the dashboard
    colours: pinned colours only (``#rrggbb``), as the dashboard's table and
    filters wear them. A value it lists no colour for stays plain text."""
    out: dict[str, dict[str, str]] = {}
    for column, values in (colors or {}).items():
        if column not in df.columns or not isinstance(values, dict):
            continue
        if df.schema[column].is_numeric():
            continue
        pinned = {
            str(k): str(v)
            for k, v in values.items()
            if k != "*" and isinstance(v, str) and _HEX_COLOUR.match(v)
        }
        if pinned:
            out[column] = pinned
    return out


def chip_html(value: Any, colour: str | None) -> str:
    """One value as the report's chip: tinted with its colour, a dot before it."""
    text = _esc(value)
    if not colour:
        return text
    return f'<span class="dpx-chip" style="--dpx-chip:{colour}">{text}</span>'


def _chipped(df: pl.DataFrame, chips: dict[str, dict[str, str]]) -> pl.DataFrame:
    """``df`` with its text as HTML: the coloured columns as chips, every
    other text escaped (the table is read as HTML once any cell is)."""
    exprs = []
    for column in df.columns:
        if column in chips:
            colours = chips[column]
            exprs.append(
                pl.col(column)
                .cast(pl.Utf8)
                .map_elements(lambda v, c=colours: chip_html(v, c.get(v)), return_dtype=pl.Utf8)
                .alias(column)
            )
        elif df.schema[column] == pl.Utf8:
            exprs.append(
                pl.col(column).map_elements(lambda v: _esc(v), return_dtype=pl.Utf8).alias(column)
            )
    return df.with_columns(exprs) if exprs else df


def data_html(df: pl.DataFrame, colors: dict[str, dict[str, str]] | None = None) -> str:
    """A DataFrame as HTML with every row it holds (not Polars' 10-row head/tail).

    An interactive table when ``init_tables`` turned itables on; the frame
    is never downsampled (``maxBytes=0``): the cell already holds the rows the
    tile asked for. A column the dashboard colours (``colors``, its
    ``category_colors``) shows its values as chips; DataTables sorts and
    searches them by their text.
    """
    if _TABLES["interactive"]:
        try:
            from itables import to_html_datatable

            chips = chip_columns(df, colors)
            return to_html_datatable(
                _chipped(df, chips) if chips else df,
                connected=False,
                pageLength=TABLE_PAGE_LENGTH,
                lengthMenu=[10, 25, 50, 100],
                maxBytes=0,
                classes="display compact",
                **({"allow_html": True} if chips else {}),
            )
        except Exception:  # noqa: BLE001 - fall through to plain HTML
            pass
    with pl.Config(tbl_rows=max(df.height, 1), tbl_cols=-1, fmt_str_lengths=200):
        return df._repr_html_()


# What an error may say once it is written into a document that travels: its
# first line, without the paths of the machine that raised it. A worker's
# Playwright error once put `/opt/pw-browsers/chromium_headless_shell-…` and
# an install banner into every report it rendered.
_ABS_PATH = re.compile(
    r"(?<![\w:/.])(?:/(?:[\w.+-]+/)+[\w.+-]*|[A-Za-z]:\\(?:[\w.+ -]+\\)*[\w.+-]*)"
)
_BANNER = re.compile(r"[\u2500-\u257f]")


def public_reason(text: str, limit: int = 300) -> str:
    """``text`` as a reader of an exported file may see it.

    The first line only (stack traces and install banners stay in the logs),
    absolute filesystem paths replaced by ``<path>``, at most ``limit``
    characters. URLs keep their paths: ``https://host/x`` is not a file.
    """
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _BANNER.search(ln)]
    first = lines[0] if lines else "unavailable"
    first = _ABS_PATH.sub("<path>", first)
    return first if len(first) <= limit else first[: limit - 1] + "\u2026"


class TableView:
    """A DataFrame displayed whole: what a table tile shows (``show_table``)."""

    def __init__(
        self,
        df: pl.DataFrame,
        title: str | None = None,
        colors: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.df = df
        self.title = title
        self.colors = colors

    def _repr_html_(self) -> str:
        return data_html(self.df, self.colors)

    def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
        bundle = {HTML_MIME: self._repr_html_(), PLAIN_MIME: repr(self.df)}
        if static_figures():
            bundle[MARKDOWN_MIME] = _typst.table(
                self.df,
                orientation=page_orientation(),
                chips=chip_columns(self.df, self.colors),
            )
        return bundle

    def __repr__(self) -> str:
        return repr(self.df)


def show_table(
    df: pl.DataFrame,
    title: str | None = None,
    colors: dict[str, dict[str, str]] | None = None,
) -> TableView:
    """Display ``df`` with every row, as an interactive table when available.
    ``colors`` (``{column: {value: colour}}``, the dashboard's category
    colours) shows those columns' values as coloured chips."""
    return TableView(df, title, colors)


def figure_bundle(fig) -> dict[str, Any]:
    """A mimebundle Jupyter and Quarto both render.

    Plotly's own ``_repr_mimebundle_`` is empty unless a mimetype renderer is
    active, which is not the case in every kernel; building the bundle here
    keeps the figure interactive wherever ``application/vnd.plotly.v1+json``
    is understood and falls back to inline HTML elsewhere. The figure wears
    the document's look (``theme.use_theme``), as the app's chrome restyles
    every figure it draws.
    """
    fig = _theme.apply_to_figure(fig)
    bundle: dict[str, Any] = {
        PLOTLY_MIME: json.loads(fig.to_json()),
        HTML_MIME: fig.to_html(full_html=False, include_plotlyjs=PLOTLY_JS),
        PLAIN_MIME: "Plotly figure",
    }
    if static_figures():
        png = figure_png(fig)
        if png:
            bundle[PNG_MIME] = png
            # A figure wider than a portrait page prints on a landscape one:
            # typst carrying the dpx-wide mark, read by the preamble's show
            # rule. Portrait figures stay on the image path above. The
            # caption is the float's, so the block carries none.
            orientation = figure_orientation(figure_ratio(fig), page_orientation())
            if orientation == "landscape":
                typst = _typst.figure(png, orientation=orientation)
                if typst:
                    bundle[MARKDOWN_MIME] = typst
    return bundle


def _decode_data_uri(uri: str) -> bytes:
    return base64.b64decode(uri.split(",", 1)[1] if "," in uri else uri)


def snapshot_html(image_uri: str, title: str, live_url: str | None, note: str = "") -> str:
    """A PNG snapshot of a tile, captioned as one.

    Used for renderers that are not Plotly (SVG, canvas, WebGL, the genome
    browser): the picture is the real renderer's, but nothing in it can be
    hovered or zoomed, and the caption says so rather than letting it pass for
    the live tile.
    """
    link = (
        f'<a href="{_esc(live_url, quote=True)}">live dashboard</a>'
        if live_url
        else "live dashboard"
    )
    extra = f" {_esc(note)}" if note else ""
    return (
        '<figure class="dpx-snapshot" style="margin:0.25rem 0 0.75rem">'
        f'<img src="{_esc(image_uri, quote=True)}" alt="{_esc(title, quote=True)}" '
        'style="max-width:100%;height:auto;border:1px solid #e9ecef;border-radius:8px">'
        '<figcaption style="font-size:12px;color:#868e96;margin-top:4px">'
        f"Static snapshot; interactive in the {link}.{extra}</figcaption></figure>"
    )


def snapshot_bundle(
    image_uri: str, title: str, live_url: str | None, note: str = ""
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        HTML_MIME: snapshot_html(image_uri, title, live_url, note),
        PLAIN_MIME: f"{title} (static snapshot)",
    }
    if image_uri.startswith("data:image/png;base64,"):
        bundle["image/png"] = image_uri.split(",", 1)[1]
    return bundle


def filters_to_metadata(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``filter_metadata`` shape (``clean_filter_payload``) from state filters."""
    out = []
    for f in filters or []:
        meta = f.get("metadata") or {}
        column = f.get("column_name") or meta.get("column_name")
        if not column or f.get("value") in (None, [], ""):
            continue
        entry = {
            "interactive_component_type": f.get("interactive_component_type")
            or meta.get("interactive_component_type"),
            "column_name": column,
            "value": f.get("value"),
        }
        fexpr = f.get("filter_expr") or meta.get("filter_expr")
        if fexpr:
            entry["filter_expr"] = fexpr
        out.append(entry)
    return out


def pin_body(state: dict[str, Any]) -> dict[str, Any]:
    """``AnalysisState.pins`` as the keys a render body takes (``dataVersionBody``)."""
    pins = state.get("pins") or {}
    out: dict[str, Any] = {}
    if pins.get("as_of_version"):
        out["as_of_version"] = pins["as_of_version"]
    if pins.get("data_versions"):
        out["data_versions"] = dict(pins["data_versions"])
    if pins.get("definition_version"):
        out["definition_version"] = pins["definition_version"]
    return out


def _render_groups(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The saved groups as the render endpoints take them (``groupsRenderPayload``)."""
    out = []
    for g in state.get("groups") or []:
        if not g.get("values"):
            continue
        out.append(
            {
                "name": g.get("name"),
                "column_name": g.get("column_name"),
                "values": list(g.get("values") or []),
                "color": g.get("color"),
                "dc_id": g.get("dc_id"),
            }
        )
    return out


def figure_group_body(
    state: dict[str, Any], category_colors: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    """The grouping keys of a ``render_figure`` body, as the viewer sends them.

    Mirrors ``renderFigure`` in ``depictio-react-core/src/api.ts``: groups win
    over a column override, ``grouping_display`` rides along only with one of
    them, and nothing is sent when the state is ungrouped, so an ungrouped
    request stays byte-identical. A column override's colour map is the
    dashboard's own category colours for that column when it has some (the
    viewer builds it from the column's palette); without one the server
    declines to facet, as it does for the viewer.
    """
    color_by = state.get("color_by") or {}
    kind = color_by.get("kind") or "none"
    body: dict[str, Any] = {}
    groups = _render_groups(state)
    if kind == "groups" and groups:
        body = {"groups": groups, "color_by_group": True}
        if state.get("show_other") is False:
            body["include_other"] = False
    elif kind == "column" and color_by.get("column_name"):
        column = str(color_by["column_name"])
        spec: dict[str, Any] = {"column_name": column}
        color_map = (category_colors or {}).get(column)
        if color_map:
            spec["color_map"] = dict(color_map)
        body = {"color_by_column": spec}
    if body and state.get("display_mode") == "facet":
        body["grouping_display"] = "facet"
    return body


def card_group_body(state: dict[str, Any]) -> dict[str, Any]:
    """The comparison keys of a ``bulk_compute_cards`` body (``bulkComputeCards``)."""
    groups = _render_groups(state)
    if not (state.get("compare_in_cards") and groups):
        return {}
    body: dict[str, Any] = {"groups": groups, "compare_groups": True}
    if state.get("show_other") is False:
        body["include_other"] = False
    if state.get("show_overall") is False:
        body["include_overall"] = False
    return body


class DepictioComponent:
    """One dashboard component, bound to a client and an analysis state."""

    default_display: str = "html"  # figure | data | html | markdown

    def __init__(
        self,
        client: DepictioClient,
        dashboard_id: str,
        meta: dict[str, Any],
        state: dict[str, Any],
        theme: str = "light",
    ) -> None:
        self.client = client
        self.dashboard_id = dashboard_id
        self.meta = meta
        self.state = state
        self.theme = theme
        self._figure = None
        self._data: Any = None
        self._html: str | None = None

    # ------------------------------------------------------------ identity
    @property
    def index(self) -> str:
        return str(self.meta.get("index") or "")

    @property
    def title(self) -> str:
        """The tile's name: its title, else what it shows (a MultiQC plot or
        module, a column), never its index (a UUID means nothing to a reader)."""
        title = str(self.meta.get("title") or "").strip()
        if title:
            return title
        return (
            readable_name(
                self.meta.get("selected_plot")
                or self.meta.get("selected_module")
                or self.meta.get("column_name")
            )
            or readable_name(self.component_type)
            or "This tile"
        )

    @property
    def component_type(self) -> str:
        return str(self.meta.get("component_type") or "")

    @property
    def dc_id(self) -> str | None:
        return str(self.meta.get("dc_id") or "") or None

    @property
    def filters(self) -> list[dict[str, Any]]:
        return list(self.state.get("filters") or [])

    @property
    def pins(self) -> dict[str, Any]:
        """The state's time travel as render-body keys; empty for a live view.

        Both halves together, as every render needs them: the data pins
        (``as_of_version`` / ``data_versions``) and ``definition_version``.
        """
        return pin_body(self.state)

    def __repr__(self) -> str:
        return f"<DepictioComponent {self.component_type} {self.title!r} ({self.index})>"

    def _category_colors(self) -> dict[str, dict[str, str]]:
        """The dashboard's colour per category value, when the colour-by needs it."""
        if ((self.state.get("color_by") or {}).get("kind") or "none") != "column":
            return {}
        return self.client.category_colors(self.dashboard_id)

    def pinned_colors(self, column: str | None) -> dict[str, str] | None:
        """The colours the dashboard pins for ``column``, with the component's
        own ``category_palettes`` for it laid over value by value
        (``columnCategoryColors`` / ``pinnedPalette`` in the app). ``None``
        when nothing is pinned: the renderer keeps its own palette."""
        if not column:
            return None
        merged: dict[str, str] = {}
        cfg = self.meta.get("config") if isinstance(self.meta.get("config"), dict) else {}
        own = (cfg.get("category_palettes") or {}) if isinstance(cfg, dict) else {}
        for layer in (self.client.category_colors(self.dashboard_id).get(column), own.get(column)):
            if not isinstance(layer, dict):
                continue
            for value, colour in layer.items():
                if str(value) != "*" and isinstance(colour, str) and colour:
                    merged[str(value)] = colour
        return merged or None

    # ------------------------------------------------------------- fetching
    def _fetch_figure(self):
        raise AttributeError(f"a {self.component_type} component has no figure")

    def _fetch_data(self) -> Any:
        raise AttributeError(f"a {self.component_type} component has no data payload")

    def _fetch_html(self) -> str:
        resp = self.client.post(
            f"/dashboards/embed/{self.dashboard_id}/{self.index}",
            {"state": self.state, "theme": self.theme},
            raw=True,
        )
        return resp.text

    @property
    def figure(self):
        if self._figure is None:
            self._figure = self._fetch_figure()
        return self._figure

    @property
    def data(self) -> Any:
        if self._data is None:
            self._data = self._fetch_data()
        return self._data

    @property
    def html(self) -> str:
        if self._html is None:
            self._html = self._fetch_html()
        return self._html

    def refresh(self) -> DepictioComponent:
        self._figure, self._data, self._html = None, None, None
        return self

    # -------------------------------------------------------------- display
    def _iframe(self, doc: str, height: int = 480) -> str:
        return (
            f'<iframe srcdoc="{_esc(doc, quote=True)}" '
            f'style="width:100%;height:{height}px;border:0" '
            'sandbox="allow-scripts allow-same-origin" title="Depictio component"></iframe>'
        )

    @property
    def live_url(self) -> str | None:
        """The live dashboard this tile belongs to, on the instance it came from."""
        base = getattr(self.client, "base_url", "") or ""
        return f"{base}/dashboard/{self.dashboard_id}" if base else None

    def _live_link(self, text: str = "Open the live dashboard") -> str:
        url = self.live_url
        if not url:
            return ""
        return f'<a href="{_esc(url, quote=True)}">{_esc(text)}</a>'

    def _placeholder_html(self, reason: str) -> str:
        """What a tile shows when it cannot be drawn: its title, why, and where it lives.

        A report is a document a reader trusts end to end; one tile that cannot
        be fetched (an instance without JBrowse, a renderer that timed out, a
        table over the export cap) must cost that tile, never the document.
        """
        link = self._live_link()
        return (
            '<div class="dpx-unavailable" data-dpx-unavailable="1" style="border:1px dashed '
            "#adb5bd;border-radius:8px;padding:10px 14px;margin:4px 0;font-size:13px;"
            'color:#495057">'
            f"<b>{_esc(self.title)}</b> could not be drawn in this report."
            f'<div style="margin-top:4px;color:#868e96">{_esc(reason)}</div>'
            '<div style="margin-top:6px;font-size:12px">'
            + (f"{link} · " if link else "")
            + "re-run this cell, or call <code>.refresh()</code> on the component, to try again"
            "</div></div>"
        )

    @staticmethod
    def _reason(exc: BaseException) -> str:
        return public_reason(str(exc).strip() or type(exc).__name__)

    def _display_html(self) -> str:
        """HTML for the default display; subclasses override for lighter renderings."""
        return self._iframe(self.html)

    def _display_markdown(self) -> str | None:
        return None

    def _bundle(self) -> dict[str, Any]:
        mode = self.default_display
        if mode == "figure":
            return figure_bundle(self.figure)
        if mode == "data":
            df = self.data
            if isinstance(df, pl.DataFrame):
                out = {HTML_MIME: data_html(df), PLAIN_MIME: repr(df)}
                if static_figures():
                    out[MARKDOWN_MIME] = _typst.table(df)
                return out
            return {PLAIN_MIME: repr(df)}
        if mode == "markdown":
            return {MARKDOWN_MIME: self._display_markdown() or "", PLAIN_MIME: self.title}
        return {HTML_MIME: self._display_html(), PLAIN_MIME: repr(self)}

    def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
        """The Jupyter kernel's display hook (what Quarto renders from).

        Never raises: a failure becomes a visible placeholder carrying the
        reason. Asking for ``.figure`` / ``.data`` explicitly still raises.
        """
        try:
            bundle = self._bundle()
            if static_figures() and set(bundle) <= {HTML_MIME, PLAIN_MIME}:
                # A card, a placeholder: what a static page keeps is its text.
                text = html_text(str(bundle.get(HTML_MIME) or ""))
                if text:
                    bundle = {**bundle, MARKDOWN_MIME: text}
            return bundle
        except Exception as exc:  # noqa: BLE001 - a tile must never break the document
            reason = self._reason(exc)
            out = {
                HTML_MIME: self._placeholder_html(reason),
                PLAIN_MIME: f"{self.title} could not be drawn in this report ({reason}).",
            }
            if static_figures():
                out[MARKDOWN_MIME] = _typst.note(
                    f"{self.title} could not be drawn in this report.",
                    "The HTML report and the live dashboard show it.",
                )
            return out

    def _repr_html_(self) -> str | None:
        try:
            bundle = self._bundle()
        except Exception as exc:  # noqa: BLE001 - same contract as _repr_mimebundle_
            return self._placeholder_html(self._reason(exc))
        if HTML_MIME in bundle:
            return str(bundle[HTML_MIME])
        if MARKDOWN_MIME in bundle:
            return None
        return f"<pre>{_esc(str(bundle.get(PLAIN_MIME, '')), multiline=True)}</pre>"

    def show(self) -> Any:
        """Display now (``IPython.display.display`` when available)."""
        try:
            from IPython.display import display

            display(self)
        except Exception:
            print(repr(self))
        return self


# ---------------------------------------------------------------------------
# Figures the server already renders as Plotly
# ---------------------------------------------------------------------------


class FigureComponent(DepictioComponent):
    default_display = "figure"

    def _fetch_figure(self):
        payload = self.client.post(
            f"/dashboards/render_figure/{self.dashboard_id}/{self.index}",
            {
                "filters": self.filters,
                "theme": self.theme,
                "full_load": False,
                **figure_group_body(self.state, self._category_colors()),
                **self.pins,
            },
        )
        return _figure_from_dict(payload["figure"])


class MapComponent(FigureComponent):
    def _fetch_figure(self):
        payload = self.client.post(
            f"/dashboards/render_map/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "theme": self.theme, **self.pins},
        )
        return _figure_from_dict(payload["figure"])

    def _fetch_data(self) -> pl.DataFrame:
        payload = self.client.post(
            f"/dashboards/map_data/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, **self.pins},
        )
        return pl.DataFrame(payload.get("rows") or {})


class MultiQCComponent(FigureComponent):
    """A MultiQC plot; the server may answer 202 while its cache warms."""

    def _fetch_figure(self):
        deadline = time.monotonic() + 300
        while True:
            resp = self.client.post(
                f"/dashboards/render_multiqc/{self.dashboard_id}/{self.index}",
                {"filters": self.filters, "theme": self.theme, **self.pins},
                raw=True,
            )
            if resp.status_code == 202:
                if time.monotonic() > deadline:
                    raise TimeoutError("MultiQC figure did not become ready in time")
                time.sleep(2)
                continue
            return _figure_from_dict(resp.json()["figure"])


# ``MultiQCGeneralStats.tsx``: the first number of a Dash ``filter_query``
# ("{col} >= 12 && {col} < 17") is a bin's floor, the second its ceiling.
_GS_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
# A bar as the server draws it: one colour up to the value's share of the cell.
_GS_BAR = re.compile(
    r"^linear-gradient\(90deg, (#[0-9a-fA-F]{3,8}) 0%, \1 (\d+(?:\.\d+)?)%, "
    r"transparent \2%, transparent 100%\)$"
)


def gs_bars(styles: list[dict[str, Any]]) -> dict[str, list[tuple[float, float, str, float]]]:
    """The General Statistics data bars by column: (floor, ceiling, colour,
    share in %) per bin, from the server's ``table_styles`` (the dashboard's
    ``indexDataBars``). A style that is not a plain bar is skipped."""
    out: dict[str, list[tuple[float, float, str, float]]] = {}
    for style in styles or []:
        cond = style.get("if") or {}
        col = cond.get("column_id")
        m = _GS_BAR.match(str(style.get("backgroundImage") or ""))
        query = re.sub(r"\{[^}]*\}", "", str(cond.get("filter_query") or ""))
        nums = _GS_NUMBER.findall(query)
        if not col or not m or not nums:
            continue
        floor = float(nums[0])
        ceiling = float(nums[1]) if len(nums) > 1 else float("inf")
        out.setdefault(str(col), []).append((floor, ceiling, m.group(1), float(m.group(2))))
    return out


def gs_bar_for(
    bins: list[tuple[float, float, str, float]] | None, value: Any
) -> tuple[str, float] | None:
    """The bar of ``value`` (colour, share in %), as ``findDataBar`` picks it:
    the bin it falls in, else the last one (a value on the global maximum)."""
    if not bins or value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    for floor, ceiling, colour, share in bins:
        if floor <= num < ceiling:
            return colour, share
    return bins[-1][2], bins[-1][3]


def gs_format(value: Any, fmt: dict[str, Any] | None) -> str:
    """A cell as the dashboard writes it (``formatCell``): the column's
    precision, thousands grouping and unit (" bp", "%", " M")."""
    if value is None or value == "":
        return ""
    if not fmt:
        return str(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    precision = int(fmt.get("precision") or 0)
    text = f"{num:,.{precision}f}" if fmt.get("group") else f"{num:.{precision}f}"
    return f"{text}{fmt.get('suffix') or ''}"


class MultiQCGeneralStatsComponent(DepictioComponent):
    default_display = "data"

    def _payload(self) -> dict[str, Any]:
        return self.client.post(
            f"/dashboards/render_multiqc_general_stats/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "theme": self.theme, **self.pins},
        )

    @staticmethod
    def _mode(payload: dict[str, Any]) -> dict[str, Any]:
        """The view the dashboard opens on: the mean of a sample's reads (one
        row per sample), else whatever the server sent."""
        modes = payload.get("modes") or {}
        return modes.get("mean") or modes.get("all") or next(iter(modes.values()), {})

    def _fetch_data(self) -> pl.DataFrame:
        self._gs_mode = self._mode(self._payload())
        return pl.DataFrame(self._gs_mode.get("table_data") or [])

    def _fetch_figure(self):
        return _figure_from_dict(self._mode(self._payload())["violin_figure"])

    def _gs_cells(self, df: pl.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
        """Per column: how its values are written, and its data bars."""
        mode = getattr(self, "_gs_mode", None) or {}
        formats = {
            str(c.get("id")): c.get("format")
            for c in mode.get("table_columns") or []
            if isinstance(c, dict) and c.get("type") == "numeric"
        }
        bars = gs_bars(mode.get("table_styles") or [])
        return formats, {c: bars[c] for c in df.columns if c in bars and c != "Sample Name"}

    def _gs_html(self, df: pl.DataFrame) -> str:
        """The table as the dashboard draws it: one row per sample, values with
        their units, each over its bar."""
        formats, bars = self._gs_cells(df)
        head = "".join(f"<th>{_esc(str(c))}</th>" for c in df.columns)
        rows = []
        for row in df.iter_rows(named=True):
            cells = []
            for c in df.columns:
                text = _esc(
                    gs_format(row[c], formats.get(c)) if c in formats else str(row[c] or "")
                )
                bar = gs_bar_for(bars.get(c), row[c])
                style = (
                    f' style="background-image:linear-gradient(90deg,{bar[0]} 0%,{bar[0]} '
                    f'{bar[1]:g}%,transparent {bar[1]:g}%)"'
                    if bar
                    else ""
                )
                cls = ' class="dpx-gs-name"' if c == "Sample Name" else ""
                cells.append(f"<td{cls}{style}>{text}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return (
            '<div class="dpx-gs-wrap"><table class="dpx-gs"><thead><tr>'
            + head
            + "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )

    def _bundle(self) -> dict[str, Any]:
        """The table the tile shows, then the violin summary drawn beside it."""
        df = self.data
        html = self._gs_html(df) if isinstance(df, pl.DataFrame) and df.height else ""
        bundle: dict[str, Any] = {PLAIN_MIME: repr(df)}
        try:
            fig = self.figure
        except Exception:  # noqa: BLE001 - a table with no numeric column has no violin
            fig = None
        if fig is not None and fig.data:
            fig = _theme.apply_to_figure(fig)
            html += fig.to_html(full_html=False, include_plotlyjs=PLOTLY_JS)
        bundle[HTML_MIME] = html
        if static_figures() and isinstance(df, pl.DataFrame):
            # A page: the table as a table, its values and bars as on the
            # dashboard (the violins stay the HTML's).
            formats, bars = self._gs_cells(df)
            bundle[MARKDOWN_MIME] = _typst.table(
                df,
                text={c: (lambda v, f=f: gs_format(v, f)) for c, f in formats.items()},
                bars={c: (lambda v, b=b: gs_bar_for(b, v)) for c, b in bars.items()},
            )
        return bundle


# ---------------------------------------------------------------------------
# Advanced visualisations
# ---------------------------------------------------------------------------


class AdvancedVizComponent(DepictioComponent):
    """An advanced visualisation: its Plotly figure, drawn here, or a snapshot.

    Three ways to the picture, the first that works:

    * the kinds the live app draws with Plotly come back as that figure (built
      on the server where it can, otherwise read off the real React renderer
      headlessly);
    * the kinds it draws with SVG, a canvas or WebGL are drawn here, from the
      data the renderer reads (``depictio.notebook.native``): a Plotly figure,
      a py3Dmol structure, SVG or HTML;
    * failing that (a renderer whose library is missing, a file the client
      cannot reach), a PNG of the server's renderer, captioned as the static
      snapshot it is. ``.image`` holds it.
    """

    default_display = "figure"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._result: dict[str, Any] | None = None
        self._native: Any = None
        # Why the native renderer did not draw this tile, when it did not.
        self.native_error: str | None = None

    @property
    def kind(self) -> str:
        return str(
            self.meta.get("viz_kind")
            or self.meta.get("kind")
            or self.meta.get("advanced_viz_kind")
            or ""
        )

    def refresh(self) -> DepictioComponent:
        self._result = None
        self._native = None
        self.native_error = None
        return super().refresh()

    def _native_result(self) -> Any:
        """The tile drawn here, or ``None`` (no renderer, its library missing, or it failed)."""
        from . import native

        if self._native is not None:
            return self._native
        if self.native_error is not None or not native.native_enabled():
            return None
        renderer = native.renderer_for(self.meta)
        if renderer is None:
            return None
        if not renderer.available():
            self.native_error = f"{renderer.requires or 'its renderer'} is not installed"
            return None
        try:
            self._native = renderer.render(native.Tile(self))
        except Exception as exc:  # noqa: BLE001 - the server's snapshot is the fallback
            self.native_error = self._reason(exc)
            return None
        return self._native

    def _render_result(self) -> dict[str, Any]:
        if self._result is None:
            self._result = self._fetch_render()
        return self._result

    def _fetch_render(self) -> dict[str, Any]:
        return self.client.poll(
            f"/dashboards/component_figure/{self.dashboard_id}/{self.index}",
            {"state": self.state, "theme": self.theme},
            "/dashboards/component_figure/jobs/{job_id}",
        )

    def _fetch_figure(self):
        drawn = self._native_result()
        if drawn is not None and drawn.figure is not None:
            return drawn.figure
        if drawn is not None:
            raise AttributeError(
                f"{self.title!r} is drawn here as HTML, not with Plotly, so it has no figure"
            )
        result = self._render_result()
        if result.get("figure"):
            return _figure_from_dict(result["figure"])
        if result.get("image"):
            raise AttributeError(
                f"{self.title!r} is not drawn with Plotly, so it has no figure; "
                "`.image` holds a PNG snapshot of it"
            )
        raise RuntimeError(f"no figure for {self.title!r}: {result.get('reason') or 'unsupported'}")

    @property
    def image(self) -> bytes | None:
        """The server's PNG snapshot, for a renderer that is not Plotly (else ``None``)."""
        uri = self._render_result().get("image")
        return _decode_data_uri(uri) if uri else None

    def _bundle(self) -> dict[str, Any]:
        drawn = self._native_result()
        if drawn is not None:
            return drawn.bundle
        result = self._render_result()
        if result.get("figure"):
            return figure_bundle(self.figure)
        if result.get("image"):
            note = f" Not drawn here: {self.native_error}." if self.native_error else ""
            return snapshot_bundle(str(result["image"]), self.title, self.live_url, note=note)
        raise RuntimeError(str(result.get("reason") or "the server returned nothing to show"))

    def _fetch_data(self) -> pl.DataFrame:
        """The rows the tile's renderer reads: every column its config binds."""
        from .native import Tile

        config = self.meta.get("config") if isinstance(self.meta.get("config"), dict) else {}
        columns: list[str] = []
        for key, value in config.items():
            if key.endswith("_col") and isinstance(value, str) and value:
                columns.append(value)
            elif key.endswith("_cols") and isinstance(value, list):
                columns.extend(v for v in value if isinstance(v, str) and v)
        if not columns and self.dc_id:
            # Nothing bound by name (a kind whose config names no column): the
            # collection's own columns, as its specs list them.
            try:
                columns = [str(s["name"]) for s in self.client.specs(self.dc_id) if s.get("name")]
            except Exception:  # noqa: BLE001 - the server then says what it needs
                columns = []
        return Tile(self).rows(columns)


# ---------------------------------------------------------------------------
# Data-shaped components
# ---------------------------------------------------------------------------


class TableComponent(DepictioComponent):
    default_display = "data"

    def _fetch_data(self) -> pl.DataFrame:
        return self.page(all_rows=True)

    def page(
        self,
        start: int = 0,
        limit: int = 500,
        *,
        sort_by: str | None = None,
        sort_dir: str = "asc",
        all_rows: bool = False,
    ) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        offset = start
        while True:
            payload = self.client.post(
                f"/dashboards/render_table/{self.dashboard_id}/{self.index}",
                {
                    "filters": self.filters,
                    "start": offset,
                    "limit": min(limit, 500),
                    "sort_by": sort_by,
                    "sort_dir": sort_dir,
                    **self.pins,
                },
            )
            rows = payload.get("rows") or []
            frames.append(pl.DataFrame(rows))
            total = int(payload.get("total") or 0)
            offset += len(rows)
            if not all_rows or not rows or offset >= total:
                break
        return (
            pl.concat([f for f in frames if f.width], how="vertical_relaxed")
            if any(f.width for f in frames)
            else pl.DataFrame()
        )


class CardComponent(DepictioComponent):
    default_display = "html"

    def _fetch_data(self) -> dict[str, Any]:
        payload = self.client.post(
            f"/dashboards/bulk_compute_cards/{self.dashboard_id}",
            {
                "filters": self.filters,
                "component_ids": [self.index],
                "include_icons": True,
                **card_group_body(self.state),
                **self.pins,
            },
        )
        return {
            "value": (payload.get("values") or {}).get(self.index),
            "secondary": (payload.get("secondary_values") or {}).get(self.index),
            "aggregations": (payload.get("aggregations") or {}).get(self.index),
            "icon_svg": (payload.get("icons") or {}).get(str(self.meta.get("icon_name") or "")),
            "filter_applied": payload.get("filter_applied"),
        }

    @property
    def value(self) -> Any:
        return self.data.get("value")

    @property
    def number_format(self) -> str | None:
        """The format the app prints this card's value in (``cardNumberFormat``):
        its ``format``, else its ``decimals`` as ``decimals:N``."""
        explicit = self.meta.get("format")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        decimals = self.meta.get("decimals")
        if isinstance(decimals, (int, float)) and not isinstance(decimals, bool):
            return f"decimals:{min(6, max(0, round(decimals)))}"
        return None

    def value_text(self, value: Any = _MISSING) -> str:
        """``value`` (the card's own by default) as the dashboard prints it:
        ``formatValue`` with the card's format, so 7.7049 reads 7.70 under
        ``decimals: 2`` and 61.52 reads 61.5 with no format at all."""
        v = self.value if value is _MISSING else value
        if v is None:
            return "–"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return _text.format_number(float(v), self.number_format)
        return str(v)

    @staticmethod
    def _fmt(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:,.4g}" if abs(value) < 1e6 else f"{value:,.0f}"
        return "–" if value is None else _esc(str(value))

    def _display_html(self) -> str:
        agg = _esc(str(self.meta.get("aggregation") or ""))
        column = _esc(str(self.meta.get("column_name") or ""))
        icon_color = str(self.meta.get("icon_color") or "#868e96")
        title_color = str(self.meta.get("title_color") or "#868e96")
        background = str(self.meta.get("background_color") or "#ffffff")
        icon_svg = self.data.get("icon_svg") or ""
        icon = (
            f'<span style="color:{_esc(icon_color)};font-size:20px;line-height:1;'
            f'position:absolute;top:12px;right:14px">{icon_svg}</span>'
            if icon_svg
            else ""
        )
        return (
            # The card's own frame, as `DepictioCard.css` draws it: a 1.5px
            # gray-2 border at radius 12, not the generic 1px box.
            # `dpx-card*` are the hooks the report's theme restyles them by.
            '<div class="dpx-card" style="position:relative;display:inline-block;min-width:180px;'
            "padding:12px 16px;border:1.5px solid #e9ecef;border-radius:12px;font-family:inherit;"
            f'background:{_esc(background)}">'
            f"{icon}"
            f'<div class="dpx-card-title" style="font-size:12px;color:{_esc(title_color)}">'
            f"{_esc(self.title)}</div>"
            '<div class="dpx-card-value" style="font-size:28px;font-weight:600;line-height:1.2">'
            f"{self._fmt(self.value)}</div>"
            f'<div style="font-size:11px;color:#adb5bd">{agg} · {column}</div>'
            f"{self._secondary_html()}</div>"
        )

    def _typst_card_(self, mono: bool = False) -> str:
        """The card on a static page: its icon, title, value, caption and
        secondary numbers (a top-N breakdown as bars, a box plot's summary,
        a coverage share), drawn by the PDF's ``dpx-kpi``."""
        accent = "#868e96" if mono else _hex_color(self._accent_color, "#868e96")
        sec = self.data.get("secondary") or {}
        layout = str(self.meta.get("secondary_layout") or "")
        secondary = None
        if layout in ("top_n", "concentration", "composition", "donut"):
            top = ((sec.get("__breakdown__") or {}).get("top")) or []
            if top:
                secondary = _typst.bars(
                    [(str(i["name"]), float(i["percent"]), f"{i['count']:,}") for i in top],
                    accent,
                )
        elif layout == "box_plot" and sec.get("box_plot_stats"):
            b = sec["box_plot_stats"]
            secondary = (
                f"dpx-range({_typst.tstr(self.value_text(b.get('min')))}, "
                f"{_typst.tstr(self.value_text(b.get('median')))}, "
                f"{_typst.tstr(self.value_text(b.get('max')))})"
            )
        elif layout == "coverage" and isinstance(self.value, (int, float)):
            top = float(self.meta.get("coverage_max") or 100) or 100.0
            frac = max(0.0, min(1.0, float(self.value) / top))
            secondary = _typst.bars([("", frac, f"{frac:.0%} of {top:g}")], accent)
        caption = str(self.meta.get("caption") or "").strip() or None
        return _typst.kpi(
            title=self.title,
            value=self.value_text(),
            caption=caption,
            icon_svg=_typst.colored_svg(self.data.get("icon_svg"), accent),
            secondary=secondary,
        )

    @property
    def _accent_color(self) -> str | None:
        """The card's own accent colour — its icon colour, falling back to
        its title colour — the same precedence ``ComponentRenderer`` uses to
        pick what it hands the React secondary-metric strips. ``None`` when
        the card carries neither, which tints strips with the same teal
        fallback the live strips use.
        """
        icon_color = self.meta.get("icon_color")
        if icon_color:
            return str(icon_color)
        title_color = self.meta.get("title_color")
        return str(title_color) if title_color else None

    def _bar(
        self,
        label: str,
        fraction: float,
        note: str = "",
        color: str | None = None,
        alpha: float = 0.75,
    ) -> str:
        pct = max(0.0, min(1.0, fraction)) * 100
        fill = _hex_with_alpha(color, alpha)
        return (
            '<div style="margin:4px 0 0;font-size:11px;color:#495057">'
            f'<div style="display:flex;justify-content:space-between">'
            f"<span>{_esc(label)}</span><span>{_esc(note)}</span></div>"
            '<div style="background:rgba(160,160,160,0.18);border-radius:3px;height:6px;margin-top:2px">'
            f'<div style="background:{fill};border-radius:3px;height:6px;width:{pct:.1f}%"></div>'
            "</div></div>"
        )

    def _box_plot_html(self, s: dict[str, Any]) -> str:
        """A static Tukey box-and-whisker plot, replicating the live card's
        ``BoxPlot.tsx`` geometry (whisker line + caps, an IQR box tinted with
        the card's own accent colour, a median line, a mean marker, outlier
        dots) as absolutely-positioned divs, which a static report keeps
        intact. The full five-number
        summary the live card keeps in a hover tooltip has no static
        equivalent; the caption row below carries min/median/max instead.
        """
        lo, hi, median = s.get("min"), s.get("max"), s.get("median")
        if lo is None or hi is None:
            return ""
        if lo == hi:
            return (
                '<div style="margin-top:4px;font-size:11px;color:#495057;text-align:center">'
                f"{self._fmt(median)} (constant)</div>"
            )
        rng = hi - lo

        def frac(v: Any) -> float:
            return 0.0 if v is None else max(0.0, min(1.0, (v - lo) / rng))

        color = self._accent_color
        track_h, box_h, cap_h, whisker_t, outlier_r = 28, 14, 10, 1.5, 2.5
        axis_y = track_h / 2
        box_top = axis_y - box_h / 2
        ink = "#111"
        f_low, f_up = frac(s.get("lower_whisker", lo)), frac(s.get("upper_whisker", hi))
        f_q1, f_q3, f_med = frac(s.get("q1")), frac(s.get("q3")), frac(median)
        f_mean = frac(s.get("mean", median))

        box = (
            f'<div style="position:absolute;left:{f_q1 * 100:.2f}%;'
            f"width:{(f_q3 - f_q1) * 100:.2f}%;top:{box_top:.1f}px;height:{box_h}px;"
            f"background:{_hex_with_alpha(color, 0.45)};"
            f'border:1px solid {_hex_with_alpha(color, 0.95)};border-radius:2px"></div>'
            if f_q3 > f_q1
            else ""
        )
        caps = "".join(
            f'<div style="position:absolute;left:{f * 100:.2f}%;top:{axis_y - cap_h / 2:.1f}px;'
            f"height:{cap_h}px;width:{whisker_t}px;margin-left:-{whisker_t / 2}px;"
            f'background:{ink};opacity:0.85"></div>'
            for f in (f_low, f_up)
        )
        outliers = "".join(
            f'<div style="position:absolute;left:{frac(v) * 100:.2f}%;'
            f"top:{axis_y - outlier_r:.1f}px;width:{outlier_r * 2}px;height:{outlier_r * 2}px;"
            f"margin-left:-{outlier_r}px;border-radius:50%;background:rgba(127,127,127,0.85);"
            f'border:0.5px solid {ink}"></div>'
            for v in (s.get("outliers") or [])[:100]
        )
        plot = (
            f'<div style="width:100%;position:relative;height:{track_h}px;margin-top:6px">'
            f'<div style="position:absolute;left:{f_low * 100:.2f}%;'
            f"width:{max(0.0, f_up - f_low) * 100:.2f}%;top:{axis_y - whisker_t / 2:.2f}px;"
            f'height:{whisker_t}px;background:{ink};opacity:0.7"></div>'
            f"{caps}{box}"
            f'<div style="position:absolute;left:{f_med * 100:.2f}%;top:{box_top:.1f}px;'
            f'height:{box_h}px;width:2px;margin-left:-1px;background:{ink}"></div>'
            f'<div style="position:absolute;left:{f_mean * 100:.2f}%;top:{axis_y - 5:.1f}px;'
            f"margin-left:-4px;width:0;height:0;border-left:4px solid transparent;"
            f'border-right:4px solid transparent;border-bottom:6px solid #E74C3C"></div>'
            f"{outliers}</div>"
        )
        caption = (
            '<div style="display:flex;justify-content:space-between;font-size:10px;'
            'color:#495057;margin-top:2px">'
            f"<span>{self._fmt(lo)}</span>"
            f'<span style="font-weight:600">{self._fmt(median)}</span>'
            f"<span>{self._fmt(hi)}</span></div>"
        )
        tail = (
            f'<div style="font-size:10px;color:#adb5bd">{s["outlier_count"]:,} outlier(s)</div>'
            if s.get("outlier_count")
            else ""
        )
        return plot + caption + tail

    def _secondary_html(self) -> str:
        """The card's secondary visualization, from the same numbers the React
        renderer draws (``bulk_compute_cards``' ``secondary_values``), not a
        reconstruction: a top-N breakdown, a box plot's five-number summary, a
        histogram, a pass/warn/fail count, a trend sparkline... The exact
        chrome differs from the dashboard's chart, but every number in it is
        the one Depictio computed, keyed by ``secondary_layout``.
        """
        layout = str(self.meta.get("secondary_layout") or "")
        sec = self.data.get("secondary") or {}
        if layout in ("top_n", "concentration", "composition", "donut"):
            breakdown = sec.get("__breakdown__")
            if not breakdown:
                return ""
            rows = "".join(
                self._bar(
                    item["name"],
                    item["percent"],
                    f"{item['count']:,} ({item['percent']:.0%})",
                    self._accent_color,
                )
                for item in breakdown.get("top") or []
            )
            return rows
        if layout == "box_plot":
            s = sec.get("box_plot_stats")
            if not s:
                return ""
            return self._box_plot_html(s)
        if layout == "histogram":
            h = sec.get("__histogram__")
            bins = (h or {}).get("bins") or []
            if not bins:
                return ""
            peak = max(bins) or 1
            fill = _hex_with_alpha(self._accent_color, 0.8)
            bars = "".join(
                f'<div style="flex:1;background:{fill};height:{c / peak * 24:.0f}px;'
                f'align-self:flex-end;margin:0 1px" title="{c:,}"></div>'
                for c in bins
            )
            return (
                '<div style="margin-top:6px;display:flex;align-items:flex-end;height:24px">'
                f"{bars}</div>"
                f'<div style="font-size:10px;color:#adb5bd">'
                f"{self._fmt(h['min'])} – {self._fmt(h['max'])}</div>"
            )
        if layout == "trend":
            t = sec.get("__trend__")
            points = (t or {}).get("points") or []
            values = [p["value"] for p in points]
            if len(values) < 2:
                return ""
            lo, hi = min(values), max(values)
            span = (hi - lo) or 1
            width, height = 120, 28
            step = width / (len(values) - 1)
            poly = " ".join(
                f"{i * step:.1f},{height - (v - lo) / span * height:.1f}"
                for i, v in enumerate(values)
            )
            change = t.get("change")
            note = f"{change:+.0%}" if change is not None else ""
            stroke = _hex_with_alpha(self._accent_color, 0.9)
            return (
                f'<div style="margin-top:6px"><svg width="{width}" height="{height}">'
                f'<polyline points="{poly}" fill="none" stroke="{stroke}" stroke-width="1.5"/></svg>'
                f'<div style="font-size:10px;color:#adb5bd">{_esc(note)}</div></div>'
            )
        if layout == "threshold":
            th = sec.get("__threshold__")
            if not th:
                return ""
            warn = (
                f' · <span style="color:#f08c00">{th["warning"]:,} warn</span>'
                if th.get("warning")
                else ""
            )
            return (
                '<div style="margin-top:4px;font-size:11px">'
                f'<span style="color:#2f9e44">{th["passing"]:,} pass</span>{warn} · '
                f'<span style="color:#e03131">{th["failing"]:,} fail</span></div>'
            )
        if layout == "completeness":
            c = sec.get("__completeness__")
            if not c:
                return ""
            return self._bar(
                "Filled",
                c["fill_rate"],
                f"{c['filled']:,}/{c['total']:,}",
                self._accent_color,
                0.85,
            )
        if layout == "uniqueness":
            u = sec.get("__uniqueness__")
            if not u:
                return ""
            return self._bar(
                "Distinct",
                u["unique_rate"],
                f"{u['distinct']:,}/{u['measured']:,}",
                self._accent_color,
                0.85,
            )
        if layout == "attrition":
            a = sec.get("__attrition__")
            if not a:
                return ""
            color = self._accent_color
            return "".join(
                self._bar(
                    s["name"], s["share"], f"{s['value']:,.0f}", color, max(0.35, 0.85 - i * 0.12)
                )
                for i, s in enumerate(a.get("stages") or [])
            )
        if layout in ("coverage", "gauge"):
            cap = self.meta.get("coverage_max")
            value = self.value
            if not isinstance(cap, (int, float)) or not cap or not isinstance(value, (int, float)):
                return ""
            return self._bar(layout.capitalize(), value / cap, f"/{cap:,}", self._accent_color, 0.8)
        if layout in ("vertical", "compact", "grid"):
            names = [n for n in self.meta.get("aggregations") or [] if n in sec]
            if not names:
                return ""
            rows = " · ".join(f"{_esc(n)} {self._fmt(sec[n])}" for n in names)
            return f'<div style="margin-top:4px;font-size:11px;color:#495057">{rows}</div>'
        return ""


class InteractiveComponent(DepictioComponent):
    default_display = "html"

    @property
    def column(self) -> str:
        return str(self.meta.get("column_name") or "")

    @property
    def control(self) -> str:
        return str(self.meta.get("interactive_component_type") or "")

    def _fetch_data(self) -> pl.DataFrame:
        if self.control in ("Select", "MultiSelect", "SegmentedControl"):
            values = self.client.unique_values(self.dc_id or "", self.column)
            return pl.DataFrame({self.column: values})
        specs = self.client.specs(self.dc_id or "")
        for spec in specs:
            if spec.get("name") == self.column:
                s = spec.get("specs") or {}
                return pl.DataFrame({"stat": list(s.keys()), "value": [str(v) for v in s.values()]})
        return pl.DataFrame({"stat": [], "value": []})

    def _display_html(self) -> str:
        df = self.data
        preview = (
            ", ".join(str(v) for v in df[df.columns[0]].head(12).to_list()) if df.width else ""
        )
        return (
            '<div style="font-family:system-ui,sans-serif;font-size:13px">'
            f"<b>{_esc(self.title)}</b> · {_esc(self.control)} on "
            f"<code>{_esc(self.column)}</code><br>"
            f'<span style="color:#868e96">{_esc(preview)}</span></div>'
        )


class TextComponent(DepictioComponent):
    default_display = "markdown"

    def _display_markdown(self) -> str:
        title = str(self.meta.get("title") or "").strip()
        body = str(self.meta.get("body") or "").strip()
        order = self.meta.get("order")
        try:
            level = max(1, min(6, int(order))) if order is not None else 3
        except (TypeError, ValueError):
            level = 3
        parts = [f"{'#' * level} {title}"] if title else []
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    @property
    def markdown(self) -> str:
        return self._display_markdown()


class ImageComponent(DepictioComponent):
    default_display = "html"
    max_images = 50

    def _fetch_data(self) -> pl.DataFrame:
        payload = self.client.post(
            f"/dashboards/render_image_paths/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "max": self.max_images, **self.pins},
        )
        self._paths = list(payload.get("paths") or [])
        self._base = str((self.meta.get("dc_config") or {}).get("s3_base_folder") or "")
        return pl.DataFrame(payload.get("rows") or [])

    def images(self) -> list[bytes]:
        self.data  # populates paths
        out = []
        for rel in self._paths[: self.max_images]:
            s3_path = f"{self._base}/{rel}" if self._base and not rel.startswith("s3://") else rel
            out.append(self.client.get_bytes("/files/serve/image", s3_path=s3_path))
        return out

    def _display_html(self) -> str:
        tags = []
        for blob in self.images():
            b64 = base64.b64encode(blob).decode()
            tags.append(
                f'<img src="data:image/*;base64,{b64}" style="max-width:220px;margin:4px;'
                'border-radius:4px">'
            )
        return f'<div style="display:flex;flex-wrap:wrap">{"".join(tags)}</div>'


class JBrowseComponent(DepictioComponent):
    """A genome browser tile: its session as data, a snapshot, and a link.

    The live tile is the embedded JBrowse 2 linear view, which reads its
    tracks by HTTP range through the instance's signed track proxy. Neither the
    view nor the reads survive being written into a file, so the document
    shows what can: the assembly, the locus it opens on and the tracks it
    shows (``.tracks``, a DataFrame), a PNG snapshot of that opening view
    taken by the instance's worker, and a link to browse it live. ``.data`` is
    the server's whole session payload.
    """

    default_display = "html"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._snap: dict[str, Any] | None = None

    def refresh(self) -> DepictioComponent:
        self._snap = None
        return super().refresh()

    def _fetch_data(self) -> dict[str, Any]:
        return self.client.post(
            f"/dashboards/render_jbrowse/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, **self.pins},
        )

    @property
    def location(self) -> str:
        loc = self.data.get("location")
        return loc if isinstance(loc, str) else (json.dumps(loc) if loc else "")

    @property
    def assembly(self) -> str:
        conf = self.data.get("assembly") or {}
        return (
            str(conf.get("displayName") or conf.get("name") or "") if isinstance(conf, dict) else ""
        )

    @property
    def tracks(self) -> pl.DataFrame:
        """One row per track the session carries; ``shown`` marks the open ones."""
        shown = {str(t) for t in self.data.get("shown_track_ids") or []}
        rows = []
        for t in self.data.get("tracks") or []:
            if not isinstance(t, dict):
                continue
            category = t.get("category")
            rows.append(
                {
                    "name": str(t.get("name") or t.get("trackId") or ""),
                    "type": str(t.get("type") or ""),
                    "category": " / ".join(category) if isinstance(category, list) else category,
                    "shown": str(t.get("trackId")) in shown,
                    "track_id": str(t.get("trackId") or ""),
                }
            )
        if not rows:
            return pl.DataFrame(
                schema={"name": pl.Utf8, "type": pl.Utf8, "category": pl.Utf8, "shown": pl.Boolean}
            )
        return pl.DataFrame(rows).sort("shown", descending=True, maintain_order=True)

    @property
    def iframe_url(self) -> str:
        """Kept for old notebooks: the live dashboard (there is no JBrowse host to frame)."""
        return self.live_url or ""

    def _snapshot(self) -> dict[str, Any]:
        """The worker's PNG of the opening view, or ``{"reason": ...}`` when it has none."""
        if self._snap is None:
            try:
                self._snap = self.client.poll(
                    f"/dashboards/component_figure/{self.dashboard_id}/{self.index}",
                    {"state": self.state, "theme": self.theme},
                    "/dashboards/component_figure/jobs/{job_id}",
                )
            except Exception as exc:  # noqa: BLE001 - the table and the link still stand
                self._snap = {"reason": self._reason(exc)}
        return self._snap

    @property
    def image(self) -> bytes | None:
        uri = self._snapshot().get("image")
        return _decode_data_uri(uri) if uri else None

    def _display_html(self) -> str:
        data = self.data  # raises (e.g. JBrowse disabled): the placeholder says why
        tracks = self.tracks
        shown = tracks.filter(pl.col("shown")) if tracks.height else tracks
        facts = [
            ("Assembly", self.assembly or "–"),
            ("Opens on", self.location or "the assembly's default region"),
            (
                "Tracks",
                f"{shown.height} shown of {int(data.get('matched_tracks') or tracks.height)} "
                f"matching ({int(data.get('total_tracks') or tracks.height)} in the manifest)",
            ),
        ]
        head = "".join(
            f'<tr><th style="text-align:left;padding:2px 12px 2px 0;color:#868e96;'
            f'font-weight:500">{_esc(k)}</th><td>{_esc(v)}</td></tr>'
            for k, v in facts
        )
        snap = self._snapshot()
        if snap.get("image"):
            picture = snapshot_html(
                str(snap["image"]),
                self.title,
                self.live_url,
                "The genome browser reads its "
                "tracks live from the instance, so the view itself cannot travel in a file.",
            )
        else:
            picture = (
                '<div style="font-size:12px;color:#868e96;margin:6px 0">No snapshot of the view '
                f"({_esc(public_reason(str(snap.get('reason') or 'unavailable')))}). "
                f"{self._live_link('Browse it in the live dashboard')}</div>"
            )
        listing = shown.select([c for c in ("name", "type", "category") if c in shown.columns])
        rows = "".join(
            "<tr>" + "".join(f"<td>{_esc(str(v or ''))}</td>" for v in r) + "</tr>"
            for r in listing.iter_rows()
        )
        table = (
            '<table class="dpx-tracks" style="font-size:12px;border-collapse:collapse;margin-top:6px">'
            "<thead><tr>"
            + "".join(
                f'<th style="text-align:left;padding-right:12px">{c}</th>' for c in listing.columns
            )
            + f"</tr></thead><tbody>{rows}</tbody></table>"
            if listing.height
            else ""
        )
        return (
            '<div class="dpx-jbrowse">'
            f'<table style="font-size:13px;margin-bottom:6px">{head}</table>'
            f"{picture}{table}</div>"
        )


def component_for(
    client: DepictioClient,
    dashboard_id: str,
    meta: dict[str, Any],
    state: dict[str, Any],
    theme: str = "light",
) -> DepictioComponent:
    ctype = str(meta.get("component_type") or "")
    cls: type[DepictioComponent]
    if ctype == "figure":
        cls = FigureComponent
    elif ctype == "map":
        cls = MapComponent
    elif ctype == "multiqc":
        cls = (
            MultiQCGeneralStatsComponent
            if str(meta.get("selected_plot") or "").endswith("general_stats")
            or meta.get("selected_module") == "general_stats"
            else MultiQCComponent
        )
    elif ctype == "advanced_viz":
        cls = AdvancedVizComponent
    elif ctype == "table":
        cls = TableComponent
    elif ctype == "card":
        cls = CardComponent
    elif ctype == "interactive":
        cls = InteractiveComponent
    elif ctype == "text":
        cls = TextComponent
    elif ctype == "image":
        cls = ImageComponent
    elif ctype == "jbrowse":
        cls = JBrowseComponent
    else:
        cls = DepictioComponent
    return cls(client, dashboard_id, meta, state, theme)


COMPONENT_CLASSES: dict[str, type[DepictioComponent]] = {
    "figure": FigureComponent,
    "map": MapComponent,
    "multiqc": MultiQCComponent,
    "advanced_viz": AdvancedVizComponent,
    "table": TableComponent,
    "card": CardComponent,
    "interactive": InteractiveComponent,
    "text": TextComponent,
    "image": ImageComponent,
    "jbrowse": JBrowseComponent,
}
