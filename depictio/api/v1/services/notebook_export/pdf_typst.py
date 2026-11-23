"""The PDF's page: the typst the document carries for its ``typst`` format.

Quarto's typst article is a centred title block, Libertinus serif and plain
headings. The report's PDF reads as the HTML report does instead:

* page 1 is a title page in the header's spirit: the dashboard's mark and
  "Powered by Depictio" on one line, the title (the dashboard's logo when its
  first tab has one), the subtitle, then the export's provenance;
* page 2 is the contents, alone; the body starts on page 3;
* every body page has a light running header (the dashboard's mark and title,
  the tab in view) and footer ("Powered by Depictio", the page number);
* Inter for text and headings, a matching mono for code, each with a fallback
  chain: a font the machine lacks is a typst warning, never a failed render;
* ``colour`` keeps each tab's and section's colour on its heading and in the
  contents and tints the notes; ``mono`` prints them all in the text colour
  (figures are left as they are).

All of it is one raw typst block (``include-before-body``), built from the
export's own data: nothing here is a file next to the ``.qmd``, so a reader's
own ``quarto render`` produces the same PDF.
"""

from __future__ import annotations

import base64
import struct
from typing import Literal

from depictio.notebook.qmd_safe import typst_str

from .resources import asset

PdfStyle = Literal["colour", "mono"]
PDF_STYLES: tuple[str, ...] = ("colour", "mono")

# The app's type, then what a worker or a laptop is likely to have. Typst picks
# the first family it finds and warns about the others.
SANS: tuple[str, ...] = ("Inter", "Inter Variable", "Roboto", "Liberation Sans", "DejaVu Sans")
MONO: tuple[str, ...] = ("JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono")

INK = "#212529"
MUTED = "#868e96"
HAIR = "#dee2e6"

# The PDF's heading levels: the document's shifted up by one (no h1 in the
# body; ``quarto.QuartoFrontMatter``): the results and closing parts at 1, a
# tab at 2, a section at 3, a tile's own heading below.
TAB_LEVEL = 2
CONTENTS_DEPTH = 3


#: A raw typst block that clears a tile's failure mark (``dpx-failed``),
#: after a tile with no caption to read it.
TYPST_TILE_DONE = "```{=typst}\n#dpx-tile-done\n```"


def tstr(text: str) -> str:
    """A typst string literal (``qmd_safe.typst_str``)."""
    return typst_str(text)


def tcolor(hex_color: str) -> str:
    return f"rgb({tstr(hex_color)})"


def _fonts(families: tuple[str, ...]) -> str:
    return "(" + ", ".join(tstr(f) for f in families) + ")"


def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) if w and h else None


def svg_of(data_uri: str | None) -> str | None:
    """An image data URI as SVG text typst can draw (``image(bytes(...))``).

    Typst reads no data URI and decodes no base64; an SVG it reads as text,
    and an SVG may hold a PNG as its own data URI. ``None`` for anything else.
    """
    if not data_uri or not data_uri.startswith("data:image/") or "," not in data_uri:
        return None
    head, payload = data_uri.split(",", 1)
    if head.startswith("data:image/svg+xml"):
        try:
            return base64.b64decode(payload).decode("utf-8") if ";base64" in head else payload
        except (ValueError, UnicodeDecodeError):
            return None
    if head.startswith("data:image/png") and ";base64" in head:
        try:
            size = _png_size(base64.b64decode(payload[:64] + "=" * (-len(payload[:64]) % 4)))
        except ValueError:
            size = None
        if size is None:
            return None
        w, h = size
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<image width="{w}" height="{h}" xlink:href="{data_uri}"/></svg>'
        )
    return None


def _image_fn(name: str, svg: str | None) -> str:
    """``#let name(h) = image(...)``, or a function drawing nothing."""
    if not svg:
        return f"#let {name}(h) = none\n#let {name}-ok = false"
    return f"#let {name}(h) = image(bytes({tstr(svg)}), height: h)\n#let {name}-ok = true"


# The page's building blocks: what the tiles' typst output and the document's
# own raw blocks call (``depictio/notebook/typst.py``, ``report_chrome``).
# Plain typst, no Python formatting: the colours are the ``dpx-*`` set above.
DEFINITIONS = asset("definitions.typ")


def typst_preamble(
    *,
    title: str,
    subtitle: str | None,
    primary: str,
    style: str = "colour",
    dashboard_mark: str | None = None,
    title_logo: str | None = None,
    depictio_mark: str | None = None,
    provenance: list[tuple[str, str]] | None = None,
    heading_colors: dict[str, str] | None = None,
    heading_icons: dict[str, str] | None = None,
    statement: str | None = None,
    tab_level: int = TAB_LEVEL,
) -> str:
    """The raw typst block the PDF opens with (see the module docstring).

    ``heading_icons`` is each heading label's Iconify SVG (``currentColor``),
    drawn before the heading in its colour (the text colour in ``mono``).
    ``statement`` is the cover's plain sentence of what the file is.
    """
    mono = style == "mono"
    accent = INK if mono else primary
    colors = {} if mono else dict(heading_colors or {})
    mark_svg = svg_of(dashboard_mark)
    logo_svg = svg_of(title_logo)
    dep_svg = svg_of(depictio_mark)

    def svg_in(svg: str, color: str) -> str:
        out = svg.replace("currentColor", color)
        if "xmlns=" not in out:
            out = out.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        return out

    icons = {
        label: svg_in(svg, colors.get(label) or (INK if mono else MUTED))
        for label, svg in (heading_icons or {}).items()
        if svg
    }

    lines: list[str] = []
    add = lines.append
    add(f"#let dpx-sans = {_fonts(SANS)}")
    add(f"#let dpx-mono = {_fonts(MONO)}")
    add(f"#let dpx-ink = {tcolor(INK)}")
    add(f"#let dpx-muted = {tcolor(MUTED)}")
    add(f"#let dpx-hair = {tcolor(HAIR)}")
    add(f"#let dpx-accent = {tcolor(accent)}")
    add(f"#let dpx-title = {tstr(title)}")
    add(_image_fn("dpx-mark", mark_svg))
    add(_image_fn("dpx-depictio", dep_svg))
    add(_image_fn("dpx-logo", logo_svg))
    # Each tab's and section's colour and icon, by its heading's label.
    # (`(:)` is typst's empty dictionary; `()` would be an empty array.)
    add(
        "#let dpx-colors = ("
        + ("".join(f"{tstr(k)}: {tcolor(v)}, " for k, v in colors.items()) or ":")
        + ")"
    )
    add(
        "#let dpx-icons = ("
        + ("".join(f"{tstr(k)}: {tstr(v)}, " for k, v in icons.items()) or ":")
        + ")"
    )
    # Type: the app's sans, Mantine's scale and weights, comfortable leading.
    add("#set text(font: dpx-sans, size: 9.5pt, fill: dpx-ink)")
    add("#set par(justify: false, leading: 0.72em, spacing: 1.05em)")
    add("#show raw: set text(font: dpx-mono, size: 8.5pt)")
    add('#show heading: set text(font: dpx-sans, weight: "bold", fill: dpx-ink)')
    for level, size in ((1, "18pt"), (2, "15pt"), (3, "12pt"), (4, "10.5pt"), (5, "9.5pt")):
        add(f"#show heading.where(level: {level}): set text(size: {size})")
    add(DEFINITIONS)
    # A heading: its icon before it, its colour on both (by label), drawn as a
    # block of its own so the icon sits on the heading's line.
    add(
        "#show heading: it => { "
        'let key = if it.has("label") { str(it.label) } else { none }; '
        "let c = if key != none { dpx-colors.at(key, default: none) } else { none }; "
        "let ic = if key != none { dpx-icons.at(key, default: none) } else { none }; "
        "set text(fill: c) if c != none; "
        "block(above: 1.35em, below: 0.65em, sticky: true)[#if ic != none "
        "[#dpx-svg(ic, 0.85em)#h(0.3em)]#it.body] }"
    )
    # A tab starts a page, as it does when the HTML report is printed; the
    # first follows the results' own lead-in, and an appendix right after the
    # "Appendices" heading shares its page.
    add(
        f"#show heading.where(level: {tab_level}): it => {{ "
        f"let first = query(heading.where(level: {tab_level})).first(); "
        "let before = query(selector(heading).before(it.location(), inclusive: false)); "
        'let after-appx = before.len() > 0 and before.last().has("label") '
        'and str(before.last().label) == "appendices"; '
        "if it.location() != first.location() and not after-appx { pagebreak(weak: true) }; it }"
    )
    add(
        "#show heading.where(level: 1): it => { "
        'if it.has("label") and str(it.label) == "appendices" { pagebreak(weak: true) }; it }'
    )
    # Last of the heading rules, so it sees the heading before they draw it: a
    # heading right before a wide float moves onto its landscape page
    # (definitions.typ, ``dpx-heading-copy``). Here it draws nothing: the
    # element stays in the document, so the contents still list and link it.
    add(
        "#show heading: it => context { let next = dpx-next(it.location()); "
        "if next != none and dpx-is-wide(next) { [] } else { it } }"
    )
    add("#show figure.caption: set text(size: 8pt, fill: dpx-muted)")
    add("#show link: set text(fill: dpx-accent)")
    # The notes ("About this component"): a quiet card, the accent on its edge.
    add(
        '#let callout(body: [], title: "Note", background_color: none, icon: none, '
        "icon_color: none, body_background_color: none) = block(width: 100%, breakable: true, "
        "inset: (x: 10pt, y: 8pt), radius: 4pt, stroke: (left: 2pt + dpx-accent, "
        "top: 0.5pt + dpx-hair, right: 0.5pt + dpx-hair, bottom: 0.5pt + dpx-hair))"
        '[#text(size: 8pt, weight: "semibold", fill: dpx-muted)[#title] #v(2pt) '
        "#text(size: 8.5pt)[#body]]"
    )

    # Page 1: the cover. What this is, whose, and the export's record.
    rows = "".join(
        f'text(fill: dpx-muted)[#{tstr(k)}], text(weight: "medium")[#{tstr(v)}], '
        for k, v in (provenance or [])
        if v
    )
    title_block = (
        "#dpx-logo(84pt)"
        if logo_svg
        else '#text(size: 34pt, weight: "bold", tracking: -0.02em)[#dpx-title]'
    )
    sub = f"#v(10pt) #text(size: 15pt, fill: dpx-muted)[#{tstr(subtitle)}]" if subtitle else ""
    said = f"#v(14pt) #text(size: 10.5pt)[#{tstr(statement)}]" if statement else ""
    powered = (
        '[#text(size: 8pt, weight: "bold", fill: dpx-muted)[Powered by] '
        "#if dpx-depictio-ok { box(baseline: 1.5pt, dpx-depictio(10pt)) } "
        'else { text(size: 8pt, weight: "bold")[Depictio] }]'
    )
    add(
        "#page(header: none, footer: none, numbering: none)["
        "#grid(columns: (1fr, auto), align: (left + horizon, right + horizon), "
        f"[#dpx-mark(20pt)], {powered})"
        "#v(-2pt)#line(length: 100%, stroke: 0.5pt + dpx-hair)"
        "#v(56pt)"
        '#text(size: 9pt, weight: "bold", fill: dpx-accent, tracking: 0.12em)[DASHBOARD REPORT]'
        "#v(8pt)"
        f"{title_block}"
        f"{sub}"
        f"{said}"
        "#v(30pt)"
        "#block(width: 100%, inset: 14pt, radius: 6pt, fill: dpx-well)["
        "#set text(size: 9.5pt)\n"
        f"#grid(columns: (auto, 1fr), column-gutter: 16pt, row-gutter: 8pt, {rows})]"
        "]"
    )
    # Page 2: the contents, alone, in the text colour (the headings carry the
    # tabs' colours; a contents page of a dozen hues reads as noise).
    add('#show outline.entry.where(level: 1): set text(weight: "semibold")')
    add(
        "#page(header: none, footer: none, numbering: none)["
        f"#outline(title: text(size: 17pt)[Contents], depth: {CONTENTS_DEPTH}, indent: 1.1em)]"
    )
    # The body: a running header and footer on every page. The header says
    # what the file is, the footer who made it.
    add(
        '#set page(numbering: "1", '
        "header: context { let p = here().page(); "
        f"let tabs = query(heading.where(level: {tab_level})).filter(h => h.location().page() <= p); "
        "set text(size: 7.5pt, fill: dpx-muted); "
        "grid(columns: (1fr, auto), align: (left + horizon, right + horizon), "
        "[#if dpx-mark-ok { box(baseline: 1pt, dpx-mark(8pt)) } "
        '#text(fill: dpx-ink, weight: "medium")[#dpx-title] · Dashboard report], '
        "[#if tabs.len() > 0 { tabs.last().body }]); "
        "v(-4pt); line(length: 100%, stroke: 0.4pt + dpx-hair) }, "
        "footer: context { set text(size: 7.5pt, fill: dpx-muted); "
        "grid(columns: (1fr, auto), align: (left + horizon, right + horizon), "
        "[Powered by #if dpx-depictio-ok { box(baseline: 1pt, dpx-depictio(6.5pt)) } "
        "else [Depictio]], [#counter(page).display()]) })"
    )
    add("#counter(page).update(1)")
    return "\n".join(lines) + "\n"
