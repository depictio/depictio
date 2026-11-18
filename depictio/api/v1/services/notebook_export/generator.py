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
from html import escape as _esc
from typing import Any

import polars as pl

from depictio.models.models.analysis_state import (
    AnalysisState,
    NotebookPreflight,
    NotebookPreflightComponent,
    NotebookPreflightDC,
    NotebookPreflightStage,
)
from depictio.notebook.report_runtime import (
    filters_placeholder,
    tile_close,
    tile_open,
    tile_ref,
)
from depictio.notebook.theme import resolve_primary, sans_stack

from .aggregations import agg_expr_source
from .cells import Cell, md_cell, render_qmd
from .classify import Classification, classify
from .names import NameAllocator, slug
from .pdf_typst import typst_preamble
from .predicates import PredicateSource, emit_filter_expr, emit_predicate
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
    stepper_markdown,
    title_logo_css,
)
from .report_theme import BRAND_DEFAULTS, CHROME_CSS, CHROME_JS, brand_rules

# What a highlight can show (``highlightTile.ts``: ``HIGHLIGHTABLE_TYPES``).
_HIGHLIGHTABLE = frozenset({"figure", "advanced_viz"})

# Shade 6 of ``@mantine/core``'s own ``DEFAULT_COLORS`` — the shade every
# icon/accent use in the live app resolves a bare palette name to. The server
# has no Mantine theme to ask, so a section's or tab's ``color`` (``"teal"``,
# picked from the same palette the editor's colour picker offers) is resolved
# against this fixed copy instead of hand-waving a different blue everywhere.
_MANTINE_SHADE_6 = {
    "dark": "#2e2e2e",
    "gray": "#868e96",
    "red": "#fa5252",
    "pink": "#e64980",
    "grape": "#be4bdb",
    "violet": "#7950f2",
    "indigo": "#4c6ef5",
    "blue": "#228be6",
    "cyan": "#15aabf",
    "teal": "#12b886",
    "green": "#40c057",
    "lime": "#82c91e",
    "yellow": "#fab005",
    "orange": "#fd7e14",
}
_CSS_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\()")
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
# The closing part: what produced the data and the report, and what to cite.
METHODS_HEADING = "Methods and citations"
METHODS_ICON = "mdi:book-open-variant"

# ``activeFilters.ts``: what the panel's summary prints for a filter's value.
_MAX_INLINE_VALUES = 2
_MAX_LABEL_CHARS = 28
_RANGE_TYPES = frozenset({"RangeSlider", "DateRangePicker", "DatePicker", "Timeline"})

# ``FunnelView.tsx``'s marker palette, in order, as Mantine resolves it.
_FUNNEL_PALETTE = (
    "#12b886",  # teal 6
    "#228be6",  # blue 6
    "#7950f2",  # violet 6
    "#fd7e14",  # orange 6
    "#e64980",  # pink 6
    "#15aabf",  # cyan 6
    "#be4bdb",  # grape 6
    "#74b816",  # lime 7
)

# The chrome the three formats cannot get from Depictio's own stylesheets: the
# section rail, and the fold the live dashboard gets from Mantine's accordion.
# Inline rather than a linked asset, like every other asset in these exports —
# the file has to still work months later, off the network that served it — and
# strictly additive: without the script the headings, the colours, the icons and
# every number are all still there, they just do not fold.
NOTEBOOK_CHROME = """<style>
/* The app's own type and colour, so an export reads as the same product as
   the dashboard it came from. These are the values `buildDepictioTheme`
   passes to Mantine (`brandTheme.ts`) and the Mantine 7 defaults it leaves
   alone: the system sans stack, `defaultRadius: md` (8px), gray-4 borders,
   gray-6 for dimmed text, and body text at line-height 1.55. Scoped to the
   document body rather than `*`, so the host's own chrome keeps its look. */
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
    Ubuntu, Cantarell, sans-serif;
  line-height: 1.55;
  color: #000;
}
body code, body pre, body kbd, body samp {
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
}
/* Mantine's heading scale (h1 2.125rem … h4 1.125rem), all at weight 700. */
body h1 { font-size: 2.125rem; line-height: 1.3; font-weight: 700; }
body h2 { font-size: 1.625rem; line-height: 1.35; font-weight: 700; }
body h3 { font-size: 1.375rem; line-height: 1.4; font-weight: 700; }
body h4 { font-size: 1.125rem; line-height: 1.45; font-weight: 700; }
body h5 { font-size: 1rem; line-height: 1.5; font-weight: 700; }
body h6 { font-size: .875rem; line-height: 1.5; font-weight: 700; }
/* `Code`/`Table` as Mantine draws them: a tinted block on gray-0, rows split
   by a gray-4 rule and nothing between the columns. */
body :not(pre) > code { background: #f8f9fa; border-radius: .25rem; padding: .1em .35em; }
body pre { background: #f8f9fa; border-radius: .5rem; }
body table:not(.dpx-plain) { border-collapse: collapse; }
body table:not(.dpx-plain) th { border-bottom: 1px solid #ced4da; }
body table:not(.dpx-plain) td { border-bottom: 1px solid #f1f3f5; }
.dpx-h { cursor: pointer; }
.dpx-hc { color: var(--dpx-hc); }
.dpx-chev {
  display: inline-block; width: .8em; font-size: .65em; opacity: .45;
  margin-inline-end: .28em; transition: transform .15s ease;
}
.dpx-folded > .dpx-chev, .dpx-folded > a > .dpx-chev { transform: rotate(-90deg); }
#TOC .dpx-chev { cursor: pointer; }
/* A branch with nothing under it keeps the slot, so titles stay aligned. */
#TOC .dpx-gap { visibility: hidden; cursor: default; }
/* Fold the whole report at once. It rides on the results heading rather than
   floating over the page: that is the one heading every tab hangs off, so the
   control sits where the thing it collapses begins. */
.dpx-all {
  margin-inline-start: auto; font: inherit; font-size: .6em; font-weight: 500;
  color: #868e96; background: none; border: 1px solid currentColor;
  border-radius: 999px; padding: .3em 1em; cursor: pointer; opacity: .7;
  white-space: nowrap;
}
.dpx-all:hover { opacity: 1; }
/* A tab's own fold control sits on its heading, smaller than the report's. */
.dpx-tab-all { font-size: .5em; }
/* A heading's aside ("2 active"): quiet, and not repeated in the contents. */
.dpx-h-note {
  font-size: .62em; font-weight: 500; color: #868e96; margin-inline-start: .6em;
  white-space: nowrap;
}
#TOC .dpx-h-note, nav[role="doc-toc"] .dpx-h-note { display: none; }
/* Icon and title on one optical line. The glyph is sized in `em`, so it
   follows the heading's size, but an inline box hangs it off the baseline
   and it reads as sitting too low next to large text. Laying the heading out
   as a flex row centres the icon against the text instead; the same applies
   to the copies Quarto puts in the table of contents. Browsers without
   `:has()` fall back to the baseline shift the span carries itself. */
h1:has(> span[data-dpx-accent]), h2:has(> span[data-dpx-accent]),
h3:has(> span[data-dpx-accent]), h4:has(> span[data-dpx-accent]),
h5:has(> span[data-dpx-accent]), h6:has(> span[data-dpx-accent]),
a:has(> span[data-dpx-accent]) { display: flex; align-items: center; }
[data-dpx-accent] svg { display: block; }
/* The section accordion's accent rail (`sectionAccordion.css`): 3px of the
   section's own colour, falling back to the default border like the app's
   `--section-accent` does, with the body indented by one Mantine `md`. */
.dpx-body {
  border-inline-start: 3px solid var(--dpx-accent, #ced4da);
  padding-inline-start: 16px; margin: .3rem 0 1.4rem 3px;
}
.dpx-body > .dpx-body { margin-bottom: .8rem; }
/* A card is built to stand on its own — inline-block, with a minimum width
   that keeps its number readable. In a row it is a grid cell instead, and
   has to give that width up or three cards will not share one line. */
.dpx-cards > div {
  display: block !important; width: 100% !important;
  min-width: 0 !important; margin: 0 !important; box-sizing: border-box;
}
/* The chrome the host renderer draws around the report — Quarto's contents
   sidebar, its links, its code toggle — carrying the instance's own primary
   colour and Mantine's proportions, so the page around the dashboard reads as
   the same product as the dashboard. Selectors the other two renderers do not
   have simply match nothing there. */
body a { color: var(--dpx-primary, #228be6); }
nav[role="doc-toc"], #quarto-margin-sidebar { font-size: .8125rem; }
nav[role="doc-toc"] > h2, #toc-title {
  font-size: .75rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; color: #868e96;
}
nav[role="doc-toc"] a { color: #495057; }
nav[role="doc-toc"] a:hover { color: var(--dpx-primary, #228be6); }
nav[role="doc-toc"] a.active {
  color: var(--dpx-primary, #228be6); font-weight: 600;
  border-inline-start-color: var(--dpx-primary, #228be6);
}
/* Quarto's "Code" toggle as a Mantine `variant="default"` button. */
#quarto-code-tools-source .btn, .code-tools-button {
  border: 1px solid #ced4da; border-radius: .5rem; color: #495057;
  background: #fff; font-size: .8125rem; font-weight: 500;
}
#quarto-code-tools-source .btn:hover, .code-tools-button:hover { background: #f8f9fa; }
/* Plotly draws its dropdown in SVG, and the one thing it will not take from
   the figure's own options is a corner radius — but the rects it draws take
   one from CSS. The rest (font, padding, colours) is set on the figure, where
   Plotly can measure the text it is sizing the box around. This is the
   fallback the script below replaces; it shows only until then. */
.updatemenu-item-rect { rx: 8px; ry: 8px; stroke: #ced4da; }
.updatemenu-header-arrow { fill: #868e96; }
.updatemenu-dropdown-button-group .updatemenu-item-rect { rx: 6px; ry: 6px; stroke: none; }
/* The same control as an HTML select, in the document's own flow: a Plotly
   menu is placed in paper coordinates, so on a figure with a wide label
   gutter it can only ever float above the middle of the plot. */
.dpx-controls {
  display: flex; align-items: center; gap: .5rem;
  margin: 0 0 .5rem; font-size: .8125rem;
}
.dpx-controls > span { color: #868e96; font-weight: 500; }
.dpx-select-wrap { position: relative; display: inline-flex; align-items: center; }
.dpx-select-wrap::after {
  content: '▾'; position: absolute; right: .7em;
  color: #868e96; font-size: .8em; pointer-events: none;
}
.dpx-select {
  font: inherit; color: #495057; line-height: 1.55;
  background-color: #fff; border: 1px solid #ced4da; border-radius: .5rem;
  padding: .3em 2em .3em .7em; cursor: pointer; appearance: none;
}
.dpx-select:hover { background-color: #f8f9fa; }
.dpx-select:focus {
  outline: none; border-color: var(--dpx-primary, #228be6);
}
/* The tile's full-screen control, as the app draws it: a subtle square button
   that only appears on hover, so a report at rest is a report and not a row of
   affordances. */
.dpx-zoomable { position: relative; }
.dpx-zoom {
  position: absolute; top: 4px; right: 4px; z-index: 3;
  font: inherit; font-size: .8rem; line-height: 1;
  color: #868e96; background: #fff; border: 1px solid #ced4da;
  border-radius: .5rem; padding: .3em .5em; cursor: pointer;
  opacity: 0; transition: opacity .15s ease;
}
.dpx-zoomable:hover > .dpx-zoom, .dpx-zoom:focus { opacity: 1; }
.dpx-zoom:hover { background: #f8f9fa; color: #495057; }
.dpx-full {
  position: fixed !important; inset: 0 !important; z-index: 9999 !important;
  margin: 0 !important; padding: 2.75rem 1.25rem 1.25rem !important;
  background: #fff; overflow: auto; box-sizing: border-box;
}
.dpx-full > .dpx-zoom { opacity: 1; top: 10px; right: 14px; }
/* A table full screen should scroll on its own, with its header in view. */
.dpx-full table { width: 100%; }
.dpx-full thead th { position: sticky; top: 0; background: #fff; z-index: 1; }
</style>
<script>
(function () {
  var SEL = 'h1,h2,h3,h4,h5,h6';
  function levelOf(el) { return parseInt(el.tagName.charAt(1), 10); }
  function headingIn(el) { return el.matches(SEL) ? el : el.querySelector(SEL); }
  // What a heading introduces. Quarto wraps each heading and its content in a
  // <section>, so there the body is simply the rest of that wrapper; a heading
  // that is not the first child of one (raw HTML, a heading inside a tile)
  // walks forward to the next heading of the same or higher rank.
  function bodyOf(h) {
    var out = [], p = h.parentElement, n;
    if (p && p.tagName === 'SECTION' && p.firstElementChild === h) {
      for (n = h.nextElementSibling; n; n = n.nextElementSibling) out.push(n);
      return out;
    }
    var block = h, stop = ['BODY', 'MAIN', 'ARTICLE', 'SECTION'];
    while (block.parentElement &&
           block.parentElement.childElementCount === 1 &&
           block.parentElement.firstElementChild === block &&
           stop.indexOf(block.parentElement.tagName) < 0) {
      block = block.parentElement;
    }
    var lvl = levelOf(h);
    for (n = block.nextElementSibling; n; n = n.nextElementSibling) {
      var inner = headingIn(n);
      if (inner && levelOf(inner) <= lvl) break;
      out.push(n);
    }
    return out;
  }
  // Folded content is still in the page, only hidden: what it holds was drawn
  // (or will be) at a size it could not measure. Every unfold re-fits the
  // figures it reveals and tells anything else listening (the report runtime,
  // Plotly's own responsive handler) that the layout changed.
  function setFold(h, body, folded) {
    h.classList.toggle('dpx-folded', folded);
    body.style.display = folded ? 'none' : '';
  }
  function reveal(body) {
    controls();
    refit();
    try {
      window.dispatchEvent(new Event('resize'));
      document.dispatchEvent(new CustomEvent('dpx:reveal', { detail: body }));
    } catch (e) { /* an old browser keeps the static fit */ }
  }
  function fold(h, body, closed) {
    h.classList.add('dpx-h');
    var chev = document.createElement('span');
    chev.className = 'dpx-chev';
    chev.textContent = '▾';
    h.insertBefore(chev, h.firstChild);
    h.addEventListener('click', function (ev) {
      if (ev.target.closest('a, button')) return;
      var folded = !h.classList.contains('dpx-folded');
      setFold(h, body, folded);
      if (!folded) reveal(body);
      syncTabButtons();
    });
    // The export's default for this heading: a tab after the first, a
    // section the dashboard opens folded, the filters.
    if (closed) setFold(h, body, true);
  }
  // These documents embed every figure, so the browser is still parsing the
  // page long after the script first runs: a heading enhanced early would keep
  // only the part of its body that existed then, and the sections parsed after
  // it would sit outside its rail. Each pass re-checks what has since arrived.
  var pairs = [];
  function absorb(h, body) {
    var lvl = levelOf(h), n = body.nextElementSibling, next;
    while (n) {
      var inner = headingIn(n);
      if (inner && levelOf(inner) <= lvl) break;
      next = n.nextElementSibling;
      body.appendChild(n);
      n = next;
    }
  }
  function enhance() {
    var marks = document.querySelectorAll('span[data-dpx-accent]:not([data-dpx-seen])');
    for (var i = 0; i < marks.length; i++) {
      var mark = marks[i];
      mark.setAttribute('data-dpx-seen', '1');
      var h = mark.closest(SEL);
      if (!h) continue;
      var nodes = bodyOf(h);
      if (!nodes.length) continue;
      var body = document.createElement('div');
      body.className = 'dpx-body';
      var accent = mark.getAttribute('data-dpx-accent');
      var kind = mark.getAttribute('data-dpx-kind') || '';
      if (accent) body.style.setProperty('--dpx-accent', accent);
      body.setAttribute('data-dpx-kind', kind);
      // The heading's own wrapper (Quarto's <section>) carries the kind and
      // the accent too: a theme that frames a whole section, heading
      // included, styles that element.
      if (h.parentElement && h.parentElement.tagName === 'SECTION') {
        h.parentElement.setAttribute('data-dpx-kind', kind);
        if (accent) h.parentElement.style.setProperty('--dpx-accent', accent);
      }
      nodes[0].parentNode.insertBefore(body, nodes[0]);
      for (var j = 0; j < nodes.length; j++) body.appendChild(nodes[j]);
      fold(h, body, mark.getAttribute('data-dpx-fold') === 'closed');
      pairs.push([h, body]);
    }
    for (var k = 0; k < pairs.length; k++) absorb(pairs[k][0], pairs[k][1]);
    tabButtons();
    if (!hashDone && location.hash) {
      hashDone = true;
      openHash(location.hash);
    }
    collapseAll();
    tocFold();
    controls();
    zoomable();
    refit();
  }
  // A figure's own dropdown, lifted out of the figure. Plotly places a menu in
  // paper coordinates — there is no container-relative reference for one — so
  // on a figure whose labels need a wide left gutter the menu lands above the
  // middle of the plot, attached to nothing. As an HTML select it sits in the
  // flow above the figure, flush with everything else on the page, and looks
  // like the app's own controls rather than drawn text. The figure keeps its
  // menu as the thing this replaces: until this runs, it is what works.
  function controls() {
    if (!window.Plotly) return;
    var plots = document.querySelectorAll('.js-plotly-plot');
    for (var i = 0; i < plots.length; i++) {
      var gd = plots[i];
      var menu = gd.layout && gd.layout.updatemenus && gd.layout.updatemenus[0];
      if (!menu || !menu.buttons || !menu.buttons.length) continue;
      // A folded figure has no size yet, and hiding a menu re-computes the
      // margins around it: leave it for the pass that runs when it comes back.
      if (gd.getAttribute('data-dpx-select') || !gd.clientWidth) continue;
      gd.setAttribute('data-dpx-select', '1');
      // At the top of the output cell, not next to the figure: Plotly wraps a
      // figure in a box of exactly its height, and anything added in there
      // pushes the figure straight back out of it.
      var box = gd.closest(OUTPUT) || gd.parentNode;
      box.insertBefore(selectBar(gd, menu), box.firstChild);
      Plotly.relayout(gd, { 'updatemenus[0].visible': false });
    }
  }
  function selectBar(gd, menu) {
    var bar = document.createElement('div');
    bar.className = 'dpx-controls';
    if (menu.name) {
      var label = document.createElement('span');
      label.textContent = menu.name;
      bar.appendChild(label);
    }
    var wrap = document.createElement('span');
    wrap.className = 'dpx-select-wrap';
    var sel = document.createElement('select');
    sel.className = 'dpx-select';
    if (menu.name) sel.setAttribute('aria-label', menu.name);
    for (var i = 0; i < menu.buttons.length; i++) {
      var opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = menu.buttons[i].label;
      sel.appendChild(opt);
    }
    sel.value = String(menu.active || 0);
    sel.addEventListener('change', function () {
      var b = menu.buttons[parseInt(sel.value, 10)];
      if (!b) return;
      var args = b.args || [];
      if (b.method === 'relayout') Plotly.relayout(gd, args[0] || {});
      else if (b.method === 'restyle') Plotly.restyle(gd, args[0] || {}, args[1]);
      else Plotly.update(gd, args[0] || {}, args[1] || {});
    });
    wrap.appendChild(sel);
    bar.appendChild(wrap);
    return bar;
  }
  // A Plotly figure sizes itself to its container once, when it draws. Wrapping
  // it in a rail afterwards takes that container ~20px narrower, and the figure
  // keeps the width it measured: every plot in the report ends up with its own
  // horizontal scrollbar. Re-fit whatever no longer matches its box — the same
  // pass puts a figure back together after it is opened full screen.
  function refit() {
    if (!window.Plotly || !Plotly.Plots) return;
    var plots = document.querySelectorAll('.js-plotly-plot');
    for (var i = 0; i < plots.length; i++) {
      var p = plots[i];
      if (!p._fullLayout || !p.clientWidth) continue;
      if (Math.abs(p._fullLayout.width - p.clientWidth) > 1) Plotly.Plots.resize(p);
    }
  }
  // The tile control the dashboard has: one button that takes a result to the
  // whole viewport and back. A report is read on screens the export knows
  // nothing about, and a 12-column table or a dense heatmap is the case the
  // page column cannot win. Only computed results get it — the header's own
  // tables are chrome, not results.
  var OUTPUT = '.cell-output-display';
  function zoomable() {
    var found = document.querySelectorAll(OUTPUT + ', .js-plotly-plot');
    for (var i = 0; i < found.length; i++) {
      var box = found[i].closest(OUTPUT) || found[i].parentElement;
      if (!box || box.getAttribute('data-dpx-zoom')) continue;
      if (!box.querySelector('.js-plotly-plot, table, img')) continue;
      box.setAttribute('data-dpx-zoom', '1');
      box.classList.add('dpx-zoomable');
      box.appendChild(zoomButton(box));
    }
  }
  function zoomButton(box) {
    var b = document.createElement('button');
    b.className = 'dpx-zoom';
    b.type = 'button';
    b.title = 'Full screen';
    b.textContent = '⤡';
    b.addEventListener('click', function () {
      var on = box.classList.toggle('dpx-full');
      b.textContent = on ? '✕' : '⤡';
      b.title = on ? 'Close' : 'Full screen';
      document.documentElement.style.overflow = on ? 'hidden' : '';
      // A figure carries the size the export chose for a page column; full
      // screen it should use the room it just got, and get its own size back
      // on the way out. Both dimensions are set outright rather than left to
      // `Plots.resize`: a figure that has already been re-fitted once carries
      // an explicit width, and resizing no longer moves it.
      var plots = box.querySelectorAll('.js-plotly-plot'), jobs = [];
      for (var i = 0; i < plots.length; i++) {
        var p = plots[i], lay = p.layout || {};
        if (on) {
          p.setAttribute('data-dpx-size', (lay.width || '') + ',' + (lay.height || ''));
          jobs.push(
            Plotly.relayout(p, {
              width: box.clientWidth - 40,
              height: window.innerHeight - 80,
            })
          );
        } else {
          var prev = (p.getAttribute('data-dpx-size') || ',').split(',');
          jobs.push(
            Plotly.relayout(p, {
              width: prev[0] ? parseFloat(prev[0]) : null,
              height: prev[1] ? parseFloat(prev[1]) : null,
            })
          );
        }
      }
      // Only once those have landed: `relayout` is async, and re-fitting a
      // figure Plotly is still redrawing leaves it at the width it just left.
      if (jobs.length && jobs[0] && jobs[0].then) Promise.all(jobs).then(refit);
      else refit();
    });
    return b;
  }
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    var open = document.querySelector('.dpx-full > .dpx-zoom');
    if (open) open.click();
  });
  // Printing prints the whole report: every fold opens for the page (a folded
  // tab would print as its title alone) and closes again after. The print
  // stylesheet hides the fold controls and starts each tab on a new page.
  var printFolds = null;
  window.addEventListener('beforeprint', function () {
    printFolds = pairs.map(function (p) { return p[0].classList.contains('dpx-folded'); });
    for (var i = 0; i < pairs.length; i++) setFold(pairs[i][0], pairs[i][1], false);
    refit();
  });
  window.addEventListener('afterprint', function () {
    if (!printFolds) return;
    for (var i = 0; i < pairs.length; i++) setFold(pairs[i][0], pairs[i][1], printFolds[i]);
    printFolds = null;
    syncTabButtons();
  });
  function setAll(folded) {
    for (var i = 0; i < pairs.length; i++) setFold(pairs[i][0], pairs[i][1], folded);
    // A figure unfolded back into view was never measured while hidden.
    if (!folded) reveal(document.body);
    syncTabButtons();
  }
  function kindOf(pair) { return pair[1].getAttribute('data-dpx-kind') || ''; }
  // The sections of one tab: every folding heading inside its body.
  function sectionsOf(tab) {
    var out = [];
    for (var i = 0; i < pairs.length; i++) {
      if (pairs[i] !== tab && tab[1].contains(pairs[i][0])) out.push(pairs[i]);
    }
    return out;
  }
  function tabOpen(tab) {
    if (tab[0].classList.contains('dpx-folded')) return false;
    var secs = sectionsOf(tab);
    for (var i = 0; i < secs.length; i++) {
      if (!secs[i][0].classList.contains('dpx-folded')) return true;
    }
    return secs.length === 0;
  }
  // The dashboard's own "Collapse all / Expand all", one per tab: it folds the
  // tab's sections, or opens the tab and every section in it.
  function tabButtons() {
    for (var i = 0; i < pairs.length; i++) {
      var tab = pairs[i];
      if (kindOf(tab) !== 'tab' || tab[0].querySelector('.dpx-tab-all')) continue;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dpx-all dpx-tab-all';
      btn.addEventListener('click', (function (t, b) {
        return function (ev) {
          ev.stopPropagation();
          var open = tabOpen(t), secs = sectionsOf(t);
          if (open && !secs.length) {
            setFold(t[0], t[1], true);
          } else if (open) {
            for (var j = 0; j < secs.length; j++) setFold(secs[j][0], secs[j][1], true);
          } else {
            setFold(t[0], t[1], false);
            for (var k = 0; k < secs.length; k++) setFold(secs[k][0], secs[k][1], false);
            reveal(t[1]);
          }
          syncTabButtons();
        };
      })(tab, btn));
      tab[0].appendChild(btn);
    }
    syncTabButtons();
  }
  function syncTabButtons() {
    for (var i = 0; i < pairs.length; i++) {
      var btn = kindOf(pairs[i]) === 'tab' && pairs[i][0].querySelector('.dpx-tab-all');
      if (btn) btn.textContent = tabOpen(pairs[i]) ? 'Collapse all' : 'Expand all';
    }
  }
  // A link into folded content (the contents list, a tab link in the text,
  // a shared #anchor) opens every fold on the way to it, then the target's
  // own heading.
  var hashDone = false;
  function openTo(target) {
    var opened = null;
    for (var i = 0; i < pairs.length; i++) {
      var h = pairs[i][0], b = pairs[i][1];
      if (!h.classList.contains('dpx-folded')) continue;
      if (b.contains(target) || h === target || h.parentElement === target) {
        setFold(h, b, false);
        opened = opened || b;
      }
    }
    if (opened) { reveal(opened); syncTabButtons(); }
  }
  function openHash(hash) {
    var id = hash.charAt(0) === '#' ? hash.slice(1) : hash;
    try { id = decodeURIComponent(id); } catch (e) { /* keep it as written */ }
    var el = id && document.getElementById(id);
    if (el) openTo(el);
  }
  document.addEventListener('click', function (ev) {
    var a = ev.target.closest && ev.target.closest('a[href^="#"]');
    if (a) openHash(a.getAttribute('href'));
  }, true);
  window.addEventListener('hashchange', function () { openHash(location.hash); });
  // One control for the whole report, on the heading the tabs hang off. It
  // lives in the heading and not in its body, so it stays reachable once
  // everything below it is folded away.
  function collapseAll() {
    // Off `pairs` and not the document: Quarto copies a heading's markup into
    // the contents list, which comes first in the DOM, and that copy is not
    // inside a heading at all. `pairs` only ever holds real ones.
    var h = null;
    for (var i = 0; i < pairs.length && !h; i++) {
      if (pairs[i][0].querySelector('span[data-dpx-kind="results"]')) h = pairs[i][0];
    }
    if (!h || h.querySelector('.dpx-all')) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dpx-all';
    btn.textContent = 'Collapse all';
    btn.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var folded = btn.getAttribute('data-folded') !== '1';
      setAll(folded);
      btn.setAttribute('data-folded', folded ? '1' : '0');
      btn.textContent = folded ? 'Expand all' : 'Collapse all';
    });
    h.appendChild(btn);
  }
  // The contents list mirrors the document, so it folds the same way. Quarto
  // builds it as plain nested lists; the other two formats have no #TOC and
  // this does nothing there.
  function tocFold() {
    var toc = document.getElementById('TOC');
    if (!toc) return;
    var items = toc.querySelectorAll('li:not([data-dpx-toc])');
    for (var i = 0; i < items.length; i++) {
      var li = items[i];
      li.setAttribute('data-dpx-toc', '1');
      var link = li.querySelector(':scope > a');
      if (!link) continue;
      var sub = li.querySelector(':scope > ul');
      var chev = document.createElement('span');
      chev.className = sub ? 'dpx-chev' : 'dpx-chev dpx-gap';
      chev.textContent = '\\u25BE';
      if (sub) {
        chev.addEventListener('click', function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          var host = this.closest('li');
          var ul = host.querySelector(':scope > ul');
          ul.style.display = host.classList.toggle('dpx-folded') ? 'none' : '';
        });
      }
      link.insertBefore(chev, link.firstChild);
    }
    // The list as a whole folds from its title's own button (``report_theme``).
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhance);
  } else {
    enhance();
  }
  // Quarto's own scripts can move content around after load (and Plotly
  // mounts its figures late); re-running is cheap and skips what it has done.
  window.addEventListener('load', enhance);
  setTimeout(enhance, 500);
  setTimeout(enhance, 2500);
})();
</script>"""


# Paper, the live app's default chrome (`chrome/variants/glass/glass.css`),
# laid over the chrome above: the report as the dashboard reads in the app.
# Every value is a `--gl-*` token of that stylesheet resolved for the light
# scheme against Mantine's palette (CSS can mix colours itself, so the
# hairlines keep the stylesheet's own `color-mix`). The body font and the
# primary come from the brand (`--dpx-font`, `--dpx-primary`,
# `--dpx-accent-fg`, set beside it). Strictly a restyle: no structure, no
# script, so a report without it is the classic look with every result intact.
PAPER_CHROME = """<style>
:root {
  --gl-fg: #212529;
  --gl-muted: #868e96;
  --gl-faint: #adb5bd;
  --gl-paper: #ffffff;
  --gl-accent: var(--dpx-primary, #228be6);
  --gl-accent-fg: var(--dpx-accent-fg, #1c7ed6);
  --gl-accent-soft: color-mix(in srgb, var(--gl-accent) 12%, transparent);
  --gl-hair: color-mix(in srgb, #212529 11%, transparent);
  --gl-well: color-mix(in srgb, #212529 6%, transparent);
  --gl-shade-a: color-mix(in srgb, #212529 5%, transparent);
  --gl-shade-b: color-mix(in srgb, #212529 10%, transparent);
  --gl-tile-radius: 18px;
  --gl-tile-shadow: 0 0 0 1px var(--gl-hair), 0 1px 2px var(--gl-shade-a),
    0 14px 32px -20px var(--gl-shade-b);
}
/* The page: plain white, one family, the text colour Paper's ink. */
html, body { background: var(--gl-paper); }
body {
  font-family: var(--dpx-font, 'Inter Variable', Inter, -apple-system, BlinkMacSystemFont,
    "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif);
  color: var(--gl-fg);
}
body h1, body h2, body h3, body h4, body h5, body h6 {
  font-family: var(--dpx-headings-font, inherit);
  color: var(--gl-fg); letter-spacing: -0.012em;
}
body h1.title { font-weight: 750; letter-spacing: -0.02em; }
body .subtitle, body .quarto-title-meta-heading { color: var(--gl-muted); }
body a { color: var(--gl-accent-fg); }
body :not(pre) > code { background: var(--gl-well); color: var(--gl-fg); border-radius: 6px; }
body pre, body div.sourceCode { background: var(--gl-well); border: 0; border-radius: 12px; }
body hr { border-color: var(--gl-hair); opacity: 1; }
body table:not(.dpx-plain) th {
  border-bottom: 1px solid var(--gl-hair); color: var(--gl-muted); font-weight: 600;
}
body table:not(.dpx-plain) td { border-bottom: 1px solid var(--gl-hair); }
body blockquote { border-inline-start: 3px solid var(--gl-hair); color: var(--gl-muted); }
/* Tabs and the results heading lead the page; they are not framed. */
.dpx-body[data-dpx-kind="tab"], .dpx-body[data-dpx-kind="results"] {
  border-inline-start: 0; padding-inline-start: 0; margin-inline-start: 0;
}
/* Sections on the canvas: paper groups with a soft accent edge. */
section[data-dpx-kind="section"] {
  border: 1px solid var(--gl-hair); border-radius: 24px;
  background: var(--gl-paper);
  box-shadow: 0 0 0 1px var(--gl-hair),
    inset 3px 0 0 color-mix(in srgb, var(--dpx-accent, #ced4da) 75%, transparent);
  padding: 14px 18px 12px 16px; margin: 20px 0;
}
section[data-dpx-kind="section"] > .dpx-body {
  border-inline-start: 0; padding-inline-start: 0; margin: 6px 0 0;
}
/* Tile frames: every computed result is a soft floating card, with the same
   16px inner edge the app's tiles keep. Card rows are a row of cards, not a
   card of cards; the text a cell prints is prose, not a tile. */
.cell-output-display:has(.js-plotly-plot, table, img, .dpx-tile, .dpx-unavailable):not(:has(.dpx-cards, .dpx-card)) {
  background: var(--gl-paper); border: 1px solid var(--gl-hair);
  border-radius: var(--gl-tile-radius); box-shadow: var(--gl-tile-shadow);
  padding: 14px 16px 12px; margin: 0 0 16px; overflow: hidden;
}
.dpx-tile-head { margin: 0 0 10px; min-height: 22px; }
.dpx-tile-title { font-size: 14px; font-weight: 650; line-height: 22px; color: var(--gl-fg); }
.dpx-tile-sub { font-size: 12px; line-height: 16px; color: var(--gl-faint); }
/* KPI cards: floating cards, a quiet label over a firm number. */
.dpx-card {
  background: var(--gl-paper) !important; border: 1px solid var(--gl-hair) !important;
  border-radius: var(--gl-tile-radius) !important; box-shadow: var(--gl-tile-shadow) !important;
  padding: 14px 16px !important;
}
.dpx-card-title {
  font-size: 12.5px !important; font-weight: 600 !important; letter-spacing: 0 !important;
  text-transform: none !important; opacity: .9;
}
.dpx-card-value {
  font-weight: 700 !important; letter-spacing: -0.03em; font-variant-numeric: tabular-nums;
  font-size: 30px !important; line-height: 1.05 !important; color: var(--gl-fg) !important;
}
.dpx-cards { gap: 12px !important; }
/* What could not be drawn reads as an empty tile, not as an error box. */
.dpx-unavailable { border: 0 !important; padding: 0 !important; color: var(--gl-muted) !important; }
.dpx-snapshot img { border: 0 !important; border-radius: 12px !important; }
/* The chrome around the report. */
nav[role="doc-toc"] > h2, #toc-title { color: var(--gl-faint); }
nav[role="doc-toc"] a { color: var(--gl-muted); }
nav[role="doc-toc"] a:hover { color: var(--gl-fg); }
nav[role="doc-toc"] a.active { color: var(--gl-accent-fg); border-inline-start-color: var(--gl-accent); }
#quarto-code-tools-source .btn, .code-tools-button {
  border: 1px solid var(--gl-hair); border-radius: 999px; color: var(--gl-fg);
  background: var(--gl-paper); font-weight: 600;
}
#quarto-code-tools-source .btn:hover, .code-tools-button:hover { background: var(--gl-well); }
.dpx-all { border-radius: 999px; border-color: var(--gl-hair); color: var(--gl-muted); opacity: 1; }
.dpx-all:hover { background: var(--gl-well); color: var(--gl-fg); }
.dpx-select { border-radius: 12px; border-color: transparent; background-color: var(--gl-well); }
.dpx-select:focus { border-color: var(--gl-accent); background-color: var(--gl-paper); }
.dpx-zoom { border-radius: 10px; border-color: var(--gl-hair); color: var(--gl-muted); }
.updatemenu-item-rect { rx: 12px; ry: 12px; stroke: var(--gl-hair); }
/* DataTables (itables): Paper's quiet wells and pills. */
.dataTables_wrapper, .dt-container { font-size: .8125rem; }
.dataTables_wrapper input, .dataTables_wrapper select, .dt-container input, .dt-container select {
  border: 1px solid transparent; border-radius: 12px; background: var(--gl-well);
  padding: .2em .6em;
}
.dt-paging .dt-paging-button.current, .dataTables_paginate .paginate_button.current {
  border-radius: 999px !important; border: 0 !important;
  background: var(--gl-accent-soft) !important; color: var(--gl-accent-fg) !important;
}
</style>"""


def _css_value(value: str) -> str:
    """A brand font stack as a CSS value: nothing that could close the rule."""
    return re.sub(r"[;{}<>]", "", value).strip()


def _resolve_accent_hex(color: str | None, fallback: str) -> str:
    """A Mantine palette name or a literal CSS colour, to a hex the export's
    static HTML can use directly. Mirrors the live chrome's own fallback:
    unset/unrecognised stays neutral rather than picking a colour on the
    author's behalf.
    """
    if not color:
        return fallback
    if _CSS_COLOR_RE.match(color):
        return color
    return _MANTINE_SHADE_6.get(color.split(".")[0].strip().lower(), fallback)


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
    dcs: list[DCPlan]
    stages: list[StagePlan]
    title: str
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
    # The PDF's colours: ``colour`` (tab colours on headings and in the
    # contents, tinted notes) or ``mono`` (print-friendly, the text colour).
    pdf_style: str = "colour"

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
    return "\n".join(f"# {line}" if line else "#" for line in _sentence(text).split("\n"))


def _fmt_value(value: Any) -> str:
    if isinstance(value, list):
        shown = ", ".join(str(v) for v in value[:6])
        if len(value) > 6:
            shown += f", … ({len(value)} values)"
        return shown
    return str(value)


class NotebookBuilder:
    def __init__(self, plan: ExportPlan) -> None:
        self.plan = plan
        self.names = NameAllocator()
        self.dc_by_id: dict[str, DCPlan] = {dc.dc_id: dc for dc in plan.dcs}
        self.df_names: dict[str, str] = {}
        self.final_names: dict[str, str] = {}
        for dc in plan.dcs:
            self.df_names[dc.dc_id] = self.names.claim("df", dc.tag, fallback="table")
            self.names.reserve(f"final_{self.df_names[dc.dc_id][3:]}")
            self.final_names[dc.dc_id] = f"final_{self.df_names[dc.dc_id][3:]}"
        self._entries: list[tuple[MarkdownUnit | ComponentEntry, str | None]] | None = None
        self.tab_anchors, self._anchor_by_tab_name = self._tab_anchors()
        self._section_anchor_seq: list[str] = []
        self._section_i = 0
        self.section_anchors = self._section_anchors()
        self._float_labels: set[str] = set()
        self._hero_cache: tuple[str, str, str | None] | None | bool = False

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
        for unit in ordered_units(self.plan.tabs):
            if isinstance(unit, MarkdownUnit):
                if unit.kind == "tab":
                    current_tab = unit.text
                out.append((unit, current_tab))
                continue
            highlight: dict[str, Any] | None = None
            if unit.meta.get("component_type") == "highlight":
                source = self._highlight_source(unit.meta)
                if source is not None:
                    highlight = unit.meta
                    unit = replace(source, section=unit.section, persistent=unit.persistent)
            meta = unit.meta
            verdict = classify(meta)
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
            out.append(
                (
                    ComponentEntry(unit=unit, verdict=verdict, name=name, highlight=highlight),
                    current_tab,
                )
            )
        self._entries = out
        return out

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
        cells.append(self._state_cell())
        cells.append(self._grouping_cell())
        cells.extend(self._data_cells())
        cells.extend(self._funnel_cells())
        cells.extend(self._group_cells())
        cells.extend(self._panel_cells())
        cells.extend(self._tile_cells())
        if self.plan.embed_runtime:
            cells.append(self._runtime_cell())
        methods_md = self._methods()[0]
        if methods_md:
            cells.append(md_cell(methods_md))
        return render_qmd(cells, front_matter=self.front_matter().to_yaml())

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

    def _heading_colors(self) -> dict[str, str]:
        """Each tab's and section's heading label, with its colour (as the HTML
        draws it): what the PDF colours its headings and contents by."""
        # The document's own parts wear the primary, as on the page.
        out: dict[str, str] = {k: self._accent() for k in ("filters", "results", "methods")}
        seq = iter(self._section_anchor_seq)
        for unit in ordered_units(self.plan.tabs):
            if not isinstance(unit, MarkdownUnit):
                continue
            if unit.kind == "tab":
                brand = self.plan.tab_brands.get(unit.dashboard_id or "") or self.plan.brand or {}
                accent = _resolve_accent_hex(unit.color, brand.get("primary") or "")
                anchor = self.tab_anchors.get(unit.dashboard_id or unit.text)
            else:
                accent = _resolve_accent_hex(unit.color, "")
                anchor = next(seq, None)
            if anchor and accent:
                out[anchor] = accent
        return out

    def _typst_preamble(self) -> str:
        plan = self.plan
        project = plan.project or {}
        exported = f"{plan.exported_at:%Y-%m-%d %H:%M} UTC"
        if plan.exported_by:
            exported += f" by {plan.exported_by}"
        if plan.instance:
            exported += f" from {plan.instance}"
        state = (
            "; ".join(f"{s.label}: {self._filter_value_text(s)}" for s in plan.stages)
            or "No filter active"
        )
        rows = [
            ("Exported", exported),
            ("Project", str(project.get("name") or "")),
            ("Exported state", state),
            ("Depictio", plan.depictio_version or ""),
            ("Live dashboard", self._dashboard_url() if plan.dashboard_public else ""),
        ]
        hero = self.hero
        return typst_preamble(
            title=plan.title,
            subtitle=plan.subtitle,
            primary=self._accent(),
            style=plan.pdf_style,
            dashboard_mark=plan.dashboard_logo,
            title_logo=hero[1] if hero else None,
            depictio_mark=plan.depictio_mark,
            provenance=rows,
            heading_colors=self._heading_colors(),
        )

    def _dashboard_url(self) -> str:
        return f"{self.plan.api_url.rstrip('/')}/dashboard/{self.plan.dashboard_id}"

    def _accent(self) -> str:
        return _resolve_accent_hex((self.plan.brand or {}).get("primary"), "#228be6")

    def _appbar(self) -> str:
        """The header bar: the dashboard's mark and "Powered by" Depictio.

        The name stays off the bar whenever the title block under it says it
        already (as text, or as the dashboard's logo): one place per name. No
        tab breadcrumb either: the first part's own heading follows."""
        plan = self.plan
        main = plan.tabs[0] if plan.tabs else {}
        accent = _resolve_accent_hex(str(main.get("icon_color") or "") or None, self._accent())
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
            exported_at=f"{plan.exported_at:%Y-%m-%d %H:%M UTC}",
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
        return QuartoFrontMatter(
            title=plan.title,
            subtitle=plan.subtitle or f"Exported from Depictio on {plan.exported_at:%Y-%m-%d}",
            author=plan.exported_by,
            date=plan.exported_at.strftime("%Y-%m-%d"),
            # The dashboard's own mark on the browser tab when it has one (the
            # nf-core apple), the app's otherwise.
            favicon_data_uri=plan.dashboard_logo or plan.favicon_data_uri,
            before_body=self._appbar(),
            after_body=self._footer(),
            pdf=self.plan.pdf,
            extra={"references": refs} if (refs := self._methods()[1]) else {},
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
            "from depictio.notebook import (\n"
            "    DepictioClient,\n"
            "    fill_text,\n"
            "    funnel_rest,\n"
            "    funnel_stage,\n"
            "    html_text,\n"
            "    init_tables,\n"
            "    show_table,\n"
            "    static_figures,\n"
            "    use_document_renderer,\n"
            "    use_theme,\n"
            ")\n"
            "from polars import col, lit\n"
            "\n"
            + _comment(
                "One copy of plotly.js for the whole document, and no MathJax request "
                "per figure. Executed as a notebook, every figure otherwise embeds its "
                "own ~5 MB copy of the library, which is what a self-contained HTML "
                "export is made of: 35 figures came to 170 MB, of which 2.5 MB was data"
            )
            # Assigned to a throwaway: the call returns a bool, and a bare
            # expression at the end of a cell is that cell's output — the report
            # would open on the word "True".
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
        # A page with no browser (the PDF): the card as a line of text.
        from IPython.display import Markdown

        return Markdown(f"**{title}** {text}")
    return HTML(
        f'<div class="dpx-card" style="display:inline-block;min-width:11rem;margin:0 0.5rem 0.5rem 0;'
        f'padding:0.85rem 1.1rem;border:1px solid #e3e3e8;border-radius:12px;'
        f'font-family:inherit;background:#fafafa">'
        f'<div class="dpx-card-title" style="font-size:0.78rem;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:0.02em;margin-bottom:0.3rem">{title}</div>'
        f'<div class="dpx-card-value" style="font-size:1.65rem;font-weight:650;color:#111827">{text}</div>'
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
        from IPython.display import Markdown

        def line(c):
            md = getattr(c, "_repr_markdown_", None)
            return md() if md else html_text(c._repr_html_() or "")

        return Markdown("\\n".join(f"- {line(c)}" for c in cards))
    n = len(cards)
    cols = n if n <= 4 else (4 if n % 4 == 0 else 3)
    items = "".join(c._repr_html_() for c in cards)
    return HTML(
        f'<div class="dpx-cards" style="display:grid;grid-template-columns:'
        f'repeat({cols},minmax(0,1fr));gap:0.75rem;margin:0 0 0.5rem">{items}</div>'
    )'''
        return Cell(body)

    def _header(self) -> str:
        # The instance's primary, as the one variable the chrome's brand-aware
        # rules read. A separate block rather than a placeholder inside
        # NOTEBOOK_CHROME: that constant is full of CSS and JS braces, and
        # nothing there is worth making it a format string over.
        accent = _resolve_accent_hex((self.plan.brand or {}).get("primary"), "#228be6")
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
                instance=self.plan.instance,
                api_url=self.plan.api_url,
                dashboard_id=self.plan.dashboard_id,
                stem=self.plan.stem,
                state_version=self.plan.state.version,
                warnings=self.plan.warnings,
                params_icon=self.plan.icons.get(PROVENANCE_ICON, ""),
                details_rows=self._export_details(),
                details_icon=self.plan.icons.get(EXPORT_DETAILS_ICON, ""),
                run_icon=self.plan.icons.get(RUN_ICON, ""),
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
            ("Exported", f"{plan.exported_at:%Y-%m-%d %H:%M UTC}"),
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
            accent = _resolve_accent_hex(stage.color, "#228be6")
            icon = self._icon_html(stage.icon, accent)
            value = self._filter_value_text(stage)
            rows.append(
                '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;min-width:0">'
                + (icon or "")
                + f'<span style="font-size:0.8rem;font-weight:500">{_esc(stage.label)}</span>'
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
            labels.append(f"{position}. {name} = {short}" if short else f"{position}. {name}")

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
            + f"\n_palette = {pprint.pformat(list(_FUNNEL_PALETTE), width=88)}"
            + """
fig_funnel = go.Figure(
    go.Funnel(
        name=_series[0][0],
        orientation="h",
        y=_stages,
        x=_series[0][1],
        textinfo="value+percent initial",
        textposition="inside",
        hovertemplate="%{y}<br>%{x} rows<extra>%{fullData.name}</extra>",
        marker={"color": _palette[0]},
        connector={"line": {"color": "rgba(0,0,0,0.08)", "width": 1}},
    )
)
# One collection at a time: the tables span three orders of magnitude, and on
# one shared axis the small ones collapse into slivers with no room for their
# numbers. The dropdown is Plotly's own, so it works in the exported HTML with
# nothing to run — the report's own script replaces it with an HTML select,
# which Plotly cannot place here: a menu takes paper coordinates, and this
# figure's left third is the gutter its stage labels need. It swaps the one
# trace's data rather than toggling the visibility of seven, because a funnel
# with hidden traces drops its stage labels off the axis entirely.
fig_funnel.update_layout(
    updatemenus=[
        {
            "name": "Data collection",
            "buttons": [
                {
                    "label": _name,
                    "method": "restyle",
                    "args": [
                        {
                            "x": [_rows],
                            "name": [_name],
                            "marker.color": [_palette[_i % len(_palette)]],
                        }
                    ],
                }
                for _i, (_name, _rows) in enumerate(_series)
            ],
            "direction": "down",
            "showactive": True,
            "x": 0,
            "xanchor": "left",
            "y": 1.18,
            "yanchor": "top",
            # The app's `Select`: white on a gray-4 border, gray-7 text, the
            # system stack at Mantine's `sm`.
            "bgcolor": "#ffffff",
            "bordercolor": "#ced4da",
            "borderwidth": 1,
            "pad": {"l": 10, "r": 10, "t": 7, "b": 7},
            "font": {
                "family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                "size": 13,
                "color": "#495057",
            },
        }
    ],
    template="plotly_white",
    showlegend=False,
    # No room reserved above for the menu: Plotly grows the top margin itself
    # while it is showing, and gives it back once the select has taken over.
    margin={"l": 260, "r": 24, "t": 28, "b": 24},
    yaxis={"autorange": "reversed"},
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font={"color": "#495057"},
    height=max(290, 130 + len(_stages) * 46),
)
fig_funnel"""
        )
        return Cell(body)

    def _funnel_cells(self) -> list[Cell]:
        cells: list[Cell] = []
        stages = self.plan.stages
        accent = _resolve_accent_hex((self.plan.brand or {}).get("primary"), "#228be6")

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
        )

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
        cells: list[Cell] = [md_cell(self._results_header_html())]
        self._section_i = 0
        pending: list[ComponentEntry] = []
        tab_doc: dict[str, Any] = self.plan.tabs[0] if self.plan.tabs else {}

        def flush() -> None:
            # The run of tiles between two headings, laid out row by row as
            # the dashboard's grid draws them.
            for row in self._grid_rows(pending, grid_columns(tab_doc) or 12):
                cells.extend(self._row_cells(row, grid_columns(tab_doc) or 12))
            pending.clear()

        tabs_seen = 0
        for entry, _tab in self.entries():
            if isinstance(entry, MarkdownUnit):
                flush()
                # The first tab opens unfolded, every other one folded: the
                # report opens on its overview, not on every plot at once.
                if entry.kind == "tab":
                    tabs_seen += 1
                    tab_doc = next(
                        (
                            t
                            for t in self.plan.tabs
                            if str(t.get("dashboard_id") or "") == (entry.dashboard_id or "")
                        ),
                        tab_doc,
                    )
                cells.append(
                    md_cell(
                        self._markdown_unit_html(
                            entry, folded=entry.kind == "tab" and tabs_seen > 1, tab=tab_doc
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
        return cells

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
        the dashboard draws as a strip.
        """
        rows: list[list[ComponentEntry]] = []
        for entry in entries:
            lay = self._layout_of(entry)
            y, w = lay.get("y"), lay.get("w")
            last = rows[-1] if rows else None
            if last:
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
            return self._entry_cells(row[0])
        out = [md_cell(grid_open([int(self._layout_of(e).get("w") or 1) for e in row]))]
        for entry in row:
            out.append(md_cell(cell_open()))
            out.extend(self._entry_cells(entry))
            out.append(md_cell(DIV_CLOSE))
        out.append(md_cell(DIV_CLOSE))
        return out

    def _card_row_cells(self, row: list[ComponentEntry]) -> list[Cell]:
        """A strip of cards: one row cell, one note for their descriptions."""
        out: list[Cell] = []
        if self.plan.embed_runtime:
            out.append(md_cell(tile_open([self._tile_ref(e) for e in row])))
        render_names = []
        for e in row:
            cell, render_name = self._tile_cell(e, show=False)
            out.append(cell)
            render_names.append(render_name)
        out.append(self._row_cell(render_names))
        if self.plan.embed_runtime:
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
        dc = self.dc_by_id.get(str(meta.get("dc_id") or ""))
        tag = dc.tag if dc else str(meta.get("data_collection_tag") or "")
        if not tag:
            return ""
        bits = [f"Data: {_esc(tag)}"]
        if dc is not None:
            rows = dc.initial_rows
            for stage in self.plan.stages:
                got = stage.rows_by_dc.get(dc.dc_id)
                if got is not None:
                    rows = got
            if rows is not None:
                bits.append(f"{rows:,} rows")
            if dc.version is not None:
                bits.append(f"commit v{dc.version}")
        bits.append(f"as of {self.plan.exported_at:%Y-%m-%d}")
        return f'<span class="dpx-asof">{" · ".join(bits)}</span>'

    def _entry_cells(self, entry: ComponentEntry) -> list[Cell]:
        """One tile: its highlight line, the tile (numbered when it is a figure
        or a table, with its caption), then its "About this component"."""
        out: list[Cell] = []
        meta = entry.unit.meta
        ctype = str(meta.get("component_type") or "")
        if entry.highlight is not None:
            out.append(self._highlight_note(entry))
        tile: Cell | list[Cell] = self._tile_cell(entry)  # type: ignore[assignment]
        assert isinstance(tile, Cell)
        if self.plan.embed_runtime and self._mountable(entry):
            # The runtime's placeholder; the cell's own output inside it is
            # the fallback. The caption and the note stay the document's.
            tile = [md_cell(tile_open([self._tile_ref(entry)])), tile, md_cell(tile_close())]
        tiles = tile if isinstance(tile, list) else [tile]
        if ctype == "text":
            surface = str(meta.get("surface") or "")
            if surface == "card":
                accent = _resolve_accent_hex(str(meta.get("accent") or "") or None, "")
                out.append(md_cell(cell_open("dpx-surface-card", accent or None)))
                out.extend(tiles)
                out.append(md_cell(DIV_CLOSE))
            else:
                out.extend(tiles)
            return out
        label = self._float_label(entry)
        if label is None:
            out.extend(tiles)
        else:
            title = str(
                meta.get("title") or meta.get("selected_plot") or meta.get("selected_module") or ""
            ).strip()
            caption_bits = []
            if title:
                caption_bits.append(f"**{_esc(title)}**.")
            if entry.highlight is None and str(meta.get("caption") or "").strip():
                caption_bits.append(self._rewrite_links(str(meta["caption"]).strip()))
            badge = self._data_badge(meta)
            if badge:
                caption_bits.append(badge)
            caption = " ".join(caption_bits) or _esc(ctype)
            out.append(md_cell(f"::: {{#{label}}}"))
            out.extend(tiles)
            out.append(md_cell(f"{caption}\n\n:::"))
        about = about_callout(
            str(meta.get("description") or ""),
            name=str(meta.get("title") or ""),
            rewrite=self._rewrite_links,
        )
        if about:
            out.append(md_cell(about))
        return out

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
    ) -> str:
        """One heading line: a real ATX heading, decorated inline.

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
        title = (
            f'<span class="dpx-hc" style="--dpx-hc:{accent}">{_esc(text)}</span>'
            if accent
            else _esc(text)
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
        self, unit: MarkdownUnit, *, folded: bool = False, tab: dict[str, Any] | None = None
    ) -> str:
        if unit.kind == "section":
            return self._section_header_html(unit, tab=tab)
        return self._tab_header_html(unit, folded=folded)

    def _results_header_html(self) -> str:
        """The one heading every tab hangs off: the dashboard itself."""
        accent = _resolve_accent_hex((self.plan.brand or {}).get("primary"), "")
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
            color = _resolve_accent_hex(
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
        accent = _resolve_accent_hex(unit.color, "")
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
            parts.append("<br>".join(lines) if len(lines) > 1 else lines[0])
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

    def _tab_header_html(self, unit: MarkdownUnit, *, folded: bool = False) -> str:
        # Each tab of a multi-tab family is its own dashboard_id with its own
        # possible brand_theme override — the live sidebar shows a different
        # icon/colour per tab, so the export's per-tab part gets its own
        # resolved identity too, not just the document's.
        brand = self.plan.tab_brands.get(unit.dashboard_id or "") if unit.dashboard_id else None
        fallback = (brand or self.plan.brand or {}).get("primary") or ""
        accent = _resolve_accent_hex(unit.color, fallback)
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
            return md_cell(f"> **{title}** is not in this notebook: {entry.verdict.reason}.")
        if entry.verdict.status == "api":
            cell = self._api_cell(entry, title, show=show)
            return cell if show else (cell, entry.name or self.names.claim("viz", title))
        dc = self.dc_by_id[str(meta.get("dc_id") or "")]
        final = self.final_names[dc.dc_id]
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
                f"show_table({name})",
            ]
            return Cell("\n".join(body))
        if ctype == "figure":
            return self._figure_cell(meta, name, source, prelude, title)
        return md_cell(f"> **{title}** ({ctype}) has no code path yet.")

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
        caption = self._rewrite_tab_links(str((entry.highlight or {}).get("caption") or "").strip())
        line = f"*From the {where} tab.*"
        return md_cell(line + (f" {caption}" if caption else ""))

    def _highlight_cell(self, meta: dict[str, Any], title: str) -> Cell:
        source = str(meta.get("source_component") or "a figure")
        tab = str(meta.get("source_tab") or "").strip()
        where = f"the **{_esc(tab)}** tab" if tab else "another tab"
        line = f"> **{_esc(title)}** shows *{_esc(source)}* from {where}, drawn in that tab's part."
        caption = self._rewrite_tab_links(str(meta.get("caption") or "").strip())
        return md_cell(line + (f"\n>\n> {caption}" if caption else ""))

    def _text_cell(
        self, meta: dict[str, Any], section: str | None = None, *, tab_id: str = ""
    ) -> Cell:
        title = str(meta.get("title") or "").strip()
        body = str(meta.get("body") or "").strip()
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
        lines += [
            f"def _make_{name}(df, depictio_group_kwargs=depictio_group_kwargs, "
            "depictio_group_by=depictio_group_by):",
            *code_lines,
            "    return fig",
            "",
            call,
            name,
        ]
        return Cell("\n".join(lines))


def generate_qmd(plan: ExportPlan) -> str:
    return NotebookBuilder(plan).build()
