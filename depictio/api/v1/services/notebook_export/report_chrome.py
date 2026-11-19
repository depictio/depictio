"""The report's own chrome: what a Quarto page needs that a dashboard tile does not.

The generator turns a dashboard into cells; this module holds the pieces of
the page around them that are pure text, so they are tested without building
a whole plan:

* a tile's ``description`` as the collapsed "About this component" note the
  live tile opens from its info icon (``ComponentInfo.tsx`` and
  ``descriptionText.ts``: the same paragraphs, the same labels);
* a text tile's ``::: steps`` list as the stepper the live text renderer draws;
* the header bar (the dashboard's mark and name, "Powered by" Depictio, as the
  app header carries them) and the footer (provenance, the live link when the
  dashboard is public, the project's licence and citation when it has them);
* the stylesheet for all of the above, the multi-column rows and the text
  surfaces, in Paper's tokens and in both colour schemes.

Nothing here invents prose: every sentence a reader sees is the dashboard's,
the project's, or a fixed label.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from depictio.notebook.qmd_safe import defuse, one_line
from depictio.notebook.qmd_safe import esc as _esc
from depictio.notebook.qmd_safe import typst_str as _typst_str

from .report_theme import SCHEME_TOGGLE
from .resources import script, style

# ``descriptionText.ts`` LABELS: the paragraph labels a description may open
# with, as the popover shows them.
_LABELS: dict[str, tuple[str, str]] = {
    "how to read": ("labelled", "How to read"),
    "lines and annotations": ("labelled", "Lines and annotations"),
    "annotations": ("labelled", "Annotations"),
    "reference lines": ("labelled", "Reference lines"),
    "source": ("source", "Source"),
    "sources": ("source", "Sources"),
    "note": ("callout", "Note"),
    "warning": ("callout", "Warning"),
    "caution": ("callout", "Caution"),
}
_LABEL_RE = re.compile(
    r"^(how to read|lines and annotations|annotations|reference lines|sources?|note|warning|caution)"
    r"[ \t]*:(?:[ \t]+|(?=\n|$))",
    re.IGNORECASE,
)
_STRUCTURAL = re.compile(r"^\s*(?:#{1,3}\s|[-*+]\s|\d+[.)]\s|\||:{3,})")


@dataclass(frozen=True)
class DescriptionSection:
    kind: str  # lead | body | labelled | callout | source
    text: str
    label: str | None = None


def _match_label(paragraph: str) -> re.Match[str] | None:
    # A label is capitalised: "note: x" is prose (``matchLabel``).
    if not paragraph[:1].isupper():
        return None
    return _LABEL_RE.match(paragraph)


def _paragraphs(text: str) -> list[str]:
    """Blank lines split paragraphs; so does a single newline outside a list
    or a fenced div, as in a folded YAML scalar (``paragraphsOf``)."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        run: list[str] = []
        for line in lines:
            if _STRUCTURAL.match(line) or (run and line[:1].isspace()):
                run.append(line)
                continue
            if run:
                out.append("\n".join(run))
                run = []
            m = _match_label(line.strip())
            if m and m.end() >= len(line.strip()):
                run.append(line.strip())  # a bare label keeps the run under it
                continue
            out.append(line.strip())
        if run:
            out.append("\n".join(run))
    return [p for p in out if p.strip()]


def description_sections(description: str) -> list[DescriptionSection]:
    """``parseSections``: the description as the popover's sections."""
    out: list[DescriptionSection] = []
    for paragraph in _paragraphs(description):
        m = _match_label(paragraph)
        if m:
            kind, label = _LABELS[m.group(1).lower()]
            rest = paragraph[m.end() :].strip()
            if kind != "source" and rest[:1].islower() and re.match(r"^[a-z]+\b", rest):
                rest = rest[0].upper() + rest[1:]
            out.append(DescriptionSection(kind=kind, text=rest, label=label))
            continue
        lead = not out and not _STRUCTURAL.match(paragraph.split("\n")[0])
        out.append(DescriptionSection(kind="lead" if lead else "body", text=paragraph))
    return out


def _linkify_source(entry: str) -> str:
    """Bare URLs and ``doi:`` tokens become links (``linkifySource``)."""

    def sub(m: re.Match[str]) -> str:
        token = m.group(0)
        if token.startswith("["):
            return token
        trimmed = token.rstrip(".,;:!?")
        tail = token[len(trimmed) :]
        if trimmed.lower().startswith("doi:"):
            doi = re.sub(r"^doi:\s*", "", trimmed, flags=re.IGNORECASE)
            return f"[doi:{doi}](https://doi.org/{doi}){tail}"
        return f"<{trimmed}>{tail}"

    return re.sub(
        r"\[[^\]\n]+\]\([^)\s]+\)|https?://[^\s<>]+|doi:[ \t]*10\.\d{4,9}/[^\s;,<>]+",
        sub,
        entry,
        flags=re.IGNORECASE,
    )


def about_markdown(description: str, *, rewrite: Callable[[str], str] = lambda s: s) -> str:
    """The body of a tile's "About this component" note, as markdown."""
    parts: list[str] = []
    # An author's markdown: kept, with no Quarto construct left in it.
    for sec in description_sections(defuse(description)):
        text = rewrite(sec.text)
        if sec.kind == "source":
            entries = [e.strip() for e in re.split(r";(?![^()]*\))|\n", text) if e.strip()]
            parts.append(
                f"**{sec.label}.** " + "; ".join(_linkify_source(e.lstrip("-*+ ")) for e in entries)
            )
        elif sec.label:
            joiner = "\n\n" if _STRUCTURAL.match(text.split("\n")[0] or "") else " "
            parts.append(f"**{sec.label}.**{joiner}{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


def _about_item(body: str, *, name: str = "", index: str = "", pos: int | None = None) -> str:
    """One component's description inside an about note, marked for the page's
    "i" buttons (``report_theme``): its name heads the popover, its index ties
    it to its card in a row. A fenced div, so a page without the script (the
    PDF, a reader without JavaScript) shows the text as written."""
    attrs = ".dpx-about-item"
    if name:
        attrs += f' data-dpx-name="{_attr(name)}"'
    if index:
        attrs += f' data-dpx-index="{_attr(index)}"'
    if pos is not None:
        attrs += f' data-dpx-pos="{pos}"'
    longest = max((len(m.group(0)) for m in re.finditer(r":{3,}", body)), default=2)
    fence = ":" * max(3, longest + 1)
    return f"{fence} {{{attrs}}}\n{body}\n{fence}"


def _attr(value: str) -> str:
    """A value for a pandoc attribute: no quote or brace to end it early."""
    return re.sub(r'["{}`]', " ", one_line(value)).strip()


def about_callout(
    description: str,
    *,
    title: str = "About this component",
    name: str = "",
    rewrite: Callable[[str], str] = lambda s: s,
) -> str:
    """A collapsed Quarto callout holding a tile's description, or ``""``.

    Collapsed, as the live popover is closed at rest: the report reads as the
    dashboard does, and the text is one click away (and printed open). On
    screen the page's "i" button in the tile's action row opens the same text
    as a popover (``report_theme``); the callout is what prints, and what a
    reader without JavaScript gets. ``name`` is the tile's title, heading that
    popover.
    """
    body = about_markdown(description.strip(), rewrite=rewrite) if description else ""
    if not body.strip():
        return ""
    body = _about_item(body, name=name)
    # A colon run longer than any inside the body, so the author's own fenced
    # divs (`::: steps`) cannot close the callout.
    longest = max((len(m.group(0)) for m in re.finditer(r":{3,}", body)), default=2)
    fence = ":" * max(4, longest + 1)
    safe_title = _attr(title.replace('"', "'"))
    return (
        f'{fence} {{.callout-note .dpx-about collapse="true" appearance="simple" '
        f'icon="false" title="{safe_title}"}}\n{body}\n\n{fence}'
    )


# ── The stepper ──────────────────────────────────────────────────────────────

_STEP_ITEM = re.compile(
    r"^(?P<num>\s*\d+[.)]\s+)"
    r"(?:!\[[^\]]*\]\(icon:(?P<icon>[a-z0-9-]+:[a-z0-9-]+)\)\s*)?"
    r"(?:\*\*(?P<label>[^*\n]+)\*\*\s*)?"
    r"(?P<rest>.*)$"
)
_LINK_ONLY = re.compile(r"^\[[^\]\n]+\]\([^)\n]+\)$")
_STEPS_OPEN = re.compile(r"^(\s*):::+\s*\{?\.?steps\}?\s*$")
_DIV_CLOSE = re.compile(r"^\s*:::+\s*$")


def stepper_markdown(
    markdown: str,
    icon_html: Callable[[str], str],
    rewrite_link: Callable[[str], str] = lambda s: s,
) -> str:
    """Each ``::: steps`` list item as the stepper's parts.

    ``1. ![](icon:x) **Trim** Primers cut · [Settings](params:p) · [Tab](tab:T)``
    becomes a mark (the icon in a disc), the label, the step's links beside it
    and its text under it: what the live text renderer draws, as spans the
    stylesheet lays out. ``rewrite_link`` turns each step link into the
    document's; one it turns into plain text (a target the document lacks) is
    dropped. Everything else in the text is left as written.
    """
    lines = markdown.split("\n")
    inside = False
    for i, line in enumerate(lines):
        if not inside:
            if _STEPS_OPEN.match(line):
                inside = True
                lines[i] = "::: {.steps .dpx-steps}"
            continue
        if _DIV_CLOSE.match(line):
            inside = False
            continue
        m = _STEP_ITEM.match(line)
        if not m or not (m.group("icon") or m.group("label")):
            continue
        bits = [b.strip() for b in re.split(r"\s+·\s+", m.group("rest").strip()) if b.strip()]
        links = [r for r in (rewrite_link(b) for b in bits if _LINK_ONLY.match(b)) if "](" in r]
        text = " · ".join(b for b in bits if not _LINK_ONLY.match(b))
        mark = icon_html(m.group("icon")) if m.group("icon") else ""
        # Spaces between the parts: a page without the stylesheet (the PDF)
        # still reads "Trim MultiQC Primers cut by Cutadapt".
        head = [f'<span class="dpx-step-mark">{mark}</span>']
        if m.group("label"):
            head.append(f'<span class="dpx-step-label">{_esc(m.group("label").strip())}</span>')
        if links:
            head.append('<span class="dpx-step-links">' + " ".join(links) + "</span>")
        if text:
            head.append(f'<span class="dpx-step-text">{text}</span>')
        lines[i] = m.group("num") + " ".join(head)
    return "\n".join(lines)


# ── Header bar and footer ────────────────────────────────────────────────────

DOCS_URL = "https://depictio.github.io/depictio-docs/"


def powered_by_html(has_mark: bool) -> str:
    """``PoweredBy``: a quiet "Powered by" and the Depictio wordmark, linking
    to the docs. The wordmark is the stylesheet's (one copy for the page)."""
    mark = (
        '<span class="dpx-mark" role="img" aria-label="Depictio"></span>'
        if has_mark
        else "<strong>Depictio</strong>"
    )
    return (
        f'<a class="dpx-powered" href="{DOCS_URL}" target="_blank" rel="noopener noreferrer">'
        f'<span class="dpx-powered-label">Powered by</span>{mark}</a>'
    )


def appbar_html(
    *,
    title: str | None,
    logo: str | None,
    logo_dark: str | None,
    accent: str,
    has_mark: bool,
    scheme_toggle: bool = False,
) -> str:
    """The app header, as a report's top bar: the dashboard's mark on the left,
    "Powered by Depictio" on the right, then the colour-scheme button when the
    report has a dark theme (``scheme_toggle``, ``report_theme.SCHEME_TOGGLE``).

    ``title`` is the dashboard's name beside the mark, or ``None`` when the
    title block right under the bar already says it (it always does in a
    report: the bar is not a second place for the same name).
    """
    marks = ""
    if logo:
        cls = "dpx-appbar-logo dpx-light-only" if logo_dark else "dpx-appbar-logo"
        marks += f'<img class="{cls}" src="{logo}" alt="" />'
    if logo_dark:
        marks += f'<img class="dpx-appbar-logo dpx-dark-only" src="{logo_dark}" alt="" />'
    if not marks and title:
        marks = f'<span class="dpx-appbar-dot" style="background:{_esc(accent)}"></span>'
    name = f'<span class="dpx-appbar-title">{_esc(title)}</span>' if title else ""
    return (
        '<header class="dpx-appbar" role="banner"><div class="dpx-appbar-inner">'
        f'<span class="dpx-appbar-brand">{marks}{name}</span>'
        f'<span class="dpx-appbar-end">{powered_by_html(has_mark)}'
        f"{SCHEME_TOGGLE if scheme_toggle else ''}</span></div></header>"
    )


def title_logo_css(light: str, dark: str | None = None) -> str:
    """The dashboard's own logo as the document title: the H1 keeps its text
    (the contents, the page title, a screen reader read it) and shows the logo
    in its place, so the name is not printed twice, once in each form. Printed
    and in the reader's dark scheme too; a page without the stylesheet (the
    PDF) prints the title as text."""
    dark_rule = f"body.quarto-dark h1.title {{ background-image: url('{dark}'); }}" if dark else ""
    return (
        "<style>"
        "h1.title { flex: 1 1 auto; min-width: 0; height: 84px; margin: 0.25rem 0 0.75rem;"
        " overflow: hidden; white-space: nowrap; text-indent: -10000px;"
        f" background: url('{light}') left center / contain no-repeat;"
        " -webkit-print-color-adjust: exact; print-color-adjust: exact; }"
        f"{dark_rule}"
        "</style>"
    )


def footer_html(
    *,
    exported_at: str,
    exported_by: str | None,
    instance: str | None,
    version: str | None,
    dashboard_url: str | None,
    project: str | None,
    licence: str | None,
    citation: str | None,
    data_url: str | None,
    has_mark: bool,
) -> str:
    """The report's foot: what produced it, and how to get back to the source.

    Every value is the export's own record; a line with nothing to say is left
    out rather than filled.
    """

    def row(label: str, value_html: str) -> str:
        return f'<div class="dpx-foot-row"><dt>{_esc(label)}</dt><dd>{value_html}</dd></div>'

    rows = []
    exported = _esc(exported_at)
    if exported_by:
        exported += f" by {_esc(exported_by)}"
    if instance:
        exported += f" from <code>{_esc(instance)}</code>"
    rows.append(row("Exported", exported))
    if version:
        rows.append(row("Depictio", _esc(version)))
    if project:
        rows.append(row("Project", _esc(project)))
    if dashboard_url:
        u = _esc(dashboard_url, quote=True)
        rows.append(row("Live dashboard", f'<a href="{u}">{_esc(dashboard_url)}</a>'))
    if data_url:
        u = _esc(data_url, quote=True)
        rows.append(row("Data", f'<a href="{u}">{_esc(data_url)}</a>'))
    if licence:
        rows.append(row("Licence", _esc(licence)))
    if citation:
        rows.append(row("Cite", _esc(citation)))
    return (
        '<footer class="dpx-footer" role="contentinfo">'
        f'<div class="dpx-foot-brand">{powered_by_html(has_mark)}</div>'
        f'<dl class="dpx-foot-meta">{"".join(rows)}</dl>'
        "</footer>"
    )


def mark_css(light_uri: str | None) -> str:
    """The Depictio wordmark, once, as a background both the bar and the foot
    use; dark mode inverts it and turns the hue back, as the app does."""
    if not light_uri:
        return ""
    return (
        "<style>.dpx-mark{display:inline-block;height:18px;aspect-ratio:1200/269;"
        f"background:url('{light_uri}') center/contain no-repeat;"
        "-webkit-print-color-adjust:exact;print-color-adjust:exact;vertical-align:middle}"
        "body.quarto-dark .dpx-mark{filter:invert(1) hue-rotate(180deg)}</style>"
    )


# ── Grid rows ────────────────────────────────────────────────────────────────


def grid_open(widths: list[int]) -> str:
    """A row of tiles side by side, each as wide as its grid columns.

    Quarto's own layout (``layout="[5,3]"``), which every format draws: a flex
    row on the page, a typst grid in the PDF (each cell a card there).
    """
    cols = ",".join(str(max(1, int(w))) for w in widths)
    return f'::: {{.dpx-grid layout="[{cols}]"}}'


#: A tile on a card surface outside a row: one cell of its own, so the PDF
#: draws it as a card too (the page draws the inner div).
SURFACE_OPEN = '::: {.dpx-grid layout="[1]"}'


def cell_open(extra_class: str = "", accent: str | None = None) -> str:
    style = f' style="--dpx-accent: {_esc(accent, quote=True)}"' if accent else ""
    cls = f".dpx-cell{(' .' + extra_class) if extra_class else ''}"
    return f"::: {{{cls}{style}}}"


DIV_CLOSE = ":::"


# The stylesheet for everything above, in Paper's tokens (``--gl-*``, set by
# PAPER_CHROME) with the classic look's values as fallbacks.
REPORT_CSS = style("report.css")


def about_callout_many(
    items: list[tuple[str, str]] | list[tuple[str, str, str]],
    *,
    title: str = "About these components",
    rewrite: Callable[[str], str] = lambda s: s,
) -> str:
    """One folded note for a row of cards: each card's description under its
    name, so a strip of four does not grow four notes under it.

    An item may carry the card's index as a third value: the page then gives
    that card its own "i" button, opening its own part of the note."""
    parts = []
    for pos, item in enumerate(items):
        name, description = item[0], item[1]
        index = item[2] if len(item) > 2 else ""  # type: ignore[misc]
        body = about_markdown(description.strip(), rewrite=rewrite) if description else ""
        if body.strip():
            # Its place in the row too: a report rendered without the runtime
            # has no tile placeholder to read the cards' order from.
            parts.append(
                _about_item(
                    f"**{_esc(name)}**\n\n{body}",
                    name=name,
                    index=index,
                    pos=pos if index else None,
                )
            )
    if not parts:
        return ""
    body = "\n\n".join(parts)
    longest = max((len(m.group(0)) for m in re.finditer(r":{3,}", body)), default=2)
    fence = ":" * max(4, longest + 1)
    return (
        f'{fence} {{.callout-note .dpx-about collapse="true" appearance="simple" '
        f'icon="false" title="{_attr(title)}"}}\n{body}\n\n{fence}'
    )


# ── Methods and citations ────────────────────────────────────────────────────

DEPICTIO_REPO = "https://github.com/depictio/depictio"
# MultiQC's own paper, the reference its documentation asks a report to cite.
MULTIQC_REFERENCE: dict[str, Any] = {
    "id": "multiqc",
    "type": "article-journal",
    "title": "MultiQC: summarize analysis results for multiple tools and samples in a single report",
    "author": [
        {"family": "Ewels", "given": "Philip"},
        {"family": "Magnusson", "given": "Måns"},
        {"family": "Lundin", "given": "Sverker"},
        {"family": "Käller", "given": "Max"},
    ],
    "container-title": "Bioinformatics",
    "volume": "32",
    "issue": "19",
    "page": "3047-3048",
    "issued": {"date-parts": [[2016]]},
    "DOI": "10.1093/bioinformatics/btw354",
}


def _ref_id(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "ref"


def methods(
    *,
    project: dict[str, Any] | None,
    depictio_version: str | None,
    uses_multiqc: bool,
    collections: list[tuple[str, int | None]],
) -> tuple[str, list[dict[str, Any]]]:
    """The "Methods and citations" part, and the CSL-JSON references it cites.

    Built from the export's own records only: the project's workflows (name,
    version, engine, catalog, repository), the template it was made from, the
    collections the report reads, Depictio's version, MultiQC when the
    dashboard shows a MultiQC report, and the project's licence and citation
    when it records them. ``("", [])`` when none of that is known.
    """
    project = project or {}
    refs: list[dict[str, Any]] = []
    lines: list[str] = []
    for wf in project.get("workflows") or []:
        if not isinstance(wf, dict) or not wf.get("name"):
            continue
        catalog = wf.get("catalog") if isinstance(wf.get("catalog"), dict) else {}
        engine = wf.get("engine") if isinstance(wf.get("engine"), dict) else {}
        full = f"{catalog.get('name')}/{wf['name']}" if catalog.get("name") else str(wf["name"])
        rid = "wf-" + _ref_id(full)
        ref: dict[str, Any] = {"id": rid, "type": "software", "title": full}
        if wf.get("version"):
            ref["version"] = str(wf["version"])
        if wf.get("repository_url"):
            ref["URL"] = str(wf["repository_url"])
        if catalog.get("name"):
            ref["publisher"] = str(catalog["name"])
        refs.append(ref)
        bits = f"**{_esc(full)}**"
        if wf.get("version"):
            bits += f" {_esc(str(wf['version']))}"
        if engine.get("name"):
            eng = str(engine["name"]) + (f" {engine['version']}" if engine.get("version") else "")
            bits += f", run with {_esc(eng)}"
        lines.append(f"- Pipeline: {bits} [@{rid}]")
    origin = (
        project.get("template_origin") if isinstance(project.get("template_origin"), dict) else {}
    )
    if origin and origin.get("template_id"):
        when = f", applied {_esc(str(origin['applied_at']))}" if origin.get("applied_at") else ""
        lines.append(f"- Project template: `{_esc(str(origin['template_id']))}`{when}")
    if collections:
        listed = ", ".join(
            f"`{_esc(tag)}`" + (f" ({rows:,} rows)" if rows is not None else "")
            for tag, rows in collections
        )
        lines.append(f"- Data collections read by this report: {listed}")
    if uses_multiqc:
        refs.append(dict(MULTIQC_REFERENCE))
        lines.append("- Quality control summarised with **MultiQC** [@multiqc]")
    licence = next(
        (str(project[k]) for k in ("license", "licence", "data_license") if project.get(k)), None
    )
    citation = next((str(project[k]) for k in ("citation", "how_to_cite") if project.get(k)), None)
    if licence:
        lines.append(f"- Data licence: {_esc(licence)}")
    if citation:
        lines.append(f"- How to cite the data: {_esc(citation)}")
    if not lines:
        return "", []
    dep: dict[str, Any] = {
        "id": "depictio",
        "type": "software",
        "title": "Depictio",
        "URL": DEPICTIO_REPO,
    }
    if depictio_version:
        dep["version"] = depictio_version
    refs.append(dep)
    version = f" {_esc(depictio_version)}" if depictio_version else ""
    lines.append(f"- Dashboard and report: **Depictio**{version} [@depictio]")
    body = "\n".join(lines) + "\n\n**References**\n\n::: {#refs}\n:::"
    return body, refs


# The contents list, scoped to the tab being read: Quarto's margin contents is
# already sticky and marks the section in view; with a dozen tabs of sections
# each it is also a wall. Only the current tab's sections stay open, the other
# tabs listed (a click unfolds and scrolls to them, the fold script's job).
# It follows the reader, and leaves alone a branch the reader folded or opened
# by hand until the tab in view changes.
TOC_SCOPE_JS = script("toc_scope.js") + "\n" + style("toc_scope.css")


# The dark scheme (``body.quarto-dark``: the reader prefers it, or toggled it):
# Paper's tokens for Mantine's dark palette, and the few colours the classic
# chrome wrote out. Plotly figures drawn by the document are transparent with
# ink-coloured text: their text and grid follow the page here. Tiles drawn by
# the report runtime follow the same class on their own.
DARK_CSS = style("dark.css")


# ── Links the document cannot hold ──────────────────────────────────────────

#: Stands where a link was whose target the document does not hold (a tab the
#: export left out, a section it does not draw, run parameters it has none of).
ORPHAN = "\x00dpx-orphan\x00"

_ORPHAN_ITEM = re.compile(r"^(\s*(?:[-*+]|\d+[.)]))(?:\s+(.*))?$")
_ORPHAN_SEP = re.compile(r"\s*·\s*" + re.escape(ORPHAN))
_ORPHAN_CLAUSE = re.compile(r",[^,.;:·\n\[\]]*?" + re.escape(ORPHAN))
_ORPHAN_BARE = re.compile(r"[ \t]*" + re.escape(ORPHAN))
# What a list item may hold besides its link and still say nothing: an
# inline icon (markdown or already drawn), a bold label, punctuation.
_ITEM_NOISE = re.compile(
    r"!\[[^\]]*\]\(icon:[^)]*\)|<span[^>]*>.*?</span>|\*\*[^*]+\*\*|[\s·,;:.\-–—]+"
)


def drop_orphan_links(text: str) -> str:
    """Take out every link marked :data:`ORPHAN`, its label with it.

    A dangling label reads as stray text ("…between groups. Run parameters"),
    so the label goes too, and with it what only introduced it: the `·` before
    a step's link, the clause it ended (", its path in the run parameters"),
    a list item left with nothing but its icon and bold label.
    """
    if ORPHAN not in text:
        return text
    lines = []
    for line in text.split("\n"):
        if ORPHAN in line:
            line = _ORPHAN_SEP.sub("", line)
            line = _ORPHAN_CLAUSE.sub("", line)
            line = _ORPHAN_BARE.sub("", line)
            m = _ORPHAN_ITEM.match(line)
            if m and not _ITEM_NOISE.sub("", m.group(2) or "").strip():
                continue  # the item was its link
        lines.append(line)
    return "\n".join(lines)


# ── The PDF's own drawing of a text tile's structures ───────────────────────

_FACT_ITEM = re.compile(
    r"^\s*[-*+]\s+!\[[^\]]*\]\(icon:(?P<icon>[a-z0-9-]+:[a-z0-9-]+)\)\s*"
    r"\*\*(?P<label>[^*\n]+)\*\*\s*(?P<rest>.*)$"
)
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]*(?:\([^)\n]*\))?[^)\n]*\)")


def _plain(text: str) -> str:
    """A line of markdown as the plain text a typst string holds."""
    text = _MD_LINK.sub(r"\1", text)
    text = re.sub(
        r"\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`", lambda m: next(g for g in m.groups() if g), text
    )
    return re.sub(r"\s+", " ", text).strip(" ·")


def _typst_icon(svg: str | None, color: str) -> str:
    if not svg:
        return "none"
    out = svg.replace("currentColor", color)
    if "xmlns=" not in out:
        out = out.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return _typst_str(out)


def _typst_only(code: str) -> str:
    return f':::: {{.content-visible when-format="typst"}}\n````{{=typst}}\n{code}\n````\n::::'


def _html_only(markdown: str) -> str:
    return f':::: {{.content-visible when-format="html"}}\n{markdown}\n::::'


def pdf_structures(
    markdown: str,
    icon_svg: Callable[[str], str | None],
    *,
    accent: str,
    mono: bool = False,
) -> str:
    """A text tile's stepper (``::: steps``) and fact lists ("The run": icon,
    bold label, value) twice: as written, for the page, and as the PDF's
    ``dpx-steps`` / ``dpx-facts``, which pandoc's own list would flatten.
    The values (``{{name}}``) stay placeholders, filled when the document runs.
    """
    lines = markdown.split("\n")
    out: list[str] = []
    i = 0
    disc = "#495057" if mono else accent
    while i < len(lines):
        line = lines[i]
        if _STEPS_OPEN.match(line):
            j = i + 1
            while j < len(lines) and not _DIV_CLOSE.match(lines[j]):
                j += 1
            block = lines[i : j + 1]
            steps = []
            for item in block[1:-1]:
                m = _STEP_ITEM.match(item)
                if not m or not (m.group("icon") or m.group("label")):
                    continue
                bits = [b for b in re.split(r"\s+·\s+", m.group("rest").strip()) if b.strip()]
                text = " · ".join(_plain(b) for b in bits if not _LINK_ONLY.match(b))
                icon = _typst_icon(
                    icon_svg(m.group("icon")) if m.group("icon") else None, "#ffffff"
                )
                steps.append(
                    f"({icon}, {_typst_str(_plain(m.group('label') or ''))}, {_typst_str(text)})"
                )
            out.append(_html_only("\n".join(block)))
            if steps:
                out.append(
                    _typst_only(f"#dpx-steps(({', '.join(steps)},), rgb({_typst_str(disc)}))")
                )
            i = j + 1
            continue
        m = _FACT_ITEM.match(line)
        if m and "{{legend:" not in line:
            j = i
            facts = []
            while (
                j < len(lines)
                and (fm := _FACT_ITEM.match(lines[j]))
                and "{{legend:" not in lines[j]
            ):
                icon = _typst_icon(icon_svg(fm.group("icon")), "#868e96")
                facts.append(
                    f"({icon}, {_typst_str(_plain(fm.group('label')))}, "
                    f"{_typst_str(_plain(fm.group('rest')))})"
                )
                j += 1
            out.append(_html_only("\n".join(lines[i:j])))
            out.append(_typst_only(f"#dpx-facts(({', '.join(facts)},))"))
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out)
