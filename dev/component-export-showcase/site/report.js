/* Surveillance dashboard — the Swedish Pathogens Portal's layout, driven by
 * Depictio exports.
 *
 * The portal's own wastewater dashboards (Django + htmx + plotly.js) put a
 * three-column grey control deck above each figure: a normalisation choice, an
 * "all sites / per site" toggle with a site select, and a rolling window. Change
 * anything and htmx re-fetches the figure from the server.
 *
 * This page keeps that shape exactly and swaps the back end. Every control is
 * bound to a real interactive component from Depictio's export manifest, and
 * every figure is a `format=json` export drawn by this page's plotly.js in the
 * portal's own styling. So the demonstration is not "here is a Depictio
 * dashboard with portal colours" — it is "a host that already has a dashboard
 * idiom can keep it, and put Depictio behind it".
 *
 * The mapping is the interesting part, and it is declared in CONTROLS below:
 * portal control shape on the left, Depictio filter column on the right. The
 * option lists are never hard-coded — they come from the manifest, so a control
 * cannot drift out of step with the data it filters.
 */

const API_HINT = '/site-data.json';
const DASHBOARD = '646b0f3c1e4a2d7f8e5b8cb3';

/* Data collections. A filter only reaches a figure whose collection has the
 * column, so every figure declares which one it draws from. */
const DC = {
  samples: '646b0f3c1e4a2d7f8e5b8ca5',
  taxonomy: '646b0f3c1e4a2d7f8e5b8ca9',
  stacked: '646b0f3c1e4a2d7f8e5b8cb1',
  sunburst: '646b0f3c1e4a2d7f8e5b8cd3',
  sankey: '646b0f3c1e4a2d7f8e5b8cd4',
  upset: '646b0f3c1e4a2d7f8e5b8cd6',
};

/* Portal palette, read out of portal.f55c915045c1.css.
 *   --color-pp-dark-blue #295986   --color-pp-mid-blue  #4770b1
 *   --color-pp-teal      #37ae94   --color-pp-lime-green #d4de27
 * The trace colours below are the ones the portal's own figures use. */
const PP = {
  darkBlue: '#295986',
  midBlue: '#4770b1',
  teal: '#37ae94',
  lime: '#d4de27',
  ink: '#1a1c1a',
  grey: '#55585a',
  line: '#d6d6d6',
  grid: '#e8e8e8',
};
const PP_SEQUENCE = ['#d6604d', '#2166ac', '#37ae94', '#b691d2', '#295986', '#4770b1', '#8a6d3b', '#7fbc41'];

/* The portal's control deck, mapped onto Depictio filters.
 *
 * `column` names the Depictio interactive component to bind to; everything else
 * describes how the portal presents it. A `toggle` group reproduces the portal's
 * "All sites / Per site" radio pair, where selecting one dims the other.
 */
const CONTROLS = [
  {
    id: 'scope',
    kind: 'toggle',
    label: 'All habitats',
    altLabel: 'Per habitat',
    hint: 'Select habitat',
    column: 'habitat',
  },
  {
    id: 'kingdom',
    kind: 'select',
    label: 'Taxonomic domain',
    hint: 'Select kingdom',
    column: 'Kingdom',
  },
  {
    id: 'period',
    kind: 'dates',
    label: 'Sampling period',
    hint: 'Restrict the window',
    column: 'sampling_date',
  },
];

/* Figures, in the portal's own order: the quantitative panel first with its
 * control deck, then the qualitative breakdown. */
const FIGURES = [
  {
    slot: 'quant',
    component: 'd595144f-eaab-45f9-9138-b6f342fe2582',
    dc: DC.taxonomy,
  },
  { slot: 'stacked', component: 'adv-stacked-taxonomy', dc: DC.stacked },
  { slot: 'sunburst', component: 'adv-sunburst', dc: DC.sunburst },
  { slot: 'sankey', component: 'adv-sankey', dc: DC.sankey },
];

const state = { apiBase: '', filters: [], controls: [] };

function filtersFor(dc) {
  if (!dc) return [];
  return state.filters.filter((entry) => entry.dc === dc).map((entry) => entry.filter);
}

/* Draw one export in the portal's plotly idiom.
 *
 * The portal's figures share a recognisable treatment: white plot area, a thin
 * mirrored axis frame in #d6d6d6, pale horizontal gridlines only, a small
 * legend, and tight margins. Reproducing it here is the whole point — the same
 * Depictio spec would look like a foreign object with Depictio's own layout.
 */
async function drawFigure(host, spec) {
  const { height: _h, width: _w, ...inherited } = spec.layout || {};

  // Strip decorative per-trace colour so the portal sequence applies, but leave
  // colour that *encodes* a value (an array, a colorscale) untouched.
  const data = (spec.data || []).map((trace) => {
    const next = { ...trace };
    for (const key of ['marker', 'line']) {
      const sub = next[key];
      if (!sub || typeof sub !== 'object') continue;
      if (Array.isArray(sub.color) || sub.colorscale || sub.showscale) continue;
      const { color: _dropped, ...rest } = sub;
      next[key] = rest;
    }
    return next;
  });

  const axis = {
    linewidth: 0.8,
    linecolor: PP.line,
    mirror: true,
    zerolinecolor: '#ffffff',
  };

  // A faceted figure carries xaxis2/yaxis2/… as well, and restyling only
  // `xaxis`/`yaxis` leaves the other rows in Depictio's styling — and, worse,
  // repeats the full y-axis title on every facet, which is what turns a
  // four-row habitat plot into a column of overlapping labels. Apply the same
  // treatment to every axis, and keep the title on the first only.
  const axes = {};
  for (const key of Object.keys(inherited)) {
    if (!/^[xy]axis(\d+)?$/.test(key)) continue;
    const isFirst = key === 'xaxis' || key === 'yaxis';
    const vertical = key.startsWith('y');
    axes[key] = {
      ...inherited[key],
      ...axis,
      ...(vertical ? { showgrid: true, gridcolor: PP.grid, gridwidth: 0.8 } : {}),
      ...(isFirst ? {} : { title: { text: '' } }),
    };
  }

  await Plotly.newPlot(
    host,
    data,
    {
      ...inherited,
      ...axes,
      autosize: true,
      paper_bgcolor: '#ffffff',
      plot_bgcolor: '#ffffff',
      colorway: PP_SEQUENCE,
      font: { family: 'IBM Plex Sans, Helvetica, Arial, sans-serif', size: 12, color: PP.ink },
      margin: { l: 60, r: 20, t: 30, b: 50 },
      legend: { ...(inherited.legend || {}), font: { size: 10 } },
      hoverlabel: { font: { family: 'IBM Plex Sans, sans-serif', size: 11 } },
    },
    { ...spec.config, displayModeBar: false, responsive: true },
  );
}

async function loadFigure(entry) {
  const section = document.querySelector(`[data-slot="${entry.slot}"]`);
  if (!section) return;
  const stage = section.querySelector('.pp-stage');
  const status = section.querySelector('.pp-status');
  const filters = filtersFor(entry.dc);

  // The portal dims a panel while htmx is in flight; same affordance here, for
  // the same reason: a figure that silently swaps is hard to trust.
  section.classList.add('is-loading');

  const url = exportUrl(state.apiBase, {
    dashboard: DASHBOARD,
    component: entry.component,
    format: 'json',
    filters,
  });

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const spec = await response.json();
    await drawFigure(stage, spec);

    const traces = (spec.data || []).length;
    const unmatched = (spec.meta || {}).unmatched_filter_columns;
    status.textContent = filters.length
      ? `${traces} traces · ${filters.length} filter${filters.length === 1 ? '' : 's'} applied`
      : `${traces} traces · unfiltered`;
    // A filter that reached no control is a real state and the API now reports
    // it, so say so rather than showing an unchanged figure as if it worked.
    if (unmatched && unmatched.length) {
      status.textContent += ` · ignored: ${unmatched.join(', ')}`;
    }

    section.querySelector('.pp-req').replaceChildren(
      requestDetails({
        url,
        params: {
          format: 'json',
          filters: filters.length ? JSON.stringify(filters) : '(none)',
          dc_id: entry.dc,
        },
        meta: spec.meta,
        etag: response.headers.get('etag'),
        label: 'How this figure was fetched',
      }),
    );
  } catch (error) {
    stage.innerHTML =
      `<div class="pp-error">An error occurred while loading the plot. ` +
      `<span>${escapeHtml(String(error))}</span></div>`;
    status.textContent = 'unavailable';
  } finally {
    section.classList.remove('is-loading');
  }
}

function redrawAll() {
  FIGURES.forEach((entry) => loadFigure(entry));
}

function setFilter(id, dc, filter) {
  state.filters = state.filters.filter((entry) => entry.id !== id);
  const value = filter && filter.value;
  const empty = value == null || (Array.isArray(value) && value.length === 0) || value === '';
  if (!empty) state.filters.push({ id, dc, filter });
  renderActiveFilters();
  redrawAll();
}

function renderActiveFilters() {
  const host = document.getElementById('active-filters');
  if (!host) return;
  if (!state.filters.length) {
    host.innerHTML = '<span class="pp-chip-empty">Showing all samples.</span>';
    return;
  }
  host.innerHTML = state.filters
    .map((entry) => {
      const value = Array.isArray(entry.filter.value)
        ? entry.filter.value.join(', ')
        : String(entry.filter.value);
      return `<span class="pp-chip"><b>${escapeHtml(entry.filter.column_name)}</b> ${escapeHtml(value)}</span>`;
    })
    .join('');
}

/* ---- the control deck ------------------------------------------------------
 *
 * Each entry in CONTROLS is matched against the manifest by column name. If the
 * dashboard has no control for that column the deck simply omits it, rather
 * than rendering a dead widget — a control that cannot filter anything is worse
 * than no control.
 */
function buildToggle(spec, control) {
  const cell = document.createElement('div');
  cell.className = 'pp-control';

  const options = (control.filter.options || {}).values || [];
  const id = `pp:${control.component_id}`;

  const head = document.createElement('div');
  head.className = 'pp-control-head';
  head.innerHTML = `<span>${escapeHtml(spec.label)}</span>`;

  const body = document.createElement('div');
  body.className = 'pp-control-body is-disabled';
  body.innerHTML = `<div class="pp-control-hint">${escapeHtml(spec.hint)}</div>`;

  const select = document.createElement('select');
  select.innerHTML = options
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join('');
  select.disabled = true;

  // The portal's switch: a checkbox styled as a track and knob. Off means "all",
  // on means "this one", which is exactly an empty vs single-value filter.
  const switchLabel = document.createElement('label');
  switchLabel.className = 'pp-switch';
  switchLabel.setAttribute('aria-label', spec.altLabel);
  const toggle = document.createElement('input');
  toggle.type = 'checkbox';
  const track = document.createElement('span');
  track.className = 'pp-switch-track';
  switchLabel.append(toggle, track);
  head.append(switchLabel, Object.assign(document.createElement('span'), {
    className: 'pp-control-alt',
    textContent: spec.altLabel,
  }));

  const push = () => {
    select.disabled = !toggle.checked;
    body.classList.toggle('is-disabled', !toggle.checked);
    setFilter(id, control.dc_id, {
      interactive_component_type: control.filter.interactive_component_type,
      column_name: control.filter.column_name,
      value: toggle.checked && select.value ? [select.value] : [],
    });
  };
  toggle.addEventListener('change', push);
  select.addEventListener('change', push);

  body.appendChild(select);
  cell.append(head, body);
  return cell;
}

function buildSelect(spec, control) {
  const cell = document.createElement('div');
  cell.className = 'pp-control';
  const options = (control.filter.options || {}).values || [];
  const id = `pp:${control.component_id}`;

  cell.innerHTML =
    `<div class="pp-control-head pp-control-head-plain"><span>${escapeHtml(spec.label)}</span></div>` +
    `<div class="pp-control-body"><div class="pp-control-hint">${escapeHtml(spec.hint)}</div></div>`;

  const select = document.createElement('select');
  select.innerHTML =
    '<option value="">All</option>' +
    options
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join('');
  select.addEventListener('change', () => {
    setFilter(id, control.dc_id, {
      interactive_component_type: control.filter.interactive_component_type,
      column_name: control.filter.column_name,
      value: select.value ? [select.value] : [],
    });
  });
  cell.querySelector('.pp-control-body').appendChild(select);
  return cell;
}

function buildDates(spec, control) {
  const cell = document.createElement('div');
  cell.className = 'pp-control';
  const options = control.filter.options || {};
  const id = `pp:${control.component_id}`;

  cell.innerHTML =
    `<div class="pp-control-head pp-control-head-plain"><span>${escapeHtml(spec.label)}</span></div>` +
    `<div class="pp-control-body"><div class="pp-control-hint">${escapeHtml(spec.hint)}</div></div>`;

  // The contract reports a DateRangePicker as kind:"range" with ISO-string
  // bounds, so a numeric slider would read them as NaN. Two date inputs send
  // the same [from, to] pair the picker would.
  const wrap = document.createElement('div');
  wrap.className = 'pp-dates';
  const isoDay = (value) => String(value).slice(0, 10);
  const from = document.createElement('input');
  const to = document.createElement('input');
  for (const [input, bound] of [[from, options.min], [to, options.max]]) {
    input.type = 'date';
    input.min = isoDay(options.min);
    input.max = isoDay(options.max);
    input.value = isoDay(bound);
  }
  const push = () =>
    setFilter(id, control.dc_id, {
      interactive_component_type: 'DateRangePicker',
      column_name: control.filter.column_name,
      value: [from.value, to.value],
    });
  from.addEventListener('change', push);
  to.addEventListener('change', push);
  wrap.append(from, to);
  cell.querySelector('.pp-control-body').appendChild(wrap);
  return cell;
}

function mountControls(manifest) {
  const host = document.getElementById('plot-filters');
  host.replaceChildren();

  const byColumn = new Map();
  for (const entry of manifest) {
    if (entry.component_type !== 'interactive') continue;
    if (!entry.filter || !entry.filter.column_name) continue;
    if (!byColumn.has(entry.filter.column_name)) byColumn.set(entry.filter.column_name, entry);
  }

  let mounted = 0;
  for (const spec of CONTROLS) {
    const control = byColumn.get(spec.column);
    if (!control) continue; // no control for that column: omit rather than fake
    const builder = { toggle: buildToggle, select: buildSelect, dates: buildDates }[spec.kind];
    host.appendChild(builder(spec, control));
    mounted += 1;
  }

  const url = `${state.apiBase}/export/dashboards/${DASHBOARD}/components?include_filter_options=true`;
  document.getElementById('plot-filters-req').replaceChildren(
    requestDetails({
      url,
      params: {
        include_filter_options: 'true',
        bound: `${mounted} of ${CONTROLS.length} portal controls`,
        note: 'each control is bound to a Depictio interactive component by column',
      },
      label: 'How these controls are bound to Depictio',
    }),
  );
}

/* ---- Depictio's own control, embedded --------------------------------------
 *
 * The other direction: rather than rebuilding the widget, frame Depictio's own
 * and listen for what it posts out. Both paths end at the same `filters=`
 * array, which is the point — a host chooses how much of Depictio's interface
 * it wants, not whether it can use the data.
 */
function mountEmbeddedControl(control) {
  const host = document.getElementById('embedded-control');
  if (!host || !control) return;

  const url = exportUrl(state.apiBase, {
    dashboard: DASHBOARD,
    component: control.component_id,
    format: 'html',
  });

  const frame = document.createElement('iframe');
  frame.src = url;
  frame.className = 'pp-control-frame';
  frame.title = 'Depictio interactive component';
  frame.loading = 'lazy';
  host.replaceChildren(frame);

  document.getElementById('embedded-control-req').replaceChildren(
    requestDetails({
      url,
      params: { format: 'html', note: 'the real Depictio widget, framed' },
      label: 'How this control is embedded',
    }),
  );

  window.addEventListener('message', (event) => {
    // Only trust messages from the API origin we asked for; without this any
    // framed page could push filters into this dashboard.
    if (state.apiBase && !state.apiBase.startsWith(event.origin)) return;
    const message = event.data;
    if (!message || message.source !== 'depictio-embed' || message.type !== 'filter') return;
    setFilter(`embed:${control.component_id}`, message.dcId || control.dc_id, message.filter);
  });
}

async function init() {
  const site = await (await fetch(API_HINT)).json();
  state.apiBase = site.apiBase;
  mountSharedNav(site.pages, { backHref: '/', backLabel: 'index' });

  const manifest = await (
    await fetch(
      `${state.apiBase}/export/dashboards/${DASHBOARD}/components?include_filter_options=true`,
    )
  ).json();
  state.controls = manifest;

  mountControls(manifest);

  // Embed the one control the rebuilt deck does not cover, so the two
  // approaches complement rather than fight over a column.
  const covered = new Set(CONTROLS.map((spec) => spec.column));
  const spare = manifest.find(
    (entry) =>
      entry.component_type === 'interactive' &&
      entry.filter &&
      entry.filter.column_name &&
      !covered.has(entry.filter.column_name),
  );
  mountEmbeddedControl(spare);

  renderActiveFilters();
  redrawAll();
}

init().catch((err) => {
  const banner = document.getElementById('active-filters');
  if (banner) banner.textContent = `failed: ${err.message}`;
});
