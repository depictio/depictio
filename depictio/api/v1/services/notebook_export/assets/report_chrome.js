
(function () {
  'use strict';
  var INFO_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 9h2V7h-2m1 13c-4.41 0-8-3.59-8-8s3.59-8 8-8s8 3.59 8 8s-3.59 8-8 8m0-18A10 10 0 0 0 2 12a10 10 0 0 0 10 10a10 10 0 0 0 10-10A10 10 0 0 0 12 2m-1 15h2v-6h-2z"/></svg>';
  var TOC_KEY = 'depictio-report:toc-mode';
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

  // ── The contents: three ways to show them, chosen in the bar, remembered.
  // Full (the outline), light (the tabs only, compact) or hidden (the column
  // goes and the report takes its width). In the bar, not on the contents:
  // hidden contents have nowhere to hold their own button.
  var TOC_MODES = [
    { id: 'full', label: 'Full contents', icon: '<path d="M21 12h-8"/><path d="M21 6H8"/><path d="M21 18h-8"/><path d="M3 6v4c0 1.1.9 2 2 2h3"/><path d="M3 10v6c0 1.1.9 2 2 2h3"/>' },
    { id: 'light', label: 'Tabs only', icon: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>' },
    { id: 'hidden', label: 'Hide the contents', icon: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/><path d="m8 9 3 3-3 3"/>' }
  ];
  function setTocMode(mode, remember) {
    var known = TOC_MODES.some(function (m) { return m.id === mode; });
    if (!known) mode = 'full';
    document.body.setAttribute('data-dpx-toc', mode);
    var btns = document.querySelectorAll('.dpx-toc-mode');
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute('aria-pressed', String(btns[i].getAttribute('data-mode') === mode));
    }
    if (remember) store(TOC_KEY, mode);
  }
  function tocModes() {
    if (!document.getElementById('TOC')) return;
    var end = document.querySelector('.dpx-appbar-end');
    if (!end || end.querySelector('.dpx-toc-modes')) return;
    var group = document.createElement('span');
    group.className = 'dpx-toc-modes';
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', 'Contents');
    TOC_MODES.forEach(function (m) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dpx-toc-mode';
      btn.setAttribute('data-mode', m.id);
      btn.setAttribute('aria-label', m.label);
      btn.title = m.label;
      btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + m.icon + '</svg>';
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        setTocMode(m.id, true);
      });
      group.appendChild(btn);
    });
    end.insertBefore(group, end.firstChild);
    setTocMode(store(TOC_KEY), false);
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
  // The tile a note describes: the runtime's placeholder when the report
  // carries one, else the output right above the note (its figure, its
  // table, the cell that drew it), in a report rendered without the runtime.
  function tileFor(note) {
    // The nearest output above the note, never one past it: a note whose
    // own tile has no placeholder must not land on the tile before it.
    var n = note.previousElementSibling;
    for (var steps = 0; n && steps < 3; steps++, n = n.previousElementSibling) {
      if (n.matches('.depictio-tile')) return n;
      var inner = n.querySelectorAll('.depictio-tile');
      if (inner.length) return inner[inner.length - 1];
      if (n.matches('.quarto-float, div[id^="fig-"], div[id^="tbl-"], .cell')) return n;
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
      // The placeholder's refs (`<tab>:<index> ...`), when the note has one.
      var refs = (tile.dataset.depictioTile || '').split(/\s+/);
      var placed = 0;
      for (var j = 0; j < items.length; j++) {
        var item = items[j], index = item.getAttribute('data-dpx-index');
        if (!index) {
          tileRow(tile).appendChild(infoButton(item));
          placed++;
          continue;
        }
        // A card of a row: its own "i", on the card the export drew.
        var pos = parseInt(item.getAttribute('data-dpx-pos') || '-1', 10);
        for (var k = 0; pos < 0 && k < refs.length; k++) {
          if (refs[k].split(':').pop() === index) pos = k;
        }
        var strip = tile.querySelector('.dpx-cards');
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
    try { tocModes(); } catch (e) { /* keep the rest */ }
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
