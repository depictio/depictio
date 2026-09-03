"""From an :class:`ExportPlan` to a marimo notebook.

The endpoint gathers everything that needs Mongo, Delta or link resolution
into an ``ExportPlan``; this module only turns the plan into cells, so it
runs in tests with no infrastructure. The same pass that names cells also
produces the preflight the export modal shows.
"""

from __future__ import annotations

import pprint
import re
from dataclasses import dataclass, field
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

from .aggregations import agg_expr_source
from .cells import Cell, md_cell, render_notebook
from .classify import Classification, classify
from .names import NameAllocator, slug
from .predicates import PredicateSource, emit_filter_expr, emit_predicate
from .provenance import EXPORT_DETAILS_ICON, PROVENANCE_ICON, header_markdown
from .reading_order import ComponentUnit, MarkdownUnit, ordered_units

DEFAULT_MARIMO_VERSION = "0.24.0"

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
  // <section>, so there the body is simply the rest of that wrapper; Jupyter
  // and marimo lay cells out flat, so there we walk forward to the next
  // heading of the same or higher rank.
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
  function fold(h, body) {
    h.classList.add('dpx-h');
    var chev = document.createElement('span');
    chev.className = 'dpx-chev';
    chev.textContent = '▾';
    h.insertBefore(chev, h.firstChild);
    h.addEventListener('click', function (ev) {
      if (ev.target.closest('a')) return;
      body.style.display = h.classList.toggle('dpx-folded') ? 'none' : '';
    });
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
      if (accent) body.style.setProperty('--dpx-accent', accent);
      nodes[0].parentNode.insertBefore(body, nodes[0]);
      for (var j = 0; j < nodes.length; j++) body.appendChild(nodes[j]);
      fold(h, body);
      pairs.push([h, body]);
    }
    for (var k = 0; k < pairs.length; k++) absorb(pairs[k][0], pairs[k][1]);
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
  var OUTPUT = '.cell-output-display, .jp-OutputArea-output, .marimo-output';
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
  function setAll(folded) {
    for (var i = 0; i < pairs.length; i++) {
      pairs[i][0].classList.toggle('dpx-folded', folded);
      pairs[i][1].style.display = folded ? 'none' : '';
    }
    // A figure unfolded back into view was never measured while hidden.
    if (!folded) { controls(); refit(); }
  }
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
    var head = toc.querySelector('h2'), list = toc.querySelector(':scope > ul');
    if (!head || !list || head.hasAttribute('data-dpx-toc')) return;
    head.setAttribute('data-dpx-toc', '1');
    var top = document.createElement('span');
    top.className = 'dpx-chev';
    top.textContent = '\\u25BE';
    head.insertBefore(top, head.firstChild);
    head.classList.add('dpx-h');
    head.addEventListener('click', function () {
      list.style.display = head.classList.toggle('dpx-folded') ? 'none' : '';
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhance);
  } else {
    enhance();
  }
  // marimo mounts cells after this one runs, and Quarto's own scripts can move
  // content around after load; re-running is cheap and skips what it has done.
  window.addEventListener('load', enhance);
  setTimeout(enhance, 500);
  setTimeout(enhance, 2500);
})();
</script>"""


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
    marimo_version: str = DEFAULT_MARIMO_VERSION
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
            meta = unit.meta
            verdict = classify(meta)
            dc_id = str(meta.get("dc_id") or "")
            if verdict.status == "code" and meta.get("component_type") != "text":
                if dc_id not in self.dc_by_id:
                    verdict = Classification(
                        "api",
                        "its data collection has no Delta table in this export "
                        "(e.g. a MultiQC report); re-rendered through the Depictio API",
                        kind=verdict.kind,
                    )
            name = self._name_for(meta, verdict)
            out.append((ComponentEntry(unit=unit, verdict=verdict, name=name), current_tab))
        self._entries = out
        return out

    def _name_for(self, meta: dict[str, Any], verdict: Classification) -> str | None:
        ctype = str(meta.get("component_type") or "")
        hint = meta.get("title") or meta.get("column_name") or meta.get("index")
        if verdict.status == "omitted" or ctype == "text":
            return None
        if verdict.status == "api":
            return self.names.claim("viz", hint)
        prefix = {"figure": "fig", "card": "card", "table": "table"}.get(ctype, "tile")
        return self.names.claim(prefix, hint)

    # -------------------------------------------------------------- preflight
    def preflight(
        self, *, ipynb_available: bool, render_available: bool = False
    ) -> NotebookPreflight:
        components: list[NotebookPreflightComponent] = []
        counts = {"code": 0, "api": 0, "omitted": 0}
        for entry, tab in self.entries():
            if isinstance(entry, MarkdownUnit):
                continue
            meta = entry.unit.meta
            counts[entry.verdict.status] = counts.get(entry.verdict.status, 0) + 1
            components.append(
                NotebookPreflightComponent(
                    index=str(meta.get("index") or ""),
                    title=meta.get("title"),
                    component_type=str(meta.get("component_type") or ""),
                    kind=entry.verdict.kind,
                    status=entry.verdict.status,  # type: ignore[arg-type]
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
            ipynb_available=ipynb_available,
            render_available=render_available,
            counts={**counts, "stages": len(self.plan.stages), "dcs": len(self.plan.dcs)},
        )

    # ------------------------------------------------------------------ build
    def build(self) -> str:
        cells: list[Cell] = []
        cells.append(self._imports_cell())
        cells.append(self._connection_cell())
        cells.append(self._metric_card_cell())
        cells.append(md_cell(self._header()))
        cells.append(self._state_cell())
        cells.extend(self._data_cells())
        cells.extend(self._funnel_cells())
        cells.extend(self._group_cells())
        cells.extend(self._panel_cells())
        cells.extend(self._tile_cells())
        cells.append(
            md_cell(
                "---\n\n*Generated by Depictio's notebook export. The dashboard's theme and "
                "brand colours are not reproduced; every number is.*"
            )
        )
        return render_notebook(cells, generated_with=self.plan.marimo_version)

    def _imports_cell(self) -> Cell:
        return Cell(
            "import datetime\n"
            "\n"
            "import marimo as mo\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import plotly.express as px\n"
            "import plotly.graph_objects as go\n"
            "import polars as pl\n"
            "from depictio.notebook import DepictioClient, use_document_renderer\n"
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
            + "\n_ = use_document_renderer()"
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
        # tile. mo.Html carries both marimo's own display protocol and
        # _repr_html_, so this renders the same in marimo, Jupyter and
        # Quarto without needing marimo's runtime at read time. No leading
        # underscore: that would make marimo treat it as cell-local (like
        # `_scoped` below), invisible to every other cell that calls it.
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
    return mo.Html(
        f'<div style="display:inline-block;min-width:11rem;margin:0 0.5rem 0.5rem 0;'
        f'padding:0.85rem 1.1rem;border:1px solid #e3e3e8;border-radius:12px;'
        f'font-family:inherit;background:#fafafa">'
        f'<div style="font-size:0.78rem;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:0.02em;margin-bottom:0.3rem">{title}</div>'
        f'<div style="font-size:1.65rem;font-weight:650;color:#111827">{text}</div>'
        f'</div>'
    )


def card_row(cards):
    """Several cards on one row, as an even CSS grid.

    The column count is fixed by how many cards there are rather than left to
    `auto-fit`, which fits as many as the page happens to be wide enough for
    and strands the remainder: three cards share one line, four fall into a
    2x2 block instead of 3+1, and anything larger runs three to a line.
    `_repr_html_()` is the standard rich-display hook (mo.Html and Depictio's
    own components both implement it): calling it directly gets the actual
    card look, the same HTML each object would show if displayed bare —
    `.html` on a Depictio component is a different thing, an embeddable tile.
    """
    n = len(cards)
    cols = n if n <= 3 else (2 if n == 4 else 3)
    items = "".join(c._repr_html_() for c in cards)
    return mo.Html(
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
        return (
            f"<style>:root {{ --dpx-primary: {accent}; }}</style>\n"
            + NOTEBOOK_CHROME
            + "\n\n"
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
                brand=self.plan.brand,
                params_icon=self.plan.icons.get(PROVENANCE_ICON, ""),
                details_rows=self._export_details(),
                details_icon=self.plan.icons.get(EXPORT_DETAILS_ICON, ""),
            )
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
        return [
            ("Server", server),
            ("Project", "\n".join(x for x in (project.get("name"), project.get("_id")) if x)),
            ("Dashboard", dashboard),
            ("Data collections", collections),
            ("Analysis state", state),
            ("Notebook", f"marimo {plan.marimo_version}"),
            ("Exported", f"{plan.exported_at:%Y-%m-%d %H:%M UTC}"),
        ]

    def _state_cell(self) -> Cell:
        state = self.plan.state.model_dump(mode="json", exclude_none=True)
        literal = pprint.pformat(state, width=88, sort_dicts=False)
        return Cell(
            _comment(
                "The analysis state as exported: filters, funnel order, groups. Components "
                "rendered by Depictio below re-use it; edit it to change what they show"
            )
            + f"\ndepictio_state = {literal}"
        )

    def _data_cells(self) -> list[Cell]:
        cells = []
        for dc in self.plan.dcs:
            shape = ""
            if dc.initial_rows is not None:
                shape = f": {dc.initial_rows:,} rows"
                if dc.n_cols is not None:
                    shape += f", {dc.n_cols} columns"
                shape += " at export time"
            cells.append(
                Cell(
                    _comment(f'Data collection "{dc.tag}"{shape}')
                    + f"\n{self.df_names[dc.dc_id]} = client.data({dc.dc_id!r})"
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

        series: list[tuple[str, list[int | None]]] = []
        for dc in self.plan.dcs:
            if dc.initial_rows is None:
                continue
            series.append(
                (dc.tag, [dc.initial_rows, *(s.rows_by_dc.get(dc.dc_id) for s in stages)])
            )

        body = (
            _comment(
                "Depictio's filter funnel: rows left after each stage, per data collection. "
                "Reorder `_stages`/`_series` together to see the intermediate counts move"
            )
            + f"\n_stages = {pprint.pformat(labels, width=88)}"
            + f"\n_series = {pprint.pformat(series, width=88)}"
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

        def part(title: str, icon: str, level: int, kind: str) -> str:
            return self._heading(
                level=level,
                text=title,
                accent=accent,
                icon=self._icon_html(icon, accent),
                kind=kind,
            )

        if not stages:
            cells.append(
                md_cell(
                    part("Filters", FILTERS_ICON, RESULTS_LEVEL, "filters")
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
                    part("Filters", FILTERS_ICON, RESULTS_LEVEL, "filters")
                    + "\n\n*Each stage applies one filter on top of the previous one, in the "
                    "order the funnel view showed. Reordering stages changes the intermediate "
                    "counts, never the final one.*"
                )
            )
            cells.append(
                md_cell(
                    part("Active filters", SUMMARY_ICON, TAB_LEVEL, "section")
                    + "\n\n"
                    + self._filters_summary_html(stages)
                )
            )
            cells.append(
                md_cell(
                    part("Funnel", FUNNEL_ICON, TAB_LEVEL, "section")
                    + "\n\nRows left after each stage, and what share of the unfiltered "
                    "table that is. Pick the data collection from the dropdown."
                )
            )
            cells.append(self._funnel_figure_cell(stages))
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
            for dc in self.plan.dcs:
                name = self._stage_name(k, dc.dc_id)
                self.names.reserve(name)
                entries = stage.per_dc.get(dc.dc_id) or []
                applied = False
                lines.append(f"{name} = {prev[dc.dc_id]}")
                for entry in entries:
                    src = self._entry_source(dc, entry)
                    if src is None:
                        column = entry.get("column_name")
                        lines.append(
                            f"# '{column}' is not a column of {dc.tag}: the server skips this "
                            "filter here, and so does the notebook"
                        )
                        continue
                    if entry.get("link"):
                        lines.append(
                            f"# values resolved at export time through the cross-collection "
                            f"link {entry.get('index')!r}"
                        )
                    lines.extend(src.as_lines(name))
                    applied = True
                    fexpr = entry.get("filter_expr")
                    if fexpr:
                        lines.append(f"{name} = {name}.filter({emit_filter_expr(str(fexpr))})")
                if not applied and not entries:
                    lines[-1] += f"  # this filter does not touch {dc.tag}"
                prev[dc.dc_id] = name
            cells.append(Cell("\n".join(lines)))
        final_lines = [_comment("Every tile below reads this frame: the last funnel stage")]
        for dc in self.plan.dcs:
            final_lines.append(f"{self.final_names[dc.dc_id]} = {prev[dc.dc_id]}")
        cells.append(Cell("\n".join(final_lines)))
        return cells

    def _entry_source(self, dc: DCPlan, entry: dict[str, Any]) -> PredicateSource | None:
        column = str(entry.get("column_name") or "")
        itype = entry.get("interactive_component_type")
        if dc.columns is not None and column not in dc.columns and itype != "__link_no_match__":
            return None
        return emit_predicate(itype, column, entry.get("value"), dc.dtype(column))

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
        row: list[ComponentEntry] = []

        def flush_row() -> None:
            # A run of 0 or 1 buffered cards needs no row cell: 1 renders
            # exactly as it always has, folded or not.
            if not row:
                return
            if len(row) == 1:
                cells.append(self._tile_cell(row[0]))
            else:
                render_names = []
                for e in row:
                    cell, render_name = self._tile_cell(e, show=False)
                    cells.append(cell)
                    render_names.append(render_name)
                cells.append(self._row_cell(render_names))
            row.clear()

        for entry, _tab in self.entries():
            if isinstance(entry, MarkdownUnit):
                flush_row()
                cells.append(md_cell(self._markdown_unit_html(entry)))
                continue
            # Only cards fold into a row — a dashboard's card strip is what
            # "several tiles on one line" means; figures/tables/text stay
            # full-width, same as the dashboard draws them.
            meta = entry.unit.meta
            if (
                str(meta.get("component_type") or "") == "card"
                and entry.verdict.status != "omitted"
            ):
                row.append(entry)
                continue
            flush_row()
            cells.append(self._tile_cell(entry))
        flush_row()
        return cells

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

    def _heading(self, *, level: int, text: str, accent: str, icon: str, kind: str) -> str:
        """One heading line: a real ATX heading, decorated inline.

        The `#`s have to stay: the table of contents, the anchor links and (in
        Quarto) the section wrappers the fold script reads are all built from
        them, and a block-level `<div>` in front would take the line out of
        markdown parsing entirely. So the icon, the colour and the marker the
        script keys on all ride *inside* the line as inline HTML.
        """
        mark = f'<span data-dpx-accent="{accent}" data-dpx-kind="{kind}">{icon}</span>'
        title = f'<span style="color:{accent}">{_esc(text)}</span>' if accent else _esc(text)
        return f"{'#' * max(1, min(6, level))} {mark}{title}"

    def _markdown_unit_html(self, unit: MarkdownUnit) -> str:
        if unit.kind == "section":
            return self._section_header_html(unit)
        return self._tab_header_html(unit)

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

    def _section_header_html(self, unit: MarkdownUnit) -> str:
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
            )
        ]
        if unit.description:
            parts.append(f"*{_esc(unit.description)}*")
        return "\n\n".join(parts)

    def _tab_header_html(self, unit: MarkdownUnit) -> str:
        # Each tab of a multi-tab family is its own dashboard_id with its own
        # possible brand_theme override — the live sidebar shows a different
        # icon/colour per tab, so the export's per-tab part gets its own
        # resolved identity too, not just the document's.
        brand = self.plan.tab_brands.get(unit.dashboard_id or "") if unit.dashboard_id else None
        fallback = (brand or self.plan.brand or {}).get("primary") or ""
        accent = _resolve_accent_hex(unit.color, fallback)
        parts = [
            self._heading(
                level=TAB_LEVEL,
                text=unit.text,
                accent=accent,
                icon=self._icon_html(unit.icon, accent),
                kind="tab",
            )
        ]
        if unit.description:
            parts.append(f"*{_esc(unit.description)}*")
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
        # card_row() reads `.text` (an mo.Html from metric_card) or `.html`
        # (a DepictioComponent) off each element, so it lays them out without
        # needing to know what kind of card each one is.
        items = ", ".join(render_names)
        return Cell(f"card_row([{items}])")

    def _tile_cell(self, entry: ComponentEntry, *, show: bool = True) -> Cell | tuple[Cell, str]:
        meta = entry.unit.meta
        ctype = str(meta.get("component_type") or "")
        title = str(meta.get("title") or meta.get("index") or ctype)
        if ctype == "text":
            return self._text_cell(meta, entry.unit.section)
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
                _comment(f'Table "{title}": the first {page} filtered rows'),
                *prelude,
                f"{name} = {source}{select}.head({page})",
                name,
            ]
            return Cell("\n".join(body))
        if ctype == "figure":
            return self._figure_cell(meta, name, source, prelude, title)
        return md_cell(f"> **{title}** ({ctype}) has no code path yet.")

    def _text_cell(self, meta: dict[str, Any], section: str | None = None) -> Cell:
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
        if title:
            parts.append(f"{'#' * level} {title}")
        if body:
            parts.append(body)
        return md_cell("\n\n".join(parts) or "*(empty text tile)*")

    def _api_cell(self, entry: ComponentEntry, title: str, *, show: bool = True) -> Cell:
        meta = entry.unit.meta
        tab_id = str(entry.unit.tab.get("dashboard_id") or self.plan.dashboard_id)
        kind = entry.verdict.kind or str(meta.get("component_type") or "component")
        name = entry.name or self.names.claim("viz", title)
        head = _comment(
            f'"{title}" ({kind}) is rendered by Depictio with the state above: '
            f"{entry.verdict.reason}. `.figure` is the Plotly figure, `.data` the data, "
            "`.html` the interactive tile"
        )
        body = (
            head + f"\n{name} = client.component({tab_id!r}, {str(meta.get('index'))!r}, "
            "state=depictio_state)"
        )
        # `show=False` is a card folded into a row: the assignment above still
        # defines `name` (marimo's return tuple comes from AST-scanned
        # assignments, not from what a cell displays), it just isn't shown as
        # this cell's own output — the row cell after it displays all of them
        # together via card_row().
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
        code = str(meta.get("code_content") or "").rstrip()
        code_lines = ["    " + line if line.strip() else "" for line in code.split("\n")]
        body = [
            _comment(f'Figure "{title}", code mode: the author\'s code, verbatim'),
            *prelude,
            f"def _make_{name}(df):",
            *code_lines,
            "    return fig",
            "",
            f"{name} = _make_{name}({source})",
            name,
        ]
        return Cell("\n".join(body))


def generate_marimo(plan: ExportPlan) -> str:
    return NotebookBuilder(plan).build()
