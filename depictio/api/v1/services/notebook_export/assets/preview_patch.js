/**
 * The report editor's live preview, in the frame (PREVIEW_CONTRACT.md §3).
 *
 * The editor sends `apply` patches over postMessage; every patch is applied
 * to the document AS RENDERED (a pristine copy of every moved or rewritten
 * node is kept on the first apply, and each apply restores it first), so
 * applying twice, or a smaller patch after a bigger one, is safe. ES2017,
 * no dependency, no network, no storage: the frame is sandboxed with an
 * opaque origin, so every message is posted with target origin '*'.
 */
(function () {
  'use strict';

  // The protocol (§3) and the generator's markers (§2).
  var READY = 'depictio-preview:ready',
    SELECT = 'depictio-preview:select',
    THUMBNAIL = 'depictio-preview:thumbnail',
    SNAPSHOT = 'depictio-preview:snapshot',
    STYLES = 'depictio-preview:styles',
    SCHEME = 'depictio-preview:scheme',
    APPLY = 'depictio-preview:apply',
    THUMBNAILS = 'depictio-preview:thumbnails',
    TILE_SEL = '[data-depictio-tile],[data-depictio-prose]',
    TAB_SEL = '[data-depictio-tab]',
    SECTION_SEL = '[data-depictio-section]',
    CAPTION_SEL = '[data-depictio-caption]',
    INTRO_SEL = '[data-depictio-part="intro"]',
    CONCLUSION_SEL = '[data-depictio-part="conclusion"]',
    APPENDIX_SEL = '[data-depictio-part="appendix"]',
    // Neutral marks, currentColor/opacity so they read on any theme (§3).
    BADGE_STYLE =
      'display:inline-block;margin:0 0 .25rem;font-size:.7em;letter-spacing:.03em;' +
      'text-transform:uppercase;padding:.1em .45em;border:1px solid currentColor;' +
      'border-radius:.35em;opacity:.75;color:inherit',
    BREAK_STYLE =
      'display:flex;align-items:center;gap:.4em;margin:1.25rem 0;color:inherit;opacity:.65;font-size:.8em',
    BREAK_LINE_STYLE = 'flex:1;border-top:1px dashed currentColor',
    // The pristine document: containers -> their element children in order,
    // elements -> their innerHTML as rendered. Null until the first apply.
    PLOT_SEL = '.js-plotly-plot, .plotly-graph-div',
    MAX_SNAPSHOT_CHARS = 200000,
    MAX_TABLE_ROWS = 30,
    homes = null,
    texts = null,
    createdHeader = null,
    focusBlock = null;

  function forEach(list, fn) {
    for (var i = 0; i < list.length; i++) fn(list[i], i);
  }

  function post(msg) {
    try { window.parent.postMessage(msg, '*'); } catch (err) { /* the editor is gone */ }
  }

  // The TOC copies the tab headings' `data-depictio-tab` mark into the nav:
  // only the tab's part div counts.
  function isTabPart(el) {
    return el.tagName === 'DIV' && !el.closest('nav') && !el.closest('#quarto-margin-sidebar');
  }

  function tabParts() {
    var out = [];
    forEach(document.querySelectorAll(TAB_SEL), function (el) {
      if (isTabPart(el)) out.push(el);
    });
    return out;
  }

  function refsOf(host) {
    var out = [];
    forEach((host.getAttribute('data-depictio-tile') || host.getAttribute('data-depictio-prose') || '').trim().split(/\s+/), function (t) {
      var at = t.indexOf(':');
      if (at > 0 && at < t.length - 1) out.push({ tab_id: t.slice(0, at), component_id: t.slice(at + 1) });
    });
    return out;
  }

  // A tile's caption: the marked span in the tile's float, never one nested
  // in another tile (a card strip has no caption of its own).
  function captionOf(host) {
    var parent = host.parentNode;
    if (!parent || !parent.querySelector) return null;
    var cap = parent.querySelector(CAPTION_SEL);
    return cap && !cap.closest(TILE_SEL) ? cap : null;
  }

  // The element to move or hide for a tile: its float (the figure/table div
  // holding the caption), the grid cell when it has no caption, the host
  // itself otherwise (a card strip, a bare tile).
  function blockOf(host) {
    var cap = captionOf(host);
    if (!cap) return host.closest('.quarto-layout-cell') || host;
    var el = host.parentNode;
    while (el && !el.contains(cap)) el = el.parentNode;
    return el || host;
  }

  // The "About this component" callout that follows a tile, if any: Quarto
  // renders it as `.callout`, right after the tile's block.
  function companionOf(block) {
    var next = block.nextElementSibling;
    return next && (next.classList.contains('callout') || next.classList.contains('dpx-about')) ? next : null;
  }

  // The section div of `host`'s tab named by the patch, or null.
  function sectionTarget(host, cfg) {
    if (!cfg || typeof cfg.section !== 'string' || !cfg.section.trim()) return null;
    var tab = host.closest(TAB_SEL);
    if (!tab || !isTabPart(tab)) return null;
    var name = cfg.section.trim(), found = null;
    forEach(tab.querySelectorAll(SECTION_SEL), function (sec) {
      var value = sec.getAttribute('data-depictio-section') || '', at = value.indexOf(':');
      if (!found && at >= 0 && value.slice(at + 1) === name) found = sec;
    });
    return found;
  }

  function orderOf(value) {
    var n = value == null ? null : Number(value);
    return n !== null && isFinite(n) ? n : null;
  }

  // ── The pristine copy, and the return to it ───────────────────────────────
  // Recorded on the first apply: every container a patch can take a child
  // from or add one to, and every element it can rewrite (title block,
  // intro and conclusion parts, captions).

  function snapshot() {
    if (homes) return;
    homes = new Map();
    texts = new Map();
    function record(el) {
      if (el && !homes.has(el)) homes.set(el, Array.prototype.slice.call(el.children));
    }
    forEach(document.querySelectorAll('[data-depictio-part]'), record);
    forEach(tabParts(), record);
    forEach(document.querySelectorAll(SECTION_SEL), record);
    var header = document.querySelector('#title-block-header');
    if (header) texts.set(header, header.innerHTML);
    forEach(document.querySelectorAll(INTRO_SEL + ',' + CONCLUSION_SEL), function (el) { texts.set(el, el.innerHTML); });
    forEach(document.querySelectorAll(CAPTION_SEL), function (el) { texts.set(el, el.innerHTML); });
  }

  function restore() {
    if (!homes) return;
    forEach(document.querySelectorAll('[data-depictio-preview-badge],[data-depictio-preview-break]'),
      function (el) { if (el.parentNode) el.parentNode.removeChild(el); });
    texts.forEach(function (html, el) { if (el.isConnected) el.innerHTML = html; });
    // Outer containers first: a tab part returns to the flow with its
    // sections and tiles, then their order inside it is put back.
    homes.forEach(function (kids, container) {
      forEach(kids, function (child) { if (child.isConnected) container.appendChild(child); });
    });
    forEach(document.querySelectorAll(TILE_SEL), function (host) { blockOf(host).style.display = ''; });
    if (focusBlock) { focusBlock.style.outline = ''; focusBlock.style.outlineOffset = ''; focusBlock = null; }
    if (createdHeader) {
      if (createdHeader.parentNode) createdHeader.parentNode.removeChild(createdHeader);
      createdHeader = null;
    }
  }

  // ── The patch (§3) ─────────────────────────────────────────────────────────

  function apply(patch) {
    if (!patch || typeof patch !== 'object') return;
    snapshot();
    restore();
    if (patch.cover && typeof patch.cover === 'object') applyCover(patch.cover);
    if (typeof patch.intro_html === 'string') setText(INTRO_SEL, patch.intro_html);
    if (typeof patch.conclusion_html === 'string') setText(CONCLUSION_SEL, patch.conclusion_html);
    if (Array.isArray(patch.tabs)) applyTabs(patch.tabs);
    if (Array.isArray(patch.tiles)) applyTiles(patch.tiles);
    applyFocus(patch.focus);
  }

  function setText(selector, html) {
    var el = document.querySelector(selector);
    if (el) el.innerHTML = html;
  }

  function mark(tag, attrs, text, style) {
    var el = document.createElement(tag);
    for (var key in attrs) el.setAttribute(key, attrs[key]);
    if (style) el.setAttribute('style', style);
    el.textContent = text;
    return el;
  }

  function coverText(header, selector, tag, cls, text, first) {
    var el = header.querySelector(selector);
    if (!el) {
      el = document.createElement(tag);
      el.className = cls;
      header.appendChild(el);
    }
    if (first) header.insertBefore(el, header.firstChild);
    el.textContent = text;
    return el;
  }

  function applyCover(cover) {
    if (cover.title == null && cover.subtitle == null && cover.authors == null) return;
    var header = document.querySelector('#title-block-header');
    if (!header) {
      // A report without a title block gets one for the cover the editor sets.
      var main = document.querySelector('main') || document.body;
      header = document.createElement('header');
      header.setAttribute('id', 'title-block-header');
      main.insertBefore(header, main.firstChild);
      createdHeader = header;
    }
    if (cover.title != null) coverText(header, 'h1.title, h1', 'h1', 'title', String(cover.title), true);
    if (cover.subtitle != null) coverText(header, '.subtitle', 'p', 'subtitle', String(cover.subtitle), false);
    if (cover.authors != null) {
      var author = coverText(header, '.author', 'p', 'author', cover.authors.join(', '), false);
      forEach(header.querySelectorAll('.author'), function (el) {
        if (el !== author && el.parentNode) el.parentNode.removeChild(el);
      });
    }
  }

  // Appendix tabs land in the appendix part, in their order; a tab without
  // one keeps the order the document gave it. Body tabs: ordered ones lead.
  function applyTabs(entries) {
    var cfg = {}, appendix = document.querySelector(APPENDIX_SEL), body = [], moving = [];
    forEach(entries, function (t) { if (t && t.tab_id != null) cfg[String(t.tab_id)] = t; });
    forEach(tabParts(), function (part) {
      var c = cfg[part.getAttribute('data-depictio-tab') || ''];
      if (!c) return;
      (c.placement === 'appendix' && appendix ? moving : body).push({ part: part, order: orderOf(c.order) });
    });
    moving.sort(function (a, b) { return a.order === null || b.order === null ? 0 : a.order - b.order; });
    forEach(moving, function (m) { appendix.appendChild(m.part); });
    var ordered = [];
    forEach(body, function (m) { if (m.order !== null) ordered.push(m); });
    if (!ordered.length) return;
    ordered.sort(function (a, b) { return a.order - b.order; });
    var parent = body[body.length - 1].part.parentNode,
      anchor = body[body.length - 1].part.nextElementSibling;
    if (anchor && anchor.parentNode !== parent) anchor = null;
    forEach(ordered, function (m) { parent.insertBefore(m.part, anchor); });
  }

  // A tile hidden when the patch takes it out of the report; decorated with
  // its PDF marks; its caption rewritten when the layer sets one; moved to
  // another section of the same tab when one is named.
  function applyTiles(entries) {
    var byRef = {};
    forEach(entries, function (t) {
      if (t && t.tab_id != null && t.component_id != null) byRef[String(t.tab_id) + ':' + String(t.component_id)] = t;
    });
    forEach(document.querySelectorAll(TILE_SEL), function (host) {
      var refs = refsOf(host);
      if (!refs.length) return;
      var cfgs = [], hidden = true;
      forEach(refs, function (ref) {
        var c = byRef[ref.tab_id + ':' + ref.component_id];
        if (c) { cfgs.push(c); if (c.in_report !== false) hidden = false; } else hidden = false;
      });
      if (hidden) blockOf(host).style.display = 'none';
      decorate(host, cfgs);
      setCaption(host, cfgs);
      var target = sectionTarget(host, cfgs[0]), moved = target ? blockOf(host) : null;
      if (moved && moved.parentNode !== target) {
        target.appendChild(moved);
        var companion = companionOf(moved);
        if (companion) target.appendChild(companion);
      }
    });
    reorderTiles(byRef);
  }

  function decorate(host, cfgs) {
    var c = cfgs[0];
    if (!c) return;
    var label = c.in_pdf === false ? 'HTML only'
      : c.orientation === 'landscape' ? 'Landscape in PDF'
      : c.orientation === 'portrait' ? 'Portrait in PDF' : null;
    if (label) host.insertBefore(mark('span', { 'data-depictio-preview-badge': '' }, label, BADGE_STYLE), host.firstChild);
    if (c.page_break_before && host.parentNode) {
      var line = mark('div', { 'data-depictio-preview-break': '' }, 'Page break', BREAK_STYLE);
      line.appendChild(mark('span', {}, '', BREAK_LINE_STYLE));
      host.parentNode.insertBefore(line, host);
    }
  }

  function setCaption(host, cfgs) {
    var c = cfgs[0];
    if (!c || c.caption == null) return;
    var cap = captionOf(host);
    if (cap) cap.textContent = String(c.caption);
  }

  // Tiles are reordered within their container (a section, a tab part) by
  // `order`; the ones without one keep their place. A unit is a direct child
  // carrying tiles, moved with the callout that follows it, if one does.
  function reorderTiles(byRef) {
    var containers = [], seen = new Map();
    function add(el) { if (el && !seen.has(el)) { seen.set(el, true); containers.push(el); } }
    forEach(document.querySelectorAll(SECTION_SEL), add);
    forEach(tabParts(), add);
    forEach(containers, function (container) {
      var units = [], ordered = [], rest = [];
      forEach(container.children, function (child) {
        if (child.matches(SECTION_SEL) || child.matches(TAB_SEL)) return;
        var rec = unitOf(child, byRef);
        if (rec) units.push({ el: child, order: rec.order, companion: rec.companion });
      });
      forEach(units, function (u) { (u.order === null ? rest : ordered).push(u); });
      if (!ordered.length) return;
      ordered.sort(function (a, b) { return a.order - b.order; });
      forEach(ordered.concat(rest), function (u) {
        container.appendChild(u.el);
        if (u.companion) container.appendChild(u.companion);
      });
    });
  }

  function unitOf(el, byRef) {
    var order = null, found = false,
      hosts = el.matches(TILE_SEL) ? [el] : el.querySelectorAll(TILE_SEL);
    forEach(hosts, function (host) {
      forEach(refsOf(host), function (ref) {
        var c = byRef[ref.tab_id + ':' + ref.component_id], o = c ? orderOf(c.order) : null;
        if (c) found = true;
        if (o !== null && (order === null || o < order)) order = o;
      });
    });
    return found ? { order: order, companion: companionOf(el) } : null;
  }

  // Focus: the outline, and the tile scrolled to the middle of the frame, only
  // when the focus moves: the editor resends it with every patch, and typing a
  // caption must not keep recentring the page.
  var scrolledTo = null;
  function applyFocus(focus) {
    if (!focus || focus.tab_id == null || focus.component_id == null) { scrolledTo = null; return; }
    var ref = String(focus.tab_id) + ':' + String(focus.component_id), host = null;
    forEach(document.querySelectorAll(TILE_SEL), function (t) {
      forEach(refsOf(t), function (r) { if (host === null && r.tab_id + ':' + r.component_id === ref) host = t; });
    });
    if (!host) return;
    var block = blockOf(host);
    block.style.outline = '2px solid currentColor';
    block.style.outlineOffset = '2px';
    focusBlock = block;
    if (scrolledTo === ref) return;
    scrolledTo = ref;
    if (typeof block.scrollIntoView === 'function') {
      try { block.scrollIntoView({ block: 'center' }); } catch (err) { block.scrollIntoView(); }
    }
  }

  // ── The messages the frame posts itself (§3) ──────────────────────────────

  // `ready` once the document has loaded: the tiles and tabs it holds, each once.
  function announce() {
    var tiles = [], seenTiles = new Map(), tabs = [];
    forEach(document.querySelectorAll(TILE_SEL), function (host) {
      forEach(refsOf(host), function (ref) {
        var key = ref.tab_id + ':' + ref.component_id;
        if (!seenTiles.has(key)) { seenTiles.set(key, true); tiles.push(ref); }
      });
    });
    forEach(tabParts(), function (part) {
      var id = part.getAttribute('data-depictio-tab') || '';
      if (tabs.indexOf(id) < 0) tabs.push(id);
    });
    post({ type: READY, tiles: tiles, tabs: tabs });
  }

  // A click on a tile tells the editor: the reader is looking at this one.
  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || typeof target.closest !== 'function') return;
    var host = target.closest(TILE_SEL), refs = host ? refsOf(host) : [];
    if (refs.length) post({ type: SELECT, tab_id: refs[0].tab_id, component_id: refs[0].component_id });
  });

  // A Plotly tile gets a PNG, as asked (§3); every other tile and prose block
  // gets a snapshot of its markup (below), so no card is left with an icon.
  function thumbnails(width, height) {
    postStyles();
    forEach(document.querySelectorAll(TILE_SEL), function (host) {
      var refs = refsOf(host);
      if (!refs.length) return;
      var plot = host.querySelector(PLOT_SEL);
      if (!plot) { postSnapshots(host, refs); return; }
      if (!window.Plotly || typeof window.Plotly.toImage !== 'function') return;
      var w = orderOf(width) || 600, h = orderOf(height) || 400;
      try {
        Promise.resolve(window.Plotly.toImage(plot, { format: 'png', width: w, height: h }))
          .then(function (dataUrl) {
            if (typeof dataUrl === 'string' && dataUrl)
              post({ type: THUMBNAIL, tab_id: refs[0].tab_id, component_id: refs[0].component_id, data_url: dataUrl });
          })
          .catch(function () { /* a tile that cannot be drawn sends no thumbnail */ });
      } catch (err) { /* as above */ }
    });
  }

  // ── Snapshots: the look of a tile without scripts ─────────────────────────

  // The look of the document, once: its stylesheets (absolute), its inline
  // css, and the classes that switch its theme, so the editor can rebuild it.
  function postStyles() {
    var links = [], css = '', root = document.documentElement, scheme = '';
    forEach(document.querySelectorAll('link[rel~="stylesheet"]'), function (link) {
      if (!link.disabled && link.href) links.push(link.href);
    });
    forEach(document.querySelectorAll('style'), function (el) { css += el.textContent + '\n'; });
    try { scheme = root.style.colorScheme || window.getComputedStyle(root).colorScheme || ''; } catch (err) { /* none */ }
    post({
      type: STYLES,
      links: links,
      css: css,
      html_class: root.className || '',
      body_class: document.body ? document.body.className || '' : '',
      color_scheme: scheme === 'normal' ? '' : scheme
    });
  }

  // ── The colour scheme: the editor's, not the browser's ────────────────────

  // Quarto's own mechanism: the report carries a light and a dark stylesheet
  // set (`link.quarto-color-scheme`, the dark one `.quarto-color-alternate`
  // when the light is the author's default) and `toggleColorMode(alternate)`,
  // declared by Quarto's inline script, switches them, the `quarto-dark` /
  // `quarto-light` body class and the toggle button. Its toggle button and the
  // OS listener read the choice from the browser's storage, which the sandboxed
  // frame may not touch (the script even stops at its first read there, so the
  // page would be left on whatever the OS prefers). So the editor sends the scheme
  // and it is set here, deterministically, never toggled.
  function alternateIsDark(sheets) {
    var mode = null;
    forEach(sheets, function (sheet) {
      var m = sheet.getAttribute('data-mode');
      if (m && sheet.classList.contains('quarto-color-alternate')) mode = m;
    });
    return mode === null || mode === 'dark';
  }

  function setBodyMode(dark) {
    if (!document.body) return;
    document.body.classList.add(dark ? 'quarto-dark' : 'quarto-light');
    document.body.classList.remove(dark ? 'quarto-light' : 'quarto-dark');
  }

  // Quarto's switch re-done by hand, for a version that does not expose it.
  function switchSheets(alternate) {
    var primary = document.querySelectorAll('link.quarto-color-scheme:not(.quarto-color-alternate)'),
      alt = document.querySelectorAll('link.quarto-color-scheme.quarto-color-alternate');
    forEach(alternate ? alt : primary, function (sheet) { if (sheet.rel !== 'stylesheet') sheet.rel = 'stylesheet'; });
    // Dark is layered on light: the primary set stays on for the alternate.
    if (!alternate) forEach(alt, function (sheet) { sheet.rel = 'disabled-stylesheet'; });
    forEach(alternate ? alt : primary, function (sheet) {
      if (sheet.id === 'quarto-bootstrap') setBodyMode(sheet.getAttribute('data-mode') === 'dark');
    });
    forEach(document.querySelectorAll('.quarto-color-scheme-toggle'), function (t) {
      if (alternate) t.classList.add('alternate'); else t.classList.remove('alternate');
    });
  }

  function applyScheme(scheme) {
    if (scheme !== 'light' && scheme !== 'dark') return;
    var sheets = document.querySelectorAll('link.quarto-color-scheme');
    if (sheets.length) {
      var alternate = (scheme === 'dark') === alternateIsDark(sheets);
      var done = false;
      if (typeof toggleColorMode === 'function') {
        try { toggleColorMode(alternate); done = true; } catch (err) { /* by hand, below */ }
      }
      if (!done) switchSheets(alternate);
      // The report's own toggle cannot work here (no storage), and the editor
      // decides: it is hidden rather than left to do nothing.
      forEach(document.querySelectorAll('.quarto-color-scheme-toggle'), function (t) {
        t.style.display = 'none';
      });
      try { window.dispatchEvent(new Event('resize')); } catch (err) { /* old engine */ }
    }
    // The classes and sheets the editor rebuilds snapshots with changed.
    postStyles();
  }

  function absolute(value) {
    try { return new URL(value, document.baseURI).href; } catch (err) { return value; }
  }

  // The markup of `el`, inert: no script or embed, absolute URLs, the
  // preview's own marks and hiding undone, long tables cut short.
  function snapshotHtml(el) {
    var copy = el.cloneNode(true);
    forEach(copy.querySelectorAll('script,iframe,object,embed,[data-depictio-preview-badge],[data-depictio-preview-break]'),
      function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    copy.style.display = '';
    copy.style.outline = '';
    copy.style.outlineOffset = '';
    forEach(copy.querySelectorAll('[src],[href],[poster]'), function (n) {
      forEach(['src', 'href', 'poster'], function (attr) {
        var v = n.getAttribute(attr);
        if (v && !/^(#|data:|javascript:|mailto:)/i.test(v)) n.setAttribute(attr, absolute(v));
      });
    });
    forEach(copy.querySelectorAll('tbody'), function (body) {
      while (body.children.length > MAX_TABLE_ROWS) body.removeChild(body.lastElementChild);
    });
    return copy.outerHTML;
  }

  // The part of a card strip that is `index`'s card: its slot (`card_row`
  // wraps each card in one, in the row's order), else the first element down
  // the host with as many children as there are refs. Else null (the block).
  function subElementOf(host, index, count) {
    if (count < 2) return null;
    var slots = host.querySelectorAll('.dpx-card-slot');
    if (slots.length === count) return slots[index];
    var el = host;
    for (var depth = 0; depth < 8 && el; depth++) {
      if (el.children.length === count) return el.children[index];
      if (el.children.length !== 1) return null;
      el = el.children[0];
    }
    return null;
  }

  function postSnapshots(host, refs) {
    var block = blockOf(host);
    forEach(refs, function (ref, i) {
      var html;
      try { html = snapshotHtml(subElementOf(host, i, refs.length) || block); } catch (err) { return; }
      if (html.length > MAX_SNAPSHOT_CHARS) return;
      post({ type: SNAPSHOT, tab_id: ref.tab_id, component_id: ref.component_id, html: html });
    });
  }

  window.addEventListener('message', function (event) {
    var msg = event.data;
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === APPLY) apply(msg.patch);
    else if (msg.type === THUMBNAILS) thumbnails(msg.width, msg.height);
    else if (msg.type === SCHEME) applyScheme(msg.scheme);
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', announce);
  else announce();
})();
