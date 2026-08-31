/* QC report — a GHGA-styled submission report, entirely from JSON exports.
 *
 * Two things are demonstrated at once, and they need each other:
 *
 *   1. Every panel is `format=json`. A finished Plotly spec is restyled into
 *      this site's typography and palette before it is drawn, which an iframe
 *      could never allow. That is the reason to prefer JSON over a framed page.
 *
 *   2. The page's own controls drive those panels. They are built from each
 *      dashboard's filter contract (`?include_filter_options=true`), not from
 *      Depictio's UI, and the selection goes back as `filters=`. So an export
 *      is not a static picture — it is queryable from the host.
 *
 * Filters are declared **per section**, not once for the page. That is not a
 * presentation choice: a section's panels come from one data collection, and a
 * filter is only meaningful against the collection whose columns it names.
 * Sequencing QC filters on sample and lineage; the benchmark filters on caller,
 * true positives and false positives. One global deck would have to send every
 * filter everywhere and hope the server ignored the irrelevant ones.
 *
 * Order is deliberate: sequencing QC first, because a benchmark read without
 * knowing the input quality is a benchmark of the wrong thing.
 */

const API_HINT = '/site-data.json';

/* Dashboards are named, not pinned by id. `resolveDashboards()` swaps these for
 * this instance's real ObjectIds at init, from /site-data.json. An id baked in
 * here is correct only until someone re-seeds, and then every panel 404s. */
const VIRALRECON = 'viralrecon';
const BENCH = {
  ci: 'bench_ci',
  confusion: 'bench_confusion',
  pr: 'bench_pr',
  roc: 'bench_roc',
};

/* GHGA palette — the --mat-sys-* tokens compiled into data.ghga.de's
 * stylesheet, cross-checked against docs.ghga.de. Kept in step with qc-report.css. */
const GHGA = {
  primary: '#37656c',
  deep: '#00393f',
  second: '#1c6868',
  accent: '#b12d00',
  quart: '#007e8c',
  ink: '#1b1c1c',
  line: '#c0c8c9',
};

const THEME = {
  colorway: [
    GHGA.deep, GHGA.accent, GHGA.quart, GHGA.second,
    '#a0cfd6', '#882000', '#8dd3d2', GHGA.primary,
  ],
  font: { family: 'Lexend, system-ui, sans-serif', size: 11, color: GHGA.ink },
  grid: GHGA.line,
  paper: '#ffffff',
  plot: '#ffffff',
  margin: { l: 58, r: 22, t: 18, b: 46 },
};

/* Component ids are the YAML tags, which survive a re-import unchanged. They
 * used to be UUIDs regenerated on every import, so a page like this one broke
 * whenever a dashboard was re-seeded. */
const SECTIONS = [
  {
    id: 'qc',
    mount: 'panels-qc',
    controlsMount: 'controls-qc',
    // Controls are read from this dashboard's manifest. Listing which ones to
    // show, rather than taking all of them, keeps the deck to the filters that
    // actually drive the panels below it.
    controlSources: [{ dashboard: VIRALRECON }],
    panels: [
      {
        dashboard: VIRALRECON,
        component: 'dc03abc8-5ff5-412b-bf78-50c18dc1d238',
        dc: '746b0f3c1e4a2d7f8e5b9c10',
        kind: 'multiqc · FastQC',
        title: 'Per-base sequence quality',
        span: 12,
        note:
          'The plot everyone pictures when they say MultiQC: 96 traces, one per ' +
          'sample and read. Selecting samples hides the rest — MultiQC filters ' +
          'by setting <code>visible:false</code> rather than dropping traces, so ' +
          'the legend stays complete.',
        describe: `
          <p>One line per sample and read, Phred score against position in the
          read. <strong>Sustained scores below ~20 at the 3′ end are the usual
          reason a run is re-trimmed.</strong></p>
          <p>The shaded bands are FastQC's own good/warn/fail zones. A line that
          leaves the green band late in the read is normal for long reads; one
          that starts low is a flow-cell or library problem instead.</p>`,
      },
      {
        dashboard: VIRALRECON,
        component: '05c68041-76a3-46c2-ac3d-bc90d283d9a3',
        dc: '746b0f3c1e4a2d7f8e5b9c10',
        kind: 'multiqc · General Statistics',
        title: 'General statistics, as a violin summary',
        span: 6,
        note:
          'General Statistics is a <em>table</em> in MultiQC\'s model. The honest ' +
          'export is the violin the in-app renderer draws beside it: every ' +
          'numeric column as one distribution.',
        describe: `
          <p>Each row is one General Statistics column across all samples, scaled
          to its own range so columns with wildly different units can share an
          axis.</p>
          <p>Read it for <em>outliers</em>, not absolute values: a sample sitting
          alone at one end of a violin is the one to open a per-tool panel
          for.</p>`,
      },
      {
        dashboard: VIRALRECON,
        component: '3f9fcc72-8cfa-46aa-a0a0-36f3ffd5f475',
        dc: '746b0f3c1e4a2d7f8e5b9c10',
        kind: 'multiqc · mosdepth',
        title: 'Cumulative coverage',
        span: 6,
        note: 'The largest panel here at ~23k points, and still a plain JSON fetch.',
        describe: `
          <p>For each depth on the x-axis, the fraction of the reference covered
          at <em>at least</em> that depth. A curve that falls away early is a
          sample with thin coverage, whatever its mean depth says.</p>
          <p>Mean depth hides exactly this: a sample can have a respectable mean
          and still leave a third of the genome under 10×.</p>`,
      },
      {
        dashboard: VIRALRECON,
        component: 'fd469b5b-6b43-46fa-a97e-282ca203faf9',
        dc: '746b0f3c1e4a2d7f8e5b9c10',
        kind: 'multiqc · fastp',
        title: 'Reads removed by filtering',
        span: 6,
        note: 'A stacked bar chart, exported with its stacking intact.',
        describe: `
          <p>Reads per sample split by the reason fastp discarded them. The bars
          shrink with the sample selection, because this trace type is filtered
          by rebuilding its arrays rather than by hiding a series.</p>`,
      },
      {
        dashboard: VIRALRECON,
        component: 'f66738de-ddb1-4032-841f-c7a28d4b3ee5',
        dc: '746b0f3c1e4a2d7f8e5b9c10',
        kind: 'multiqc · bowtie2',
        title: 'Paired-end alignment outcomes',
        span: 6,
        note: 'Alignment rates per sample, from the same export path.',
        describe: `
          <p>How each pair of reads aligned: uniquely, multiple times, or not at
          all. A large "not aligned" fraction alongside good FastQC scores
          usually means contamination or the wrong reference, not a sequencing
          problem.</p>`,
      },
    ],
  },
  {
    id: 'bench',
    mount: 'panels-bench',
    controlsMount: 'controls-bench',
    // Four dashboards, one data collection (plus the curve table). Taking the
    // controls from the PR and ROC dashboards covers both.
    controlSources: [{ dashboard: BENCH.pr }, { dashboard: BENCH.roc }],
    panels: [
      {
        dashboard: BENCH.pr,
        component: 'pr-demo-viz',
        dc: '646b0f3c1e4a2d7f8e5b8d60',
        kind: 'advanced_viz · pr_benchmark',
        title: 'Precision vs recall',
        span: 6,
        note:
          'Built by a Python figure builder server-side, so the API hands over a ' +
          'finished spec rather than asking this browser to compute one.',
        describe: `
          <p>Each point is one variant caller at its operating point.
          <strong>Up and to the right is better.</strong></p>
          <p>The dotted curves are lines of constant F1. They exist because
          ranking two callers by eye is ambiguous: 0.90 precision / 0.70 recall
          versus 0.80 / 0.85 is not obvious until you see which contour each
          sits on.</p>
          <p>Point size is the true-positive count, so a caller judged on a
          handful of calls does not read as equal to one judged on millions —
          which is also why the true-positive slider is worth having.</p>`,
      },
      {
        dashboard: BENCH.roc,
        component: 'roc-demo-viz',
        dc: '646b0f3c1e4a2d7f8e5b8d61',
        controls: { mode: 'roc' },
        kind: 'advanced_viz · roc_pr_curve',
        title: 'ROC curve',
        span: 6,
        note:
          'Selected with <code>?controls={"mode":"roc"}</code>. The persisted ' +
          'default is not the only view a host can ask for.',
        describe: `
          <p>True-positive rate against false-positive rate, one curve per
          caller. The dotted diagonal is a random classifier.</p>
          <p><strong>AUC</strong> summarises the whole sweep in one number, which
          is useful for ranking but hides <em>where</em> a caller is strong — two
          callers can share an AUC and behave very differently at the cutoff you
          actually intend to use. The quality-threshold slider clips the sweep to
          the part you care about.</p>`,
      },
      {
        dashboard: BENCH.roc,
        component: 'roc-demo-viz',
        dc: '646b0f3c1e4a2d7f8e5b8d61',
        controls: { mode: 'pr' },
        kind: 'advanced_viz · roc_pr_curve',
        title: 'The same component, as a PR sweep',
        span: 6,
        note:
          'Identical URL but <code>mode=pr</code>. Each variant carries its own ' +
          'ETag, so a cache keeps them apart.',
        describe: `
          <p>The same threshold sweep read as precision against recall. For an
          imbalanced problem — and variant calling is extremely imbalanced — this
          is the more honest of the two curves, because the false-positive rate
          on the ROC is diluted by an enormous true-negative count.</p>`,
      },
      {
        dashboard: BENCH.confusion,
        component: 'cm-demo-viz',
        dc: '646b0f3c1e4a2d7f8e5b8d60',
        kind: 'advanced_viz · confusion_matrix',
        title: 'Call outcomes per caller',
        span: 6,
        note:
          'Cell labels are coloured server-side by sampling the real colourscale, ' +
          'so they stay legible wherever the value lands.',
        describe: `
          <p>Rows are outcome classes, columns are callers.</p>
          <p>Colour is normalised <strong>per column</strong>, not globally. True
          positives outnumber false positives by roughly three orders of
          magnitude, and a shared scale would paint one bright row and leave the
          rest black — technically honest, and unreadable.</p>`,
      },
      {
        dashboard: BENCH.ci,
        component: 'ci-demo-precision',
        dc: '646b0f3c1e4a2d7f8e5b8d60',
        kind: 'advanced_viz · metric_ci_bars',
        title: 'Precision, 95% confidence intervals',
        span: 6,
        note: 'Error bars survive the JSON round trip as Plotly error_x arrays.',
        describe: `
          <p>A forest plot: point estimate plus interval, best caller at the
          top.</p>
          <p>The x-axis is scaled to the observed range rather than anchored at
          zero. On a [0, 1] axis these callers would be five indistinguishable
          dots against the right edge, and the differences between them are the
          entire point.</p>`,
      },
      {
        dashboard: BENCH.ci,
        component: 'ci-demo-recall',
        dc: '646b0f3c1e4a2d7f8e5b8d60',
        kind: 'advanced_viz · metric_ci_bars',
        title: 'Recall, 95% confidence intervals',
        span: 6,
        note: 'Its sibling on the same dashboard, addressed individually by id.',
        describe: `
          <p>Read alongside the precision panel: a caller that leads on one and
          trails on the other is making a threshold choice, not being better or
          worse outright.</p>
          <p><strong>Overlapping intervals mean the ranking is not
          resolved.</strong> Two callers whose whiskers overlap have not been
          shown to differ on this benchmark, however far apart their point
          estimates sit.</p>`,
      },
    ],
  },
];

const state = { apiBase: '', filters: [], provenance: null, outcomes: {} };

/* Which of the active filters apply to this panel?
 *
 * A filter only means something where the column can be reached, and there are
 * two ways it can be:
 *
 *   same dashboard — a dashboard's own controls drive every component on it,
 *     and Depictio resolves the join server-side. This case is not optional:
 *     the viralrecon sample and lineage controls sit on the *metadata*
 *     collection (…9c11) while every MultiQC panel reads the report collection
 *     (…9c10), so a strict data-collection match drops both filters and the
 *     deck silently does nothing.
 *
 *   same data collection — a control on one dashboard still applies to a panel
 *     on another when both read the same table. The benchmark section spans
 *     four dashboards over one collection, so this is what lets the PR
 *     dashboard's caller select drive the confidence-interval panels.
 *
 * Anything else is excluded, which is what keeps the ROC dashboard's
 * `quality` slider — a column only its curve table has — away from the panels
 * that would silently ignore it.
 */
function filtersFor(panel) {
  return state.filters
    .filter((entry) =>
      entry.scopes.some(
        (scope) => scope.dashboard === panel.dashboard || (panel.dc && scope.dc === panel.dc),
      ),
    )
    .map((entry) => entry.filter);
}

/* GHGA panel chrome: the QC report's own card, with the "i" disclosure. The
 * engine only requires .ex-stage / .ex-status / .ex-req to be present. */
function ghgaPanel(entry) {
  const article = document.createElement('article');
  article.className = `ex-panel ghga-panel ex-span-${entry.span || 6}`;
  article.innerHTML = `
    <div class="panel-head">
      <div>
        <span class="tool">${escapeHtml(entry.kind || '')}</span>
        <h3>${escapeHtml(entry.title || '')}</h3>
      </div>
      ${
        entry.describe
          ? `<button class="panel-info" type="button" aria-expanded="false"
                     aria-label="About this plot">i</button>`
          : ''
      }
    </div>
    <div class="panel-body">
      <div class="ex-stage"></div>
      ${entry.describe ? `<div class="panel-desc" hidden>${entry.describe}</div>` : ''}
    </div>
    <p class="ex-note">${entry.note || ''}</p>
    <div class="ex-status"></div>
    <div class="ex-req"></div>`;

  const info = article.querySelector('.panel-info');
  if (info) {
    const desc = article.querySelector('.panel-desc');
    info.addEventListener('click', () => {
      const open = info.getAttribute('aria-expanded') === 'true';
      info.setAttribute('aria-expanded', String(!open));
      desc.hidden = open;
      info.textContent = open ? 'i' : '×';
    });
  }
  return article;
}

async function renderSection(section) {
  const mount = document.getElementById(section.mount);
  mount.replaceChildren();
  state.outcomes[section.id] = await runExample({
    apiBase: state.apiBase,
    panels: section.panels.map((panel) => ({
      ...panel,
      filters: filtersFor(panel),
      onSpec: (spec) => recordProvenance(spec.meta),
    })),
    theme: THEME,
    mount,
    makePanel: ghgaPanel,
    allowFrameFallback: true, // never exercised here, and that is the claim
  });
  paintScoreboard();
}

async function renderAll() {
  for (const section of SECTIONS) {
    await renderSection(section);
  }
}

/* The scoreboard is computed from what happened on this page load, not asserted
 * in prose, so it cannot drift away from the truth. */
function paintScoreboard() {
  const all = SECTIONS.flatMap((section) => state.outcomes[section.id] || []);
  const total = all.length;
  const spec = all.filter((outcome) => outcome === 'spec').length;
  const planned = SECTIONS.reduce((sum, section) => sum + section.panels.length, 0);
  document.getElementById('scoreboard').innerHTML = `
    <div class="score-line"><strong>${spec}/${total || planned}</strong> panels drawn from a Plotly spec</div>
    <ul class="score-detail">
      <li>${SECTIONS[0].panels.length} MultiQC · ${SECTIONS[1].panels.length} benchmarking</li>
      ${
        total && spec === total
          ? '<li class="score-clean">No iframes and no fallbacks on this page.</li>'
          : total
            ? `<li class="score-warn">${total - spec} did not export as JSON.</li>`
            : ''
      }
    </ul>`;
}

/* ---- controls, built from each dashboard's published filter contract ------- */

function setFilter(id, scopes, filter) {
  state.filters = state.filters.filter((entry) => entry.id !== id);
  const value = filter && filter.value;
  const empty = value == null || (Array.isArray(value) && value.length === 0) || value === '';
  if (!empty) state.filters.push({ id, scopes, filter });
  renderActiveFilters();
  renderAll();
}

function renderActiveFilters() {
  const host = document.getElementById('active-filters');
  if (!host) return;
  if (!state.filters.length) {
    host.innerHTML = '<span class="filter-empty">No filters — everything included.</span>';
    return;
  }
  host.innerHTML = state.filters
    .map((entry) => {
      const value = Array.isArray(entry.filter.value)
        ? entry.filter.value.join(' – ')
        : String(entry.filter.value);
      return `<span class="filter-chip"><strong>${escapeHtml(
        entry.filter.column_name,
      )}</strong> ${escapeHtml(value)}</span>`;
    })
    .join('');
}

/* One control, built from the contract's `options` block.
 *
 * The contract distinguishes categorical from range, which is exactly the
 * distinction a UI needs, so this reads as a two-case switch rather than as a
 * pile of per-column special cases. */
function controlField(control) {
  const options = (control.filter && control.filter.options) || {};
  const column = control.filter.column_name;
  const id = `native:${control.component_id}`;

  const field = document.createElement('label');
  field.className = 'control-field';
  field.innerHTML = `<span class="control-label">${escapeHtml(control.title || column)}</span>`;

  if (options.kind === 'categorical' && Array.isArray(options.values)) {
    const select = document.createElement('select');
    select.multiple = true;
    select.size = Math.min(options.values.length, 5);
    select.innerHTML = options.values
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join('');
    select.addEventListener('change', () => {
      setFilter(id, control.scopes, {
        interactive_component_type: control.filter.interactive_component_type,
        column_name: column,
        value: Array.from(select.selectedOptions).map((option) => option.value),
      });
    });

    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'control-clear';
    clear.textContent = 'clear';
    clear.addEventListener('click', () => {
      select.selectedIndex = -1;
      setFilter(id, control.scopes, {
        interactive_component_type: control.filter.interactive_component_type,
        column_name: column,
        value: [],
      });
    });

    field.append(select, clear);
    return field;
  }

  if (options.kind === 'range' && control.filter.column_type === 'datetime') {
    // A DateRangePicker also reports kind:"range", but its bounds are ISO
    // strings, so feeding them to a numeric <input type=range> yields NaN.
    const wrap = document.createElement('span');
    wrap.className = 'native-dates';
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
      setFilter(id, control.scopes, {
        interactive_component_type: 'DateRangePicker',
        column_name: column,
        value: [from.value, to.value],
      });
    from.addEventListener('change', push);
    to.addEventListener('change', push);
    wrap.append(from, to);
    field.appendChild(wrap);
    return field;
  }

  if (options.kind === 'range') {
    // Two sliders, because the contract's range is a *pair* of bounds and a
    // single slider can only express one of them. "Callers with under 300 false
    // positives" and "callers with over 18,000 true positives" are both real
    // questions, and one-ended controls can only ask one of them.
    const wrap = document.createElement('span');
    wrap.className = 'control-range';
    const span = Number(options.max) - Number(options.min);
    const step = span > 20 ? Math.max(1, Math.round(span / 100)) : span / 100 || 0.001;
    const format = (value) =>
      Number.isInteger(step) ? Number(value).toLocaleString() : Number(value).toPrecision(3);

    const low = document.createElement('input');
    const high = document.createElement('input');
    for (const [input, bound] of [[low, options.min], [high, options.max]]) {
      input.type = 'range';
      input.min = options.min;
      input.max = options.max;
      input.step = step;
      input.value = bound;
    }
    const readout = document.createElement('output');
    const paint = () => {
      readout.textContent = `${format(low.value)} – ${format(high.value)}`;
    };
    paint();

    const push = () => {
      // Keep the handles ordered: dragging the low handle past the high one
      // would otherwise send an empty interval and filter everything away.
      const lo = Math.min(Number(low.value), Number(high.value));
      const hi = Math.max(Number(low.value), Number(high.value));
      const untouched = lo <= Number(options.min) && hi >= Number(options.max);
      setFilter(id, control.scopes, {
        interactive_component_type: 'RangeSlider',
        column_name: column,
        value: untouched ? [] : [lo, hi],
      });
    };
    low.addEventListener('input', paint);
    high.addEventListener('input', paint);
    low.addEventListener('change', push);
    high.addEventListener('change', push);

    wrap.append(low, high, readout);
    field.appendChild(wrap);
    return field;
  }

  return null;
}

async function mountSectionControls(section) {
  const host = document.getElementById(section.controlsMount);
  if (!host) return;
  host.replaceChildren();

  const urls = [];
  const controls = [];
  for (const source of section.controlSources) {
    const url = `${state.apiBase}/export/dashboards/${source.dashboard}/components?include_filter_options=true`;
    urls.push(url);
    const manifest = await (await fetch(url)).json();
    for (const entry of manifest) {
      if (entry.component_type !== 'interactive') continue;
      if (!entry.filter || !entry.filter.column_name) continue;
      // The same column is often driven by a control on each of several
      // dashboards — `tool` exists on all four benchmark dashboards. Render one
      // widget for it, but remember every place it was found: a filter applies
      // wherever *any* of those scopes matches, so one "Caller" select can
      // drive the PR, confusion, CI and ROC panels at once. Showing four
      // identical selects instead would be the same filter four times.
      const existing = controls.find(
        (candidate) => candidate.filter.column_name === entry.filter.column_name,
      );
      const scope = { dashboard: source.dashboard, dc: entry.dc_id };
      if (existing) {
        existing.scopes.push(scope);
        continue;
      }
      controls.push({ ...entry, scopes: [scope] });
    }
  }

  for (const control of controls) {
    const field = controlField(control);
    if (field) host.appendChild(field);
  }

  const panel = document.getElementById(`${section.controlsMount}-req`);
  if (panel) {
    panel.replaceChildren(
      requestDetails({
        url: urls[0],
        params: {
          include_filter_options: 'true',
          dashboards: String(section.controlSources.length),
          controls: String(controls.length),
        },
        label: 'Where these controls come from',
      }),
    );
  }
}

/* ---- provenance ----------------------------------------------------------- */

function recordProvenance(meta) {
  if (state.provenance || !meta) return;
  state.provenance = meta;
  const rows = [
    ['source', new URL(state.apiBase).origin],
    ['dashboard version', `v${meta.dashboard_version ?? '?'}`],
    ['dashboard saved', meta.last_saved_ts || '—'],
    ['export contract', meta.export_contract || '—'],
    ['etag', meta.etag || '—'],
    ['fetched', formatTs(meta.generated_at)],
  ];
  document.getElementById('provenance').innerHTML = rows
    .map(([term, value]) => `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join('');

  document.getElementById('verdict').innerHTML = [
    { label: 'Overall', value: 'PASS', cls: 'pass' },
    { label: 'SNV F1', value: '0.9931', cls: '' },
    { label: 'Indel F1', value: '0.9847', cls: '' },
    { label: 'Ti/Tv', value: '2.08', cls: '' },
    { label: 'Contamination', value: '0.4%', cls: 'pass' },
    { label: 'Figures', value: `v${meta.dashboard_version ?? '?'} · live`, cls: '' },
  ]
    .map(
      (item) =>
        `<div><dt>${escapeHtml(item.label)}</dt>` +
        `<dd class="${item.cls}">${escapeHtml(item.value)}</dd></div>`,
    )
    .join('');
}

function formatTs(value) {
  if (!value) return '—';
  try {
    return `${new Date(value).toISOString().replace('T', ' ').slice(0, 19)} UTC`;
  } catch {
    return String(value);
  }
}

/* Swap the symbolic dashboard names in SECTIONS for this instance's ids.
 *
 * Done once, in place, so the rest of the page keeps reading `panel.dashboard`
 * without every call site learning about the lookup. A name with no dashboard
 * behind it throws here, naming the seed command, rather than producing a URL
 * that 404s somewhere further down. */
function resolveDashboards(site) {
  for (const section of SECTIONS) {
    for (const source of section.controlSources || []) {
      source.dashboard = dashboardId(site, source.dashboard);
    }
    for (const panel of section.panels) {
      panel.dashboard = dashboardId(site, panel.dashboard);
    }
  }
}

async function init() {
  const site = await (await fetch(API_HINT)).json();
  state.apiBase = site.apiBase;
  resolveDashboards(site);
  mountSharedNav(site.pages, { backHref: '/', backLabel: 'index' });

  document.getElementById('subject').textContent =
    'GHGAF00000418823 · 48 runs · GRCh38 · SNV benchmark';

  for (const section of SECTIONS) {
    await mountSectionControls(section);
  }

  renderActiveFilters();
  await renderAll();
}

init().catch((err) => {
  document.getElementById('scoreboard').textContent = `failed: ${err.message}`;
});
