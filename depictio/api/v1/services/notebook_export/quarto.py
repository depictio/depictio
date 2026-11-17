"""The Quarto document's front matter: the options its YAML header carries.

The export is one ``.qmd`` file (``cells.render_qmd``); this is what goes
between its leading ``---`` lines — title, the HTML report's layout, and the
Jupyter kernel the chunks execute through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class QuartoFrontMatter:
    title: str
    subtitle: str | None = None
    author: str | None = None
    date: str | None = None
    toc: bool = True
    echo: bool = False
    code_tools: bool = True
    embed_resources: bool = True
    # The tab icon, as a data URI. Quarto's own ``favicon`` option is a website
    # option and takes a path it expects to copy next to the output; a
    # single-file report has no "next to", so the icon is injected into the
    # head already inlined, like every other asset in these exports.
    favicon_data_uri: str | None = None
    # Quarto's article grid, widened. Its default body is sized for prose at
    # ~800px, and this is not prose: it carries dashboard tables of a dozen
    # columns, card rows three across and full-width figures, all of which the
    # default column makes the reader scroll sideways through. Not
    # ``page-layout: full`` — on a wide screen that stretches the narrative
    # text to an unreadable line length; a wider fixed column keeps both
    # legible. The margin grows with it so the contents stop wrapping every
    # section title onto two lines.
    body_width: str = "1100px"
    margin_width: str = "300px"
    # The report's theme, as Quarto's brand (``paper_brand``), inline in the
    # front matter so the export stays one file; ``None`` keeps Quarto's
    # stock Bootstrap (the classic look).
    brand: dict[str, Any] | None = None
    # Markup placed at the very top of the page, above Quarto's layout: the
    # report's header bar (``report_chrome.appbar_html``).
    before_body: str | None = None
    # Markup at the very end of the page, below it: the report's footer
    # (``report_chrome.footer_html``), outside every fold.
    after_body: str | None = None
    # A PDF beside the HTML (``quarto render --to typst``): Quarto's bundled
    # typst, so no TeX. Static figures and tables come from the notebook
    # client when the render asks for them (``DEPICTIO_STATIC_FIGURES``).
    pdf: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_yaml(self) -> str:
        doc: dict[str, Any] = {"title": self.title}
        if self.subtitle:
            doc["subtitle"] = self.subtitle
        if self.author:
            doc["author"] = self.author
        if self.date:
            doc["date"] = self.date
        doc["format"] = {
            "html": {
                "toc": self.toc,
                # The whole dashboard hangs off one title heading, so Quarto's
                # default (expand the active branch only) shows a contents list
                # with a single line in it until the reader scrolls. The point
                # of the contents here is to see every tab and section at once.
                "toc-expand": True,
                # Down to a section, not the headings inside a text tile: the
                # contents should mirror the dashboard's own navigation.
                "toc-depth": 4,
                # One global "View Source" affordance instead of a fold arrow
                # on every cell: the reader sees a clean report — narrative,
                # figures, cards, tables — with the code a click away rather
                # than a box between every result.
                "code-tools": self.code_tools,
                "embed-resources": self.embed_resources,
                "grid": {
                    "body-width": self.body_width,
                    "margin-width": self.margin_width,
                },
            }
        }
        if self.favicon_data_uri:
            doc["format"]["html"]["include-in-header"] = {
                "text": f'<link rel="icon" href="{self.favicon_data_uri}">'
            }
        if self.before_body:
            doc["format"]["html"]["include-before-body"] = {"text": self.before_body}
        if self.after_body:
            doc["format"]["html"]["include-after-body"] = {"text": self.after_body}
        if self.pdf:
            doc["format"]["typst"] = {
                "toc": True,
                "toc-depth": 3,
                "papersize": "a4",
                "margin": {"x": "1.8cm", "y": "2cm"},
                "fontsize": "10pt",
                "fig-format": "png",
                # The references are inline CSL (``references:``), which
                # typst's own bibliography cannot read: pandoc resolves them.
                "citeproc": True,
            }
        if self.brand:
            doc["brand"] = self.brand
        doc["jupyter"] = "python3"
        doc["execute"] = {"warning": False, "echo": self.echo}
        doc.update(self.extra)
        return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).strip()


# Mantine's gray 9 and 6 (the ink and the dimmed text of Paper), and Paper's
# hairline: gray 9 at 11%.
_INK = "#212529"
_MUTED = "#868e96"
_HAIR = "rgba(33, 37, 41, 0.11)"
_SYSTEM_SANS = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif'
)
_MONO = 'Menlo, Monaco, Consolas, "Courier New", monospace'


def paper_brand(
    *,
    primary: str,
    font_family: str | None = None,
    headings_font_family: str | None = None,
) -> dict[str, Any]:
    """Depictio's Paper look as a Quarto brand, for one export.

    Quarto 1.9 takes ``brand`` inline in a document's front matter and
    compiles it into the page's Bootstrap theme: the colours (a white page,
    gray 9 ink, the instance's primary), Inter in front of the app's UI stack
    (or the brand's own family), Mantine's line height and Paper's radii and
    hairlines. The rest of the chrome (sections as paper panels, tiles as
    cards) is CSS the document's header carries, since it styles markup
    Bootstrap has no variable for.
    """
    sans = font_family or f"'Inter Variable', Inter, {_SYSTEM_SANS}"
    defaults: dict[str, Any] = {
        "font-family-sans-serif": sans,
        "font-family-monospace": _MONO,
        "line-height-base": 1.55,
        "headings-font-weight": 700,
        "body-color": _INK,
        "body-bg": "#ffffff",
        "text-muted": _MUTED,
        "border-color": _HAIR,
        "border-radius": "0.75rem",
        "border-radius-sm": "0.5rem",
        "border-radius-lg": "1.125rem",
        "code-color": _INK,
    }
    if headings_font_family:
        defaults["headings-font-family"] = headings_font_family
    return {
        "color": {"primary": primary, "background": "#ffffff", "foreground": _INK},
        "defaults": {"bootstrap": {"defaults": defaults}},
    }
