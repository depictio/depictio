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


def tstr(text: str) -> str:
    """A typst string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


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
    tab_level: int = TAB_LEVEL,
) -> str:
    """The raw typst block the PDF opens with (see the module docstring)."""
    mono = style == "mono"
    accent = INK if mono else primary
    colors = {} if mono else dict(heading_colors or {})
    mark_svg = svg_of(dashboard_mark)
    logo_svg = svg_of(title_logo)
    dep_svg = svg_of(depictio_mark)

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
    # Each tab's and section's colour, by its heading's label.
    # (`(:)` is typst's empty dictionary; `()` would be an empty array.)
    add(
        "#let dpx-colors = ("
        + ("".join(f"{tstr(k)}: {tcolor(v)}, " for k, v in colors.items()) or ":")
        + ")"
    )
    # Type: the app's sans, Mantine's scale and weights, comfortable leading.
    add("#set text(font: dpx-sans, size: 9.5pt, fill: dpx-ink)")
    add("#set par(justify: false, leading: 0.72em, spacing: 1.05em)")
    add("#show raw: set text(font: dpx-mono, size: 8.5pt)")
    add('#show heading: set text(font: dpx-sans, weight: "bold", fill: dpx-ink)')
    add("#show heading: set block(above: 1.4em, below: 0.7em)")
    for level, size in (
        (1, "20pt"),
        (2, "17pt"),
        (3, "15pt"),
        (4, "12pt"),
        (5, "10.5pt"),
        (6, "9.5pt"),
    ):
        add(f"#show heading.where(level: {level}): set text(size: {size})")
    # A tab starts a page, as it does when the HTML report is printed.
    # (the first one goes on with the results' own lead-in rather than leaving
    # it alone on a page).
    add(
        f"#show heading.where(level: {tab_level}): it => {{ "
        f"let first = query(heading.where(level: {tab_level})).first(); "
        "if it.location() != first.location() { pagebreak(weak: true) }; it }"
    )
    # The heading's own colour (the tab's, the section's), when there is one.
    add(
        '#show heading: it => { let c = if it.has("label") { dpx-colors.at(str(it.label), '
        "default: none) } else { none }; if c == none { it } else { text(fill: c, it) } }"
    )
    add("#show figure.caption: set text(size: 8pt, fill: dpx-muted)")
    add("#show table: set text(size: 8pt)")
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

    # Page 1: the title page.
    rows = "".join(
        f"text(fill: dpx-muted)[#{tstr(k)}], [#{tstr(v)}], " for k, v in (provenance or []) if v
    )
    title_block = "#dpx-logo(54pt)" if logo_svg else '#text(size: 26pt, weight: "bold")[#dpx-title]'
    sub = f"#v(6pt) #text(size: 13pt, fill: dpx-muted)[#{tstr(subtitle)}]" if subtitle else ""
    powered = (
        '[#text(size: 7.5pt, weight: "bold", fill: dpx-muted)[Powered by] '
        "#if dpx-depictio-ok { box(baseline: 1.5pt, dpx-depictio(9pt)) } "
        'else { text(size: 8pt, weight: "bold")[Depictio] }]'
    )
    add(
        "#page(header: none, footer: none, numbering: none)["
        "#grid(columns: (1fr, auto), align: (left + horizon, right + horizon), "
        f"[#dpx-mark(16pt)], {powered})"
        "#v(-2pt)#line(length: 100%, stroke: 0.5pt + dpx-hair)"
        "#v(40pt)"
        f"{title_block}"
        f"{sub}"
        "#v(30pt)"
        f"#grid(columns: (auto, 1fr), column-gutter: 14pt, row-gutter: 7pt, {rows})"
        "]"
    )
    # Page 2: the contents, alone; coloured like the headings when they are.
    add(
        '#show outline.entry: it => { let h = it.element; let c = if h.has("label") '
        "{ dpx-colors.at(str(h.label), default: none) } else { none }; "
        "if c == none { it } else { text(fill: c, it) } }"
    )
    add(
        "#page(header: none, footer: none, numbering: none)["
        f"#outline(title: text(size: 17pt)[Contents], depth: {CONTENTS_DEPTH}, indent: 1.1em)]"
    )
    # The body: a running header and footer on every page.
    add(
        '#set page(numbering: "1", '
        "header: context { let p = here().page(); "
        f"let tabs = query(heading.where(level: {tab_level})).filter(h => h.location().page() <= p); "
        "set text(size: 7.5pt, fill: dpx-muted); "
        "grid(columns: (1fr, auto), align: (left + horizon, right + horizon), "
        "[#if dpx-mark-ok { box(baseline: 1pt, dpx-mark(8pt)) } #dpx-title], "
        "[#if tabs.len() > 0 { tabs.last().body }]); "
        "v(-4pt); line(length: 100%, stroke: 0.4pt + dpx-hair) }, "
        "footer: context { set text(size: 7.5pt, fill: dpx-muted); "
        "grid(columns: (1fr, auto), align: (left + horizon, right + horizon), "
        "[Powered by #if dpx-depictio-ok { box(baseline: 1pt, dpx-depictio(6.5pt)) } "
        "else [Depictio]], [#counter(page).display()]) })"
    )
    add("#counter(page).update(1)")
    return "\n".join(lines) + "\n"
