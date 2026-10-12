/* Bench Notes — gallery behaviour.
 *
 * JSON-first, deliberately. Depictio is visualisation-oriented and the consumer
 * already has the data, so the deliverable is a finished Plotly figure spec they
 * re-render in their own page with their own plotly.js. Cards therefore default
 * to `spec` wherever the API offers it.
 *
 * The two iframe modes are the fallback for component types with no server-side
 * figure, and they are labelled as such:
 *
 *   spec  fetch(…format=json) + our plotly.js   no iframe, restyleable, ~80 KB
 *   live  <iframe src="…format=html">           whole component, needs Depictio
 *   file  <iframe src="/exports/…">             same, saved to disk, ~7 MB
 */

const MODE_LABEL = { spec: 'plotly spec', live: 'live frame', file: 'saved file' };

const ROUTE = {
  spec: [
    ['tag spec', 'depictio'],
    ['hop', 'json spec'],
    ['hop', 'our plotly.js'],
  ],
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
};

const MODES = ['spec', 'live', 'file'];

const state = { data: null, forcedMode: null };

/* Live embeds all come from the Depictio origin, so the browser puts them in one
 * process that shares a WebGL context budget (~16). Several advanced-viz
 * renderers draw with scattergl, so mounting six at once makes the later frames
 * fail with "WebGL is not supported" — a limit of this page, not of the export.
 *
 * So: mount at most MAX_LIVE_FRAMES iframes, oldest evicted first, and mount
 * them one at a time. An evicted card keeps its place and remounts on demand. */
const MAX_LIVE_FRAMES = 3;
const live = { mounted: [], queue: [], busy: false };

function enqueueMount(stage, build) {
  live.queue.push({ stage, build });
  pumpQueue();
}

function pumpQueue() {
  if (live.busy || !live.queue.length) return;
  const { stage, build } = live.queue.shift();
  live.busy = true;

  while (live.mounted.length >= MAX_LIVE_FRAMES) {
    evict(live.mounted.shift());
  }

  const frame = build();
  live.mounted.push(stage);
  const release = () => {
    live.busy = false;
    pumpQueue();
  };
  frame.addEventListener('load', release, { once: true });
  // A frame that never fires load must not wedge the queue.
  setTimeout(release, 4000);
}

function evict(stage) {
  if (!stage || !stage.isConnected) return;
  stage.replaceChildren();
  const note = document.createElement('div');
  note.className = 'empty';
  note.innerHTML = `<strong>frame released</strong>
    <span class="why">Only ${MAX_LIVE_FRAMES} live frames are kept mounted, because they
    share one WebGL budget. Scroll back or press the mode button to remount.</span>`;
  stage.appendChild(note);
  stage.__evicted = true;
}

function mountNav(pages) {
  const host = document.getElementById('sitenav');
  if (!host) return;
  const here = location.pathname.replace(/\/$/, '') || '/';
  host.innerHTML = `<ul>${pages
    .map((page) => {
      const current = (page.href.replace(/\/$/, '') || '/') === here;
      return `<li><a href="${page.href}"${current ? ' aria-current="page"' : ''}>${escapeHtml(
        page.label,
      )}</a></li>`;
    })
    .join('')}</ul>`;
}

async function boot() {
  const originSelf = document.getElementById('origin-self');
  if (originSelf) originSelf.textContent = location.origin;

  // ?mode=live|file|spec pins every card to one mode, and ?limit=N caps how many
  // cards exist. Both are for capture runs: each embed is a ~7 MB document, and a
  // headless browser asked for all of them at once simply stops responding.
  const params = new URLSearchParams(location.search);
  const requested = params.get('mode');
  if (MODES.includes(requested)) state.forcedMode = requested;
  const limit = Number.parseInt(params.get('limit') ?? '', 10);

  const res = await fetch('/site-data.json');
  state.data = await res.json();
  mountNav(state.data.pages || []);
  const originApi = document.getElementById('origin-api');
  if (originApi) originApi.textContent = new URL(state.data.apiBase).origin;

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
  // The hero must demonstrate the recommended path, so it renders a JSON spec
  // with this page's own plotly.js — no iframe anywhere in the opening statement.
  const pick =
    components.find((c) => c.jsonStatus === 'ok' && c.jsonTraces) || components[0];
  document.getElementById('hero-title').textContent = `${pick.title} — our plotly.js`;
  document.getElementById('hero-url').textContent = pick.jsonUrl || pick.liveUrl;

  const stage = document.getElementById('hero-stage');
  if (pick.jsonStatus === 'ok') {
    drawSpec(stage, pick, { hero: true });
  } else if (pick.liveUrl) {
    stage.appendChild(frameFor(pick.liveUrl, pick.title));
  }
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
  const asSpec = components.filter((c) => c.jsonStatus === 'ok').length;
  document.getElementById('gallery-count').textContent =
    `${asSpec} of ${components.length} available as a Plotly spec · the rest need a frame`;

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
  card.dataset.span = component.span || 'normal';

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
  for (const mode of MODES) {
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
  // JSON-first: prefer `spec` (no iframe) and fall back only when the API
  // offers no server-side figure for this component type.
  const order = state.forcedMode ? [state.forcedMode, ...MODES] : MODES;
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
    enqueueMount(stage, () => {
      const frame = frameFor(component.liveUrl, component.title);
      stage.replaceChildren(frame);
      return frame;
    });
  } else if (mode === 'file') {
    enqueueMount(stage, () => {
      const frame = frameFor(component.savedHtml, `${component.title} (saved)`);
      stage.replaceChildren(frame);
      return frame;
    });
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

async function drawSpec(stage, component, { hero = false } = {}) {
  const host = document.createElement('div');
  host.className = 'plot';
  stage.appendChild(host);
  try {
    const res = await fetch(component.savedJson || component.jsonUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const spec = await res.json();
    // Restyled on purpose: proving the caller owns the figure, not just displays
    // it. `height`/`width` are dropped rather than overridden because Plotly
    // treats an explicit height as authoritative and the figure would paint
    // outside its card; without them it fills the container and stays responsive.
    const { height: _h, width: _w, ...inherited } = spec.layout || {};
    const layout = {
      ...inherited,
      autosize: true,
      paper_bgcolor: '#ffffff',
      plot_bgcolor: '#fbfaf7',
      font: { family: "'Inter Tight', system-ui, sans-serif", size: hero ? 12 : 11, color: '#55524a' },
      margin: { l: 46, r: 16, t: 34, b: 40 },
      showlegend: false,
    };
    await Plotly.newPlot(host, spec.data, layout, {
      ...spec.config,
      displayModeBar: hero,
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
      const json = component.formats.includes('json');
      const html = component.formats.includes('html');
      const size = component.jsonBytes ? `${(component.jsonBytes / 1e3).toFixed(0)} KB` : '';
      return `<tr>
        <td class="kind">${escapeHtml(kind)}</td>
        <td class="${json ? 'yes' : 'no'}">${json ? `spec · ${size}` : '—'}</td>
        <td class="${html ? 'yes' : 'no'}">${html ? 'frame' : '—'}</td>
        <td class="why">${escapeHtml(trim(json ? '' : component.jsonReason || ''))}</td>
      </tr>`;
    })
    .join('');

  document.getElementById('matrix').innerHTML = `
    <thead><tr><th>component</th><th>plotly spec</th><th>frame</th><th>why no spec yet</th></tr></thead>
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
