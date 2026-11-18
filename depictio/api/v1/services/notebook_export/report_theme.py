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
_SHARED_RULES = """
// Depictio report chrome: the brand's SCSS rules layer (Quarto `brand`,
// `defaults.bootstrap.rules`). Compiled once per colour scheme.
html { scroll-padding-top: 72px; }
body { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
// The header bar stays on screen, slimmer once the page scrolls, over a
// frosted copy of the page colour.
body .dpx-appbar {
  position: sticky; top: 0; z-index: 1030;
  background: rgba($body-bg, 0.86);
  -webkit-backdrop-filter: saturate(1.4) blur(10px); backdrop-filter: saturate(1.4) blur(10px);
  transition: box-shadow .2s ease;
}
body .dpx-appbar.dpx-scrolled { box-shadow: 0 1px 0 var(--gl-hair), 0 8px 20px -16px var(--gl-shade-b); }
body .dpx-appbar .dpx-appbar-inner { transition: min-height .2s ease, padding .2s ease; }
body .dpx-appbar.dpx-scrolled .dpx-appbar-inner { min-height: 44px; padding-top: 6px; padding-bottom: 6px; }
// Type: Paper's scale, one step quieter than the Mantine defaults the
// notebook chrome sets for every renderer. The document's parts (Filters,
// Results, Methods), a dashboard tab, a section: three clear levels.
body section[data-dpx-kind] > h2 {
  font-size: 1.5rem; line-height: 1.3; letter-spacing: -0.015em;
  padding-bottom: .55rem; margin-top: 2.25rem; border-bottom: 1px solid var(--gl-hair);
}
body section[data-dpx-kind="tab"] > h3 { font-size: 1.3rem; line-height: 1.35; letter-spacing: -0.012em; margin-top: 1.75rem; }
body section[data-dpx-kind="section"] > h4 { font-size: 1.0625rem; line-height: 1.45; letter-spacing: -0.006em; }
body .quarto-title-block .subtitle { font-size: 1.125rem; font-weight: 400; line-height: 1.5; color: var(--gl-muted); }
// The header's record: a quiet two-column list, not a data table.
body .dpx-provenance table { font-size: .875rem; margin: .25rem 0 1rem; }
body .dpx-provenance table td { padding: .4rem .75rem .4rem 0; border-bottom: 1px solid var(--gl-hair); }
body .dpx-provenance table tr:last-child td { border-bottom: 0; }
body .dpx-provenance table td:first-child { width: 9.5rem; white-space: nowrap; color: var(--gl-muted); }
body .dpx-provenance table td:first-child strong { font-weight: 600; }
// Callouts: Paper's rounded note, a hairline frame and a thin accent edge.
.callout:not(.dpx-about) {
  border-radius: $border-radius-sm; border: 1px solid var(--gl-hair);
  box-shadow: 0 1px 2px var(--gl-shade-a);
}
.callout:not(.dpx-about) .callout-header { border-top-left-radius: $border-radius-sm; border-top-right-radius: $border-radius-sm; }
// Figure captions: quiet, close to their figure.
.quarto-float-caption, figcaption { line-height: 1.45; margin-top: .5rem; }
// Links: the brand's ink, underlined only on hover in the chrome around the text.
#TOC a, .dpx-footer a, .dpx-provenance a { text-decoration: none; }
#TOC a:hover, .dpx-footer a:hover, .dpx-provenance a:hover { text-decoration: underline; }
"""


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
.dpx-icon-btn, .dpx-scheme-toggle, .dpx-toc-toggle {{
  display: inline-flex; align-items: center; justify-content: center; flex: none;
  padding: 0; margin: 0; border: 1px solid transparent; background: transparent; cursor: pointer;
  color: var(--gl-muted, #868e96); line-height: 1;
  transition: color .12s ease, background-color .12s ease, border-color .12s ease;
}}
.dpx-scheme-toggle {{ width: 34px; height: 34px; border-radius: 10px; border-color: var(--gl-hair, #dee2e6); }}
.dpx-scheme-toggle svg {{ width: 18px; height: 18px; }}
.dpx-icon-btn:hover, .dpx-scheme-toggle:hover, .dpx-toc-toggle:hover {{
  color: var(--gl-fg, #212529); background: var(--gl-well, #f1f3f5);
}}
.dpx-icon-btn:focus-visible, .dpx-scheme-toggle:focus-visible, .dpx-toc-toggle:focus-visible,
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
  .dpx-scheme-toggle, .dpx-info, .dpx-pop, .dpx-toc-toggle {{ display: none !important; }}
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
/* The contents' own control: collapse the list to its title, and back. Wide
   screens only: under 992px Quarto lays the contents out its own way. */
#TOC > #toc-title {{ display: flex; align-items: center; gap: 6px; }}
.dpx-toc-toggle {{ margin-inline-start: auto; width: 26px; height: 26px; border-radius: 8px; }}
.dpx-toc-toggle svg {{ width: 16px; height: 16px; transition: transform .15s ease; }}
#TOC.dpx-toc-collapsed .dpx-toc-toggle svg {{ transform: rotate(180deg); }}
@media (min-width: 992px) {{
  #TOC.dpx-toc-collapsed > ul {{ display: none; }}
  #TOC.dpx-toc-collapsed > #toc-title {{ cursor: pointer; }}
}}
@media (max-width: 991.98px) {{ .dpx-toc-toggle {{ display: none; }} }}
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
/* The title block's subtitle under the dashboard's name. */
.quarto-title-block .subtitle {{ margin-top: .25rem; }}
</style>"""


# The behaviours, after the body (Quarto's own scripts have run). Idempotent:
# a pass is repeated as the page finishes loading and whenever the combined
# file's host adds its own controls (``dpx:tile-actions``).
CHROME_JS = r"""<script>
(function () {
  'use strict';
  var INFO_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 9h2V7h-2m1 13c-4.41 0-8-3.59-8-8s3.59-8 8-8s8 3.59 8 8s-3.59 8-8 8m0-18A10 10 0 0 0 2 12a10 10 0 0 0 10 10a10 10 0 0 0 10-10A10 10 0 0 0 12 2m-1 15h2v-6h-2z"/></svg>';
  var TOC_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 20 5-5 5 5"/><path d="m7 4 5 5 5-5"/></svg>';
  var TOC_KEY = 'depictio-report:toc-collapsed';
  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* storage blocked: the choice lasts for this visit */ }
    return null;
  }
  function dark() { return document.body.classList.contains('quarto-dark'); }

  // ── The colour scheme: Quarto's toggle, behind an icon that says what it does.
  function schemeButtons() {
    var btns = document.querySelectorAll('[data-dpx-scheme-toggle]');
    var canToggle = typeof window.quartoToggleColorScheme === 'function';
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      if (!canToggle) { b.hidden = true; continue; }
      var label = dark() ? 'Switch to light theme' : 'Switch to dark theme';
      b.setAttribute('aria-label', label);
      b.title = label;
      if (b.getAttribute('data-dpx-wired')) continue;
      b.setAttribute('data-dpx-wired', '1');
      b.addEventListener('click', function (ev) {
        ev.preventDefault();
        window.quartoToggleColorScheme();
      });
    }
  }
  new MutationObserver(schemeButtons).observe(document.body, { attributes: true, attributeFilter: ['class'] });

  // ── The contents: one control to fold the list to its title, remembered.
  function tocToggle() {
    var toc = document.getElementById('TOC');
    var title = toc && (document.getElementById('toc-title') || toc.querySelector(':scope > h2'));
    if (!title || title.querySelector('.dpx-toc-toggle')) return;
    var list = toc.querySelector(':scope > ul');
    if (!list) return;
    if (!list.id) list.id = 'dpx-toc-list';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dpx-toc-toggle';
    btn.setAttribute('aria-controls', list.id);
    btn.innerHTML = TOC_ICON;
    function set(collapsed, remember) {
      toc.classList.toggle('dpx-toc-collapsed', collapsed);
      var label = collapsed ? 'Expand the contents' : 'Collapse the contents';
      btn.setAttribute('aria-expanded', String(!collapsed));
      btn.setAttribute('aria-label', label);
      btn.title = label;
      if (remember) store(TOC_KEY, collapsed ? '1' : '0');
    }
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      set(!toc.classList.contains('dpx-toc-collapsed'), true);
    });
    // The title itself opens a folded list: the one thing left to click.
    title.addEventListener('click', function () {
      if (toc.classList.contains('dpx-toc-collapsed')) set(false, true);
    });
    title.id = title.id || 'toc-title';
    title.appendChild(btn);
    set(store(TOC_KEY) === '1', false);
  }

  // ── Anchors of figures and tables: after the caption, away from the tile's actions.
  function floatAnchors() {
    var links = document.querySelectorAll('.quarto-float > .anchorjs-link, div[id^="tbl-"] > .anchorjs-link, div[id^="fig-"] > .anchorjs-link');
    for (var i = 0; i < links.length; i++) {
      var a = links[i], float = a.parentElement;
      var cap = float.querySelector('.quarto-float-caption, figcaption');
      if (cap) cap.appendChild(a);
    }
  }

  // ── "About this component": the "i" of the tile, as on the dashboard.
  function tileRow(tile) {
    var row = tile.querySelector(':scope > .dpx-tile-links');
    if (!row) {
      row = document.createElement('div');
      row.className = 'dpx-tile-links';
      tile.insertBefore(row, tile.firstChild);
    }
    return row;
  }
  function tileFor(note) {
    var n = note.previousElementSibling;
    for (var steps = 0; n && steps < 3; steps++, n = n.previousElementSibling) {
      if (n.matches('.depictio-tile')) return n;
      var inner = n.querySelectorAll('.depictio-tile');
      if (inner.length) return inner[inner.length - 1];
    }
    return null;
  }
  function infoButton(item, extra) {
    var name = item.getAttribute('data-dpx-name') || '';
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'dpx-icon-btn dpx-info' + (extra ? ' ' + extra : '');
    b.innerHTML = INFO_ICON;
    var label = name ? 'About ' + name : 'About this component';
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-haspopup', 'dialog');
    b.setAttribute('aria-expanded', 'false');
    b.title = 'About this component';
    b.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      toggle(b, item);
    });
    return b;
  }
  var open = null;
  function close(focusBack) {
    if (!open) return;
    var o = open;
    open = null;
    o.pop.remove();
    o.btn.setAttribute('aria-expanded', 'false');
    if (focusBack) o.btn.focus();
  }
  function toggle(btn, item) {
    var same = open && open.btn === btn;
    close(false);
    if (same) return;
    var name = item.getAttribute('data-dpx-name') || '';
    var pop = document.createElement('div');
    pop.className = 'dpx-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', name || 'About this component');
    var accent = getComputedStyle(btn).getPropertyValue('--dpx-accent').trim();
    if (accent) pop.style.setProperty('--dpx-pop-accent', accent);
    var head = document.createElement('div');
    head.className = 'dpx-pop-head';
    head.innerHTML = INFO_ICON;
    var t = document.createElement('span');
    t.textContent = name || 'About this component';
    head.appendChild(t);
    var body = document.createElement('div');
    body.className = 'dpx-pop-body';
    body.tabIndex = 0;
    body.setAttribute('role', 'region');
    body.setAttribute('aria-label', (name || 'This component') + ', description');
    for (var c = item.firstElementChild; c; c = c.nextElementSibling) {
      // A card's note opens on its name: the popover's title says it already.
      if (c === item.firstElementChild && name && c.tagName === 'P' &&
          c.textContent.trim() === name && c.querySelector('strong')) continue;
      body.appendChild(c.cloneNode(true));
    }
    pop.appendChild(head);
    pop.appendChild(body);
    document.body.appendChild(pop);
    var r = btn.getBoundingClientRect(), w = pop.offsetWidth;
    var left = Math.max(12, Math.min(r.right - w, document.documentElement.clientWidth - w - 12));
    pop.style.left = (left + window.scrollX) + 'px';
    pop.style.top = (r.bottom + 6 + window.scrollY) + 'px';
    btn.setAttribute('aria-expanded', 'true');
    open = { btn: btn, pop: pop };
    body.focus({ preventScroll: true });
  }
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && open) close(true);
  });
  document.addEventListener('mousedown', function (ev) {
    if (open && !open.pop.contains(ev.target) && !open.btn.contains(ev.target)) close(false);
  });
  window.addEventListener('resize', function () { close(false); });
  window.addEventListener('beforeprint', function () { close(false); });

  function aboutNotes() {
    var notes = document.querySelectorAll('.callout.dpx-about:not([data-dpx-wired])');
    for (var i = 0; i < notes.length; i++) {
      var note = notes[i];
      var items = note.querySelectorAll('.dpx-about-item');
      var tile = tileFor(note);
      if (!items.length || !tile) continue;
      note.setAttribute('data-dpx-wired', '1');
      var refs = (tile.getAttribute('data-depictio-tile') || '').split(/\s+/);
      var placed = 0;
      for (var j = 0; j < items.length; j++) {
        var item = items[j], index = item.getAttribute('data-dpx-index');
        if (!index) {
          tileRow(tile).appendChild(infoButton(item));
          placed++;
          continue;
        }
        // A card of a row: its own "i", on the card the export drew.
        var pos = -1;
        for (var k = 0; k < refs.length; k++) {
          if (refs[k].split(':').pop() === index) { pos = k; break; }
        }
        var strip = tile.querySelector('.depictio-fallback .dpx-cards');
        var card = strip && pos >= 0 ? strip.children[pos] : null;
        if (card) {
          card.classList.add('dpx-card-host');
          card.appendChild(infoButton(item, 'dpx-card-info'));
        } else {
          // No card drawn to carry it: the "i" goes on the row, named.
          var b = infoButton(item, 'dpx-info-named');
          b.appendChild(document.createTextNode(item.getAttribute('data-dpx-name') || index));
          tileRow(tile).appendChild(b);
        }
        placed++;
      }
      if (placed) note.classList.add('dpx-about-wired');
    }
  }

  // ── The header bar slims down once the page scrolls.
  var bar = null, queued = false;
  function scrolled() {
    queued = false;
    bar = bar || document.querySelector('.dpx-appbar');
    if (bar) bar.classList.toggle('dpx-scrolled', window.scrollY > 8);
  }
  window.addEventListener('scroll', function () {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(scrolled);
  }, { passive: true });

  function pass() {
    try { schemeButtons(); } catch (e) { /* keep the rest */ }
    try { tocToggle(); } catch (e) { /* keep the rest */ }
    try { floatAnchors(); } catch (e) { /* keep the rest */ }
    try { aboutNotes(); } catch (e) { /* keep the rest */ }
    scrolled();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pass);
  else pass();
  window.addEventListener('load', pass);
  document.addEventListener('dpx:tile-actions', pass);
  setTimeout(pass, 700);
  setTimeout(pass, 2500);
})();
</script>"""
