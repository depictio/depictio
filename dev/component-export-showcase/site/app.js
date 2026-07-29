/* Bench Notes — gallery behaviour.
 *
 * Three delivery modes per specimen, each proving a different property of the
 * export API:
 *
 *   live  <iframe src="…format=html">   cross-origin framing works
 *   file  <iframe src="/exports/…">     the saved file is genuinely standalone,
 *                                       served by THIS origin with Depictio out
 *                                       of the loop
 *   spec  fetch(…format=json) + plotly  the JSON is a real Plotly figure this
 *                                       page can restyle
 *
 * Frames are only created when a card scrolls into view: each embed is a ~7 MB
 * document, and mounting 24 of them at once is what a demo does, not a page.
 */

const MODE_LABEL = { live: 'live frame', file: 'saved file', spec: 'plotly spec' };

const ROUTE = {
  live: [
    ['tag live', 'depictio'],
    ['hop', 'renders on request'],
    ['hop', 'iframe'],
  ],
  file: [
    ['tag file', 'this server'],
    ['hop', 'exported html on disk'],
    ['hop', 'iframe'],
  ],
  spec: [
    ['tag spec', 'depictio'],
    ['hop', 'json spec'],
    ['hop', 'our plotly.js'],
  ],
};

const state = { data: null, forcedMode: null };

async function boot() {
  document.getElementById('origin-self').textContent = location.origin;

  // ?mode=live|file|spec pins every card to one mode, and ?limit=N caps how many
  // cards exist. Both are for capture runs: each embed is a ~7 MB document, and a
  // headless browser asked for all of them at once simply stops responding.
  const params = new URLSearchParams(location.search);
  const requested = params.get('mode');
  if (['live', 'file', 'spec'].includes(requested)) state.forcedMode = requested;
  const limit = Number.parseInt(params.get('limit') ?? '', 10);

  const res = await fetch('/site-data.json');
  state.data = await res.json();
  document.getElementById('origin-api').textContent = new URL(state.data.apiBase).origin;

  let components = state.data.components;
  if (state.forcedMode) {
    // A forced mode only makes sense for components that actually offer it.
    const offers = {
      live: (c) => c.htmlStatus === 'ok',
      file: (c) => Boolean(c.savedHtml),
      spec: (c) => c.jsonStatus === 'ok',
    }[state.forcedMode];
    components = components.filter(offers);
  }
  if (Number.isFinite(limit) && limit > 0) components = components.slice(0, limit);

  if (!components.length) {
    document.getElementById('gallery').innerHTML =
      '<p class="fineprint">No exports yet. Run <code>python export_all.py --clean</code>.</p>';
    return;
  }

  mountHero(components);
  mountGallery(components);
  mountMatrix(components);
}


/* ---------- hero ---------- */

function mountHero(components) {
  const pick = components.find((c) => c.htmlStatus === 'ok') || components[0];
  document.getElementById('hero-title').textContent =
    `${pick.title} — live from ${new URL(state.data.apiBase).origin}`;
  document.getElementById('hero-url').textContent = pick.liveUrl;

  const stage = document.getElementById('hero-stage');
  if (pick.liveUrl) stage.appendChild(frameFor(pick.liveUrl, pick.title));
}

function frameFor(src, title) {
  const frame = document.createElement('iframe');
  frame.src = src;
  frame.title = title;
  frame.loading = 'lazy';
  frame.setAttribute('referrerpolicy', 'no-referrer');
  return frame;
}

/* ---------- gallery ---------- */

function mountGallery(components) {
  const gallery = document.getElementById('gallery');
  document.getElementById('gallery-count').textContent =
    `${components.length} types · ${state.data.counts.html} embeddable · ${state.data.counts.json} as spec`;

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        render(entry.target);
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: '300px' },
  );

  for (const component of components) {
    const card = buildCard(component);
    gallery.appendChild(card);
    observer.observe(card.querySelector('.stage'));
  }
}

function buildCard(component) {
  const card = document.createElement('article');
  card.className = 'specimen';

  const kind = component.vizKind
    ? `${component.componentType} · ${component.vizKind}`
    : component.componentType;

  card.innerHTML = `
    <div class="specimen-head">
      <p class="specimen-kind">${escapeHtml(kind)}</p>
      <h3 class="specimen-title">${escapeHtml(component.title)}</h3>
      <p class="specimen-from">from “${escapeHtml(component.dashboardTitle)}”</p>
    </div>
    <div class="route" role="group" aria-label="delivery mode"></div>
    <div class="route-path"></div>
    <div class="stage"></div>
    <div class="specimen-foot">
      <span>${escapeHtml(component.componentId.slice(0, 18))}</span>
      <a href="${component.liveUrl}" target="_blank" rel="noopener">open standalone ↗</a>
    </div>`;

  const available = {
    live: component.htmlStatus === 'ok',
    file: Boolean(component.savedHtml),
    spec: component.jsonStatus === 'ok',
  };

  const buttons = card.querySelector('.route');
  for (const mode of ['live', 'file', 'spec']) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = MODE_LABEL[mode];
    button.dataset.mode = mode;
    button.disabled = !available[mode];
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => select(card, component, mode));
    buttons.appendChild(button);
  }

  const stage = card.querySelector('.stage');
  stage.__component = component;
  const order = state.forcedMode
    ? [state.forcedMode, 'live', 'file', 'spec']
    : ['live', 'file', 'spec'];
  stage.__initial = order.find((mode) => available[mode]) || null;
  return card;
}

function render(stage) {
  const card = stage.closest('.specimen');
  const component = stage.__component;
  if (stage.__initial) select(card, component, stage.__initial);
  else showEmpty(stage, component, null);
}

function select(card, component, mode) {
  for (const button of card.querySelectorAll('.route button')) {
    button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  }
  drawRoute(card.querySelector('.route-path'), mode, component);

  const stage = card.querySelector('.stage');
  stage.replaceChildren();

  if (mode === 'live') {
    stage.appendChild(frameFor(component.liveUrl, component.title));
  } else if (mode === 'file') {
    stage.appendChild(frameFor(component.savedHtml, `${component.title} (saved)`));
  } else if (mode === 'spec') {
    drawSpec(stage, component);
  } else {
    showEmpty(stage, component, mode);
  }
}

function drawRoute(host, mode, component) {
  host.replaceChildren();
  const hops = ROUTE[mode] || [];
  hops.forEach(([cls, text], i) => {
    if (i) {
      const arrow = document.createElement('span');
      arrow.className = 'arrow';
      arrow.textContent = '→';
      host.appendChild(arrow);
    }
    const node = document.createElement('span');
    node.className = cls;
    node.textContent = text;
    host.appendChild(node);
  });

  if (mode === 'file' && component.htmlBytes) {
    const size = document.createElement('span');
    size.className = 'arrow';
    size.textContent = `· ${(component.htmlBytes / 1e6).toFixed(1)} MB, no network`;
    host.appendChild(size);
  }
  if (mode === 'spec' && component.jsonTraces != null) {
    const traces = document.createElement('span');
    traces.className = 'arrow';
    traces.textContent = `· ${component.jsonTraces} trace${component.jsonTraces === 1 ? '' : 's'}`;
    host.appendChild(traces);
  }
}

async function drawSpec(stage, component) {
  const host = document.createElement('div');
  host.className = 'plot';
  stage.appendChild(host);
  try {
    const res = await fetch(component.savedJson || component.jsonUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const spec = await res.json();
    // Restyled on purpose: proving the caller owns the figure, not just displays it.
    const layout = {
      ...spec.layout,
      paper_bgcolor: '#ffffff',
      plot_bgcolor: '#fbfaf7',
      font: { family: "'Inter Tight', system-ui, sans-serif", size: 11, color: '#55524a' },
      margin: { l: 46, r: 16, t: 34, b: 40 },
      showlegend: false,
    };
    await Plotly.newPlot(host, spec.data, layout, {
      ...spec.config,
      displayModeBar: false,
      responsive: true,
    });
  } catch (err) {
    stage.replaceChildren();
    showEmpty(stage, component, 'spec', String(err));
  }
}

function showEmpty(stage, component, mode, extra) {
  const box = document.createElement('div');
  box.className = 'empty';
  const reason =
    extra ||
    (mode === 'spec' ? component.jsonReason : '') ||
    'This component type has no export in that form.';
  box.innerHTML = `<strong>${escapeHtml(MODE_LABEL[mode] || 'unavailable')}</strong>
    <span class="why">${escapeHtml(reason)}</span>`;
  stage.appendChild(box);
}

/* ---------- matrix ---------- */

function mountMatrix(components) {
  const rows = components
    .map((component) => {
      const kind = component.vizKind
        ? `${component.componentType}:${component.vizKind}`
        : component.componentType;
      const html = component.formats.includes('html');
      const json = component.formats.includes('json');
      const why = json ? '' : component.jsonReason || '';
      return `<tr>
        <td class="kind">${escapeHtml(kind)}</td>
        <td class="${html ? 'yes' : 'no'}">${html ? 'yes' : '—'}</td>
        <td class="${json ? 'yes' : 'no'}">${json ? 'yes' : '—'}</td>
        <td class="why">${escapeHtml(trim(why))}</td>
      </tr>`;
    })
    .join('');

  document.getElementById('matrix').innerHTML = `
    <thead><tr><th>component</th><th>embed</th><th>spec</th><th>why not</th></tr></thead>
    <tbody>${rows}</tbody>`;
}

function trim(text) {
  return text.length > 190 ? `${text.slice(0, 190)}…` : text;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch],
  );
}

boot();
