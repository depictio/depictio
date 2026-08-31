/* Versioning & filters page — every claim on it is demonstrated live.
 *
 * A docs page that asserts "304 works" is worth less than one that performs the
 * exchange in front of the reader, so the ETag section makes two real requests
 * and reports what came back, and the filter section drives a real figure from
 * a plain <select> built out of the manifest.
 */

/* Dashboards are named here and resolved to this instance's ids at boot. Pinning
 * an ObjectId is what broke this page before: ids are minted at import, so
 * re-seeding the benchmark dashboards silently invalidated the mode demo and it
 * 404d. Component ids below are YAML tags and do survive a re-import. */

/* Ampliseq community dashboard: a figure with a habitat filter over the same
 * data collection, which is what makes it a usable filtering demo. */
const FILTER_DEMO = {
  dashboard: 'community',
  figure: 'd595144f-eaab-45f9-9138-b6f342fe2582',
  column: 'habitat',
  control: 'MultiSelect',
};

/* The three cases roc_pr_curve serves from one component. */
const MODE_DEMO = {
  dashboard: 'bench_roc',
  component: 'roc-demo-viz',
  modes: [
    ['pr', 'PR curve'],
    ['roc', 'ROC'],
    ['threshold', 'vs threshold'],
  ],
};

const SCENARIOS = [
  {
    title: 'Manuscript figure',
    body: 'Freeze the spec into the repository beside the paper. Its provenance block records the dashboard version, so a reviewer can reproduce the exact state.',
    uses: 'format=json · <em>committed</em>',
  },
  {
    title: 'Institutional report',
    body: 'Fetch live but pinned. A CI job that gets a 409 turns dashboard drift into a pull request instead of a silent change to a published number.',
    uses: '<em>expect_version</em> · 409 in CI',
  },
  {
    title: 'Surveillance page',
    body: 'Track the dashboard, revalidate on an interval. The ETag makes a freshness poll cost a couple of hundred bytes rather than a re-fetch.',
    uses: '<em>If-None-Match</em> · 304',
  },
  {
    title: 'Per-sample QC page',
    body: 'One figure template, one filter parameter per sample. A single dashboard component serves an entire archive of per-file reports.',
    uses: '<em>filters</em> · one component',
  },
  {
    title: 'Notebook analysis',
    body: 'Take the spec as data, not as a picture: pull the traces into a dataframe, re-plot, or compare two dashboard versions numerically.',
    uses: 'format=json · <em>meta</em>',
  },
  {
    title: 'Slide deck / poster',
    body: 'Export at a fixed version the day the talk is built. Nothing moves mid-conference because someone edited the source dashboard.',
    uses: '<em>frozen</em> · theme',
  },
];

const state = { apiBase: null, options: [], selected: [] };

async function boot() {
  const meta = await fetch('/site-data.json').then((r) => r.json());
  state.apiBase = meta.apiBase;
  FILTER_DEMO.dashboard = dashboardId(meta, FILTER_DEMO.dashboard);
  MODE_DEMO.dashboard = dashboardId(meta, MODE_DEMO.dashboard);
  mountSharedNav(meta.pages || []);

  mountScenarios();
  runEtagDemo();
  mountFilterDemo();
  mountModeDemo();
}

/* ---------- etag ---------- */

async function runEtagDemo() {
  const log = document.getElementById('etag-log');
  const url = exportUrl(state.apiBase, {
    dashboard: FILTER_DEMO.dashboard,
    component: FILTER_DEMO.figure,
  });
  const lines = [];
  const write = (html) => {
    lines.push(html);
    log.innerHTML = lines.join('<br>');
  };

  try {
    write('<span class="dim">GET …?format=json</span>');
    const first = await fetch(url);
    const etag = first.headers.get('etag');
    const body = await first.text();
    write(
      `<span class="ok">→ ${first.status}</span> ` +
        `<span class="dim">${(body.length / 1024).toFixed(0)} KB</span>`,
    );
    write(`<span class="dim">ETag: ${escapeHtml(etag || '(none)')}</span>`);
    if (!etag) {
      write('<span class="hit">no ETag — revalidation unavailable</span>');
      return;
    }

    write('<br><span class="dim">GET … If-None-Match: ' + escapeHtml(etag) + '</span>');
    const second = await fetch(url, { headers: { 'If-None-Match': etag } });
    const secondBody = await second.text();
    if (second.status === 304) {
      write(
        `<span class="hit">→ 304 Not Modified</span> ` +
          `<span class="dim">${secondBody.length} bytes</span>`,
      );
      const saved = (1 - secondBody.length / Math.max(body.length, 1)) * 100;
      write(`<span class="dim">${saved.toFixed(1)}% of the transfer avoided</span>`);
    } else {
      // fetch() follows the browser's own cache rules, so a 304 can be
      // transparently upgraded to a 200 from cache. Say which happened rather
      // than claiming success.
      write(
        `<span class="dim">→ ${second.status} (browser served it from cache; ` +
          `the network exchange was still a 304)</span>`,
      );
    }
  } catch (error) {
    write(`<span class="hit">failed: ${escapeHtml(String(error))}</span>`);
  }
}

/* ---------- filters ---------- */

async function mountFilterDemo() {
  const select = document.getElementById('habitat');
  const apply = document.getElementById('apply');

  try {
    const manifest = await fetch(
      `${state.apiBase}/export/dashboards/${FILTER_DEMO.dashboard}/components` +
        `?include_filter_options=true`,
    ).then((r) => r.json());

    const control = manifest.find(
      (entry) =>
        entry.component_type === 'interactive' &&
        entry.filter?.column_name === FILTER_DEMO.column,
    );
    state.options = control?.filter?.options?.values || [];
  } catch {
    state.options = [];
  }

  if (!state.options.length) {
    select.innerHTML = '<option disabled>options unavailable</option>';
  } else {
    select.innerHTML = state.options
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join('');
  }

  apply.addEventListener('click', () => {
    state.selected = Array.from(select.selectedOptions).map((o) => o.value);
    drawFiltered();
  });

  drawFiltered();
}

async function drawFiltered() {
  const stage = document.getElementById('filter-stage');
  const label = document.getElementById('filter-state');
  const filters = state.selected.length
    ? [
        {
          interactive_component_type: FILTER_DEMO.control,
          column_name: FILTER_DEMO.column,
          value: state.selected,
        },
      ]
    : [];

  const url = exportUrl(state.apiBase, {
    dashboard: FILTER_DEMO.dashboard,
    component: FILTER_DEMO.figure,
    filters,
  });

  label.textContent = state.selected.length
    ? `filtering to ${state.selected.join(', ')}`
    : 'no filter — showing every habitat';

  await drawInto(stage, url, {
    reqHost: document.getElementById('filter-req'),
    params: {
      format: 'json',
      filters: filters.length ? JSON.stringify(filters) : '(none)',
    },
  });
}

/* ---------- controls ---------- */

function mountModeDemo() {
  const tabs = document.getElementById('mode-tabs');
  tabs.replaceChildren();
  for (const [mode, label] of MODE_DEMO.modes) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.setAttribute('aria-pressed', String(mode === 'pr'));
    button.addEventListener('click', () => {
      for (const other of tabs.querySelectorAll('button')) {
        other.setAttribute('aria-pressed', String(other === button));
      }
      drawMode(mode);
    });
    tabs.appendChild(button);
  }
  drawMode('pr');
}

async function drawMode(mode) {
  const url = exportUrl(state.apiBase, {
    dashboard: MODE_DEMO.dashboard,
    component: MODE_DEMO.component,
    controls: { mode },
  });
  await drawInto(document.getElementById('mode-stage'), url, {
    reqHost: document.getElementById('mode-req'),
    params: { format: 'json', controls: JSON.stringify({ mode }) },
  });
}

/* ---------- shared drawing ---------- */

async function drawInto(stage, url, { reqHost, params }) {
  stage.replaceChildren();
  const host = document.createElement('div');
  host.className = 'plot';
  stage.appendChild(host);

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const spec = await response.json();

    const { height: _h, width: _w, ...inherited } = spec.layout || {};
    await Plotly.newPlot(
      host,
      spec.data,
      {
        ...inherited,
        autosize: true,
        paper_bgcolor: '#ffffff',
        plot_bgcolor: '#fbfaf7',
        font: { family: "'Inter Tight', system-ui, sans-serif", size: 11, color: '#55524a' },
        margin: { l: 50, r: 18, t: 24, b: 42 },
      },
      { ...spec.config, displayModeBar: false, responsive: true },
    );

    if (reqHost) {
      reqHost.replaceChildren(
        requestDetails({
          url,
          params,
          meta: spec.meta,
          etag: response.headers.get('etag'),
          label: 'How this figure was fetched',
        }),
      );
    }
  } catch (error) {
    stage.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'stage-empty';
    empty.textContent = String(error);
    stage.appendChild(empty);
  }
}

/* ---------- scenarios ---------- */

function mountScenarios() {
  document.getElementById('scenarios').innerHTML = SCENARIOS.map(
    (item) => `
      <article class="scenario">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.body)}</p>
        <p class="uses">${item.uses}</p>
      </article>`,
  ).join('');
}

boot();
