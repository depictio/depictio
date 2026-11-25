"""The HTML report's look and its few behaviours, in the layers Quarto supports.

The report is one ``.qmd`` (the download is that one file), so the theme is
carried by the document itself rather than by a ``_extensions/`` folder that
would have to travel beside it. Each piece sits in the extension point Quarto
documents for it, from the most stable to the least:

1. **Brand** (``quarto.paper_brand``): colours, fonts, radii as Bootstrap
   variables, light and dark. Quarto compiles each scheme's stylesheet from it
   and swaps them itself.
2. **The brand's SCSS rules layer** (``brand.defaults.bootstrap.rules``,
   :func:`brand_rules`): the scheme's Paper tokens (``--gl-*``) and the
   refinements written against Bootstrap's own variables (``$body-bg``,
   ``$primary``...). Compiled into each scheme's stylesheet, so the dark page
   needs no ``body.quarto-dark`` override.
3. **One stylesheet** (:data:`CHROME_CSS`): the report's own controls (the
   colour-scheme button, the contents toggle, the tile's "i" and its popover)
   on CSS custom properties, so they work in the classic look too. The rules
   that have to name Quarto's internal markup (the contents, the anchors, the
   title block) are its second half, one block, with the Quarto version they
   were checked against (:data:`QUARTO_TESTED`).
4. **One script** (:data:`CHROME_JS`): the behaviours. They call Quarto's own
   hooks (``window.quartoToggleColorScheme``, the
   ``.quarto-color-scheme-toggle`` class its script keeps in step) instead of
   re-implementing them.

3 and 4 open the document body, beside the rest of the report's CSS, rather
than going through ``include-in-header``/``include-after-body``: Quarto 1.9
hands a document's front matter to pandoc as one command-line argument, which
Linux caps at 128 KB, and a report's header bar (its logo, the favicon)
already takes most of that. A front-matter include that grew the report's
YAML past it failed the render with "Argument list too long".

``test_quarto_hooks`` renders a small report with the Quarto on ``PATH`` and
asserts every hook named here still exists, so an upgrade that renames one
fails there, loudly, before a reader sees a broken page.
"""

from __future__ import annotations

from typing import Literal

from .resources import asset, script

#: The Quarto release the DOM layer below was written and checked against.
QUARTO_TESTED = "1.9.37"
#: This layer's own version, written into the page (``<meta name=
#: "depictio-report-chrome">``): which chrome a report in the wild carries.
CHROME_VERSION = "2"

Scheme = Literal["light", "dark"]

# Lucide's sun and moon, as the app header's theme toggle draws them
# (``chrome/variants/glass/parts.tsx`` ``ThemeTile``: a moon to go dark, a sun
# to go light).
_MOON = (
    '<svg class="dpx-icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>'
)
_SUN = (
    '<svg class="dpx-icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>'
    '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/>'
    '<path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>'
)

#: The colour-scheme button of the header bar. It carries Quarto's own
#: ``quarto-color-scheme-toggle`` class: Quarto then keeps it in step (its
#: ``alternate`` class) and does not float its own unlabelled switch in the
#: corner. The click calls Quarto's toggle (:data:`CHROME_JS`).
SCHEME_TOGGLE = (
    '<button type="button" class="quarto-color-scheme-toggle dpx-scheme-toggle" '
    'data-dpx-scheme-toggle aria-label="Switch to dark theme" title="Switch to dark theme">'
    f"{_MOON}{_SUN}</button>"
)


# Paper's tokens for each scheme, as ``glass.css`` resolves them against
# Mantine's palette (light) and its dark palette (dark).
_TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "--gl-fg": "#212529",
        "--gl-muted": "#868e96",
        "--gl-faint": "#adb5bd",
        "--gl-paper": "#ffffff",
        "--gl-hair": "rgba(33, 37, 41, 0.11)",
        "--gl-well": "rgba(33, 37, 41, 0.06)",
        "--gl-shade-a": "rgba(33, 37, 41, 0.05)",
        "--gl-shade-b": "rgba(33, 37, 41, 0.1)",
        "--dpx-info": "#0ca678",
    },
    "dark": {
        "--gl-fg": "#c9c9c9",
        "--gl-muted": "#828282",
        "--gl-faint": "#696969",
        "--gl-paper": "#1f1f1f",
        "--gl-hair": "rgba(255, 255, 255, 0.1)",
        "--gl-well": "rgba(255, 255, 255, 0.06)",
        "--gl-shade-a": "rgba(0, 0, 0, 0.3)",
        "--gl-shade-b": "rgba(0, 0, 0, 0.5)",
        "--gl-accent-fg": "color-mix(in srgb, var(--gl-accent) 75%, #fff)",
        "--gl-tile-shadow": "0 0 0 1px var(--gl-hair), 0 1px 2px var(--gl-shade-a)",
        "--dpx-info": "#38d9a9",
    },
}

# The rules both schemes share: everything is written against Bootstrap's
# variables, so each compiled stylesheet gets its own scheme's values.
_SHARED_RULES = asset("shared_rules.scss")


def brand_rules(scheme: Scheme) -> str:
    """The brand's SCSS rules layer for one colour scheme.

    Its Paper tokens on the root (they win over the ``:root`` defaults the
    notebook chrome sets for every renderer, and need no dark override), then
    the shared refinements. Quarto compiles it into that scheme's stylesheet
    (``brand.<scheme>.defaults.bootstrap.rules``)."""
    tokens = "; ".join(f"{k}: {v}" for k, v in _TOKENS[scheme].items())
    # `html:root`: above the notebook chrome's `:root` defaults, which come
    # later in the page, and on the root, so the page behind the body follows.
    return f"html:root {{ {tokens}; }}\n" + _SHARED_RULES.strip() + "\n"


#: Bootstrap and Quarto variables the brand sets beside the colours
#: (``brand.defaults.bootstrap.defaults``): the callout's edge and spacing.
BRAND_DEFAULTS: dict[str, str | int | float] = {
    "callout-border-width": "3px",
    "callout-margin-top": "1rem",
    "callout-margin-bottom": "1rem",
}


CHROME_CSS = f"""<style data-depictio-report-chrome="{CHROME_VERSION}; quarto {QUARTO_TESTED}">
/* ── Depictio report chrome: the report's own controls ─────────────────────
   On Paper's tokens with the classic look's values as fallbacks, so they read
   the same with or without the brand. */
.dpx-appbar-end {{ display: inline-flex; align-items: center; gap: 12px; }}
.dpx-icon-btn, .dpx-scheme-toggle, .dpx-toc-mode {{
  display: inline-flex; align-items: center; justify-content: center; flex: none;
  padding: 0; margin: 0; border: 1px solid transparent; background: transparent; cursor: pointer;
  color: var(--gl-muted, #868e96); line-height: 1;
  transition: color .12s ease, background-color .12s ease, border-color .12s ease;
}}
.dpx-scheme-toggle {{ width: 34px; height: 34px; border-radius: 10px; border-color: var(--gl-hair, #dee2e6); }}
.dpx-scheme-toggle svg {{ width: 18px; height: 18px; }}
.dpx-icon-btn:hover, .dpx-scheme-toggle:hover, .dpx-toc-mode:hover {{
  color: var(--gl-fg, #212529); background: var(--gl-well, #f1f3f5);
}}
.dpx-icon-btn:focus-visible, .dpx-scheme-toggle:focus-visible, .dpx-toc-mode:focus-visible,
.dpx-tile-links button:focus-visible {{
  outline: 2px solid var(--gl-accent, var(--dpx-primary, #228be6)); outline-offset: 2px;
}}
/* The icon is the scheme the button goes to: a moon on the light page, a sun
   on the dark one (the app header's toggle). */
.dpx-scheme-toggle .dpx-icon-sun {{ display: none; }}
body.quarto-dark .dpx-scheme-toggle .dpx-icon-sun {{ display: block; }}
body.quarto-dark .dpx-scheme-toggle .dpx-icon-moon {{ display: none; }}
/* A tile's action row (the "i", the combined file's "Open in dashboard"):
   right-aligned on its own line above the tile, never over it. */
.dpx-tile-links {{ display: flex; justify-content: flex-end; align-items: center; gap: 6px; margin: 0 0 4px; }}
.dpx-info {{
  width: 26px; height: 26px; border-radius: 999px;
  color: var(--dpx-info, #0ca678); background: var(--gl-paper, #fff);
  border: 1px solid var(--gl-hair, rgba(33, 37, 41, .11));
}}
.dpx-info svg {{ width: 16px; height: 16px; }}
.dpx-info:hover, .dpx-info[aria-expanded="true"] {{
  color: var(--dpx-info, #0ca678); background: color-mix(in srgb, var(--dpx-info, #0ca678) 10%, transparent);
}}
.dpx-info.dpx-info-named {{ width: auto; gap: 5px; padding: 0 10px 0 7px; font-size: 12px; font-weight: 600; }}
/* A card's own "i", in its bottom-right corner, where the dashboard puts a
   card's actions (its top-right holds the card's icon). */
.dpx-card-host {{ position: relative; }}
.dpx-card-info {{ position: absolute; right: 8px; bottom: 8px; z-index: 2; width: 24px; height: 24px; }}
/* With the script the note under a tile is the popover's: on screen the "i"
   opens it, and the page prints it open. */
@media screen {{ .callout.dpx-about.dpx-about-wired {{ display: none; }} }}
.dpx-pop {{
  position: absolute; z-index: 1200; width: 440px; max-width: calc(100vw - 24px);
  background: var(--gl-paper, #fff); color: var(--gl-fg, #212529);
  border: 1px solid var(--gl-hair, rgba(33, 37, 41, .11)); border-radius: 12px;
  box-shadow: 0 1px 2px var(--gl-shade-a, rgba(0, 0, 0, .05)), 0 18px 40px -18px var(--gl-shade-b, rgba(0, 0, 0, .25));
  padding: 12px 14px; font-size: .875rem; line-height: 1.55;
}}
.dpx-pop-head {{
  display: flex; align-items: center; gap: 6px; font-weight: 600; margin: 0 0 8px;
  padding: 0 0 8px 8px; border-left: 3px solid var(--dpx-pop-accent, #0ca678);
  border-bottom: 1px solid var(--gl-hair, rgba(33, 37, 41, .11));
}}
.dpx-pop-head svg {{ width: 16px; height: 16px; flex: none; color: var(--dpx-pop-accent, #0ca678); }}
.dpx-pop-body {{ max-height: min(70vh, 520px); overflow-y: auto; color: var(--gl-muted, #495057); }}
.dpx-pop-body > :last-child, .dpx-pop-body > :last-child > :last-child {{ margin-bottom: 0; }}
.dpx-pop-body strong {{ color: var(--gl-fg, #212529); }}
.dpx-pop-body:focus-visible {{ outline: 2px solid var(--gl-accent, #228be6); outline-offset: 2px; }}
@media print {{
  .dpx-scheme-toggle, .dpx-info, .dpx-pop, .dpx-toc-modes {{ display: none !important; }}
  .dpx-appbar {{ position: static !important; box-shadow: none !important; }}
}}

/* ── Quarto DOM layer ──────────────────────────────────────────────────────
   The only rules here that name Quarto's own markup. Checked against Quarto
   {QUARTO_TESTED}; every selector is asserted by test_quarto_hooks.py
   (``#TOC``, ``#toc-title``, ``#quarto-margin-sidebar``, ``.anchorjs-link``,
   ``.quarto-float-caption``, ``.quarto-color-scheme-toggle``). */
/* The contents stay clear of the sticky header bar. */
@media (min-width: 768px) {{
  body #quarto-margin-sidebar {{ top: 64px; max-height: calc(100vh - 72px); }}
}}
/* The contents, three ways (the bar's group): the outline, the tabs only, or
   none, the report then taking the column's width. Wherever the contents sit
   in the margin (768px and up, the report editor's preview included);
   narrower, Quarto folds them into its own menu and the group steps aside. */
.dpx-toc-modes {{
  display: inline-flex; align-items: center; gap: 2px; padding: 2px;
  border: 1px solid var(--gl-hair, #dee2e6); border-radius: 10px;
}}
.dpx-toc-mode {{ width: 28px; height: 28px; border-radius: 8px; }}
.dpx-toc-mode svg {{ width: 16px; height: 16px; }}
.dpx-toc-mode[aria-pressed="true"] {{
  color: var(--gl-fg, #212529); background: var(--gl-well, #f1f3f5);
}}
@media (min-width: 768px) {{
  /* Light: the tabs, one short line each, nothing under them. */
  body[data-dpx-toc="light"] #TOC {{ font-size: .75rem; }}
  body[data-dpx-toc="light"] #TOC ul ul ul {{ display: none !important; }}
  body[data-dpx-toc="light"] #TOC li > a {{ padding-top: 1px; padding-bottom: 1px; }}
  body[data-dpx-toc="light"] #TOC .dpx-toc-chev {{ visibility: hidden; }}
  /* Hidden: the column goes, the report runs to the page's edge. */
  body[data-dpx-toc="hidden"] #quarto-margin-sidebar {{ display: none !important; }}
  body[data-dpx-toc="hidden"] #quarto-content > main.content {{ grid-column: body-content-start / page-end; }}
}}
@media (max-width: 767.98px) {{ .dpx-toc-modes {{ display: none; }} }}
/* Heading anchors (anchorjs): right after the heading's text, before its
   aside and before the heading's own actions ("Collapse all"), which keep the
   far end of the line. */
:is(h1, h2, h3, h4, h5, h6) > .anchorjs-link {{ order: 1; margin-inline-start: .35em; }}
:is(h1, h2, h3, h4, h5, h6) > .dpx-h-note {{ order: 2; }}
:is(h1, h2, h3, h4, h5, h6) > .dpx-all {{ order: 3; }}
/* A figure's or a table's anchor sits after its caption (moved there by the
   script): its default place, the float's top-right corner, is where a tile
   keeps its actions. Shown with the float's hover, as the headings' are. */
.quarto-float-caption > .anchorjs-link, figcaption > .anchorjs-link {{
  position: static !important; margin-inline-start: .35em; opacity: 0; text-decoration: none;
}}
.quarto-figure:hover .anchorjs-link, div[id^="tbl-"]:hover .anchorjs-link,
.quarto-float-caption > .anchorjs-link:focus {{ opacity: 1; }}
/* A tile the export could not draw (its placeholder on screen, no runtime
   drawing it instead) has no data to date: its caption drops the badge. */
:is(.quarto-float, div[id^="fig-"], div[id^="tbl-"]):has(.dpx-unavailable):not(:has([data-depictio-mounted])) .dpx-asof {{
  display: none;
}}
/* The title block's subtitle under the dashboard's name. */
.quarto-title-block .subtitle {{ margin-top: .25rem; }}
</style>"""


# The behaviours, after the body (Quarto's own scripts have run). Idempotent:
# a pass is repeated as the page finishes loading and whenever the combined
# file's host adds its own controls (``dpx:tile-actions``).
CHROME_JS = script("report_chrome.js")
