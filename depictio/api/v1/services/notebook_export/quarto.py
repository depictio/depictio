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
    # The same brand for a reader who prefers dark: with it the report follows
    # the reader's colour scheme (and offers Quarto's toggle).
    brand_dark: dict[str, Any] | None = None
    # Markup placed at the very top of the page, above Quarto's layout: the
    # report's header bar (``report_chrome.appbar_html``).
    before_body: str | None = None
    # Markup at the very end of the page, below it: the report's footer
    # (``report_chrome.footer_html``), outside every fold.
    after_body: str | None = None
    # Markup for the page's <head>, after Quarto's own stylesheets: the
    # report's controls and its one Quarto-DOM layer (``report_theme``).
    in_header: list[str] = field(default_factory=list)
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
        header = [{"text": t} for t in self.in_header if t]
        if self.favicon_data_uri:
            header.insert(0, {"text": f'<link rel="icon" href="{self.favicon_data_uri}">'})
        if header:
            doc["format"]["html"]["include-in-header"] = header[0] if len(header) == 1 else header
        if self.before_body:
            doc["format"]["html"]["include-before-body"] = {"text": self.before_body}
        if self.after_body:
            doc["format"]["html"]["include-after-body"] = {"text": self.after_body}
        if self.pdf:
            # The HTML is one self-contained file: a link to "the other
            # format" beside it would point at nothing once it is moved.
            doc["format"]["html"]["format-links"] = False
            typst: dict[str, Any] = {
                # The title page and the contents page are the document's own
                # (``pdf_typst``, a raw typst block opening the body): Quarto's
                # centred title block and its contents are left out.
                "title": "",
                "subtitle": "",
                "author": "",
                "date": "",
                "toc": False,
                # The document's parts are h2 (no h1: the title is the page's),
                # typst's are level 1: the results, a tab at 2, a section at 3.
                "shift-heading-level-by": -1,
                "papersize": "a4",
                "margin": {"x": "1.9cm", "top": "2.3cm", "bottom": "2.1cm"},
                "fig-format": "png",
                # The references are inline CSL (``references:``), which
                # typst's own bibliography cannot read: pandoc resolves them.
                "citeproc": True,
            }
            doc["format"]["typst"] = typst
        if self.brand and self.brand_dark:
            doc["brand"] = {"light": self.brand, "dark": self.brand_dark}
            doc["format"]["html"]["respect-user-color-scheme"] = True
        elif self.brand:
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
    rules: str | None = None,
    extra_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Depictio's Paper look as a Quarto brand, for one export.

    Quarto 1.9 takes ``brand`` inline in a document's front matter and
    compiles it into the page's Bootstrap theme: the colours (a white page,
    gray 9 ink, the instance's primary), Inter in front of the app's UI stack
    (or the brand's own family), Mantine's line height and Paper's radii and
    hairlines. The rest of the chrome (sections as paper panels, tiles as
    cards) is CSS the document's header carries, since it styles markup
    Bootstrap has no variable for.

    ``rules`` is the brand's SCSS rules layer (``defaults.bootstrap.rules``,
    ``report_theme.brand_rules``), compiled into this scheme's stylesheet
    after Bootstrap's; ``extra_defaults`` more Bootstrap/Quarto variables.
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
    defaults.update(extra_defaults or {})
    bootstrap: dict[str, Any] = {"defaults": defaults}
    if rules:
        bootstrap["rules"] = rules
    return {
        "color": {"primary": primary, "background": "#ffffff", "foreground": _INK},
        "defaults": {"bootstrap": bootstrap},
    }


# Mantine's dark scheme as the app's Paper draws it: dark 7 page, dark 0 ink,
# dark 2 dimmed, white hairlines.
_DARK_BG = "#1f1f1f"
_DARK_INK = "#c9c9c9"
_DARK_MUTED = "#828282"
_DARK_HAIR = "rgba(255, 255, 255, 0.1)"


def paper_brand_dark(
    *,
    primary: str,
    font_family: str | None = None,
    headings_font_family: str | None = None,
    rules: str | None = None,
    extra_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``paper_brand`` for the dark scheme: the same type and radii, Mantine's
    dark page and ink, the same primary."""
    brand = paper_brand(
        primary=primary,
        font_family=font_family,
        headings_font_family=headings_font_family,
        rules=rules,
        extra_defaults=extra_defaults,
    )
    brand["color"] = {"primary": primary, "background": _DARK_BG, "foreground": _DARK_INK}
    boot = brand["defaults"]["bootstrap"]["defaults"]
    boot.update(
        {
            "body-color": _DARK_INK,
            "body-bg": _DARK_BG,
            "text-muted": _DARK_MUTED,
            "border-color": _DARK_HAIR,
            "code-color": _DARK_INK,
        }
    )
    return brand
