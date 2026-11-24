
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
  // A chevron as the app draws one (Lucide's chevron-down), not a glyph: a
  // "▾" at the contents' small size was too faint to be seen as a control.
  var TOC_CHEVRON = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
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
      chev.className = sub ? 'dpx-chev dpx-toc-chev' : 'dpx-chev dpx-toc-chev dpx-gap';
      chev.innerHTML = TOC_CHEVRON;
      if (sub) {
        chev.setAttribute('role', 'button');
        chev.setAttribute('aria-label', 'Fold or unfold this part of the contents');
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
