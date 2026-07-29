/* Filter self-test — proves the exports actually respond to the filters the
 * showcase pages send.
 *
 * This exists because a broken filter is invisible from the outside: the
 * response is a 200, the figure is intact, and `filter_applied` is true because
 * it was computed from the request rather than from what happened. Both of the
 * filter bugs found in this project looked exactly like success. The only
 * reliable check is to fetch twice and compare.
 *
 * It runs in the browser rather than as a Python probe because the *page's*
 * scoping rule is half of what can be wrong — the QC deck's filters were being
 * dropped client-side while the API was filtering correctly all along. The
 * cases below use `filtersFor`-shaped scopes so a page-side regression shows up
 * here too.
 */

const API_HINT = '/site-data.json';

const VIRALRECON = '746b0f3c1e4a2d7f8e5b9ca2';
const BENCH_PR = '6a6a671b2b176f56bdcf5f2e';
const BENCH_CI = '6a6a671b2b176f56bdcf5f2a';
const BENCH_CM = '6a6a671b2b176f56bdcf5f2c';
const BENCH_ROC = '6a6a671b2b176f56bdcf5f30';

const SAMPLES = ['SAMPLE_01', 'SAMPLE_02', 'SAMPLE_03'];
const CALLERS = ['deepvariant', 'strelka2'];

const multi = (column, value) => ({
  interactive_component_type: 'MultiSelect',
  column_name: column,
  value,
});
const range = (column, value) => ({
  interactive_component_type: 'RangeSlider',
  column_name: column,
  value,
});

const CASES = [
  // QC section: the controls live on the metadata collection while the panels
  // read the report collection, which is exactly the case that was silently
  // dropping filters.
  { name: 'FastQC', dashboard: VIRALRECON, component: 'dc03abc8-5ff5-412b-bf78-50c18dc1d238',
    filter: multi('sample', SAMPLES) },
  { name: 'FastQC', dashboard: VIRALRECON, component: 'dc03abc8-5ff5-412b-bf78-50c18dc1d238',
    filter: multi('lineage', ['B.1.1.7']) },
  { name: 'General statistics', dashboard: VIRALRECON, component: '05c68041-76a3-46c2-ac3d-bc90d283d9a3',
    filter: multi('sample', SAMPLES) },
  { name: 'mosdepth', dashboard: VIRALRECON, component: '3f9fcc72-8cfa-46aa-a0a0-36f3ffd5f475',
    filter: multi('sample', SAMPLES) },
  { name: 'fastp', dashboard: VIRALRECON, component: 'fd469b5b-6b43-46fa-a97e-282ca203faf9',
    filter: multi('sample', SAMPLES) },
  { name: 'bowtie2', dashboard: VIRALRECON, component: 'f66738de-ddb1-4032-841f-c7a28d4b3ee5',
    filter: multi('lineage', ['B.1.1.7']) },

  // Benchmark section: columns that had no dashboard control until one was
  // added, so a host had no way to discover them.
  { name: 'PR benchmark', dashboard: BENCH_PR, component: 'pr-demo-viz',
    filter: multi('tool', CALLERS) },
  { name: 'PR benchmark', dashboard: BENCH_PR, component: 'pr-demo-viz',
    filter: range('fp', [95, 300]) },
  { name: 'PR benchmark', dashboard: BENCH_PR, component: 'pr-demo-viz',
    filter: range('tp', [18000, 18800]) },
  { name: 'Confusion matrix', dashboard: BENCH_CM, component: 'cm-demo-viz',
    filter: range('fp', [95, 300]) },
  { name: 'Precision CI', dashboard: BENCH_CI, component: 'ci-demo-precision',
    filter: multi('tool', CALLERS) },
  { name: 'Recall CI', dashboard: BENCH_CI, component: 'ci-demo-recall',
    filter: multi('tool', CALLERS) },
  { name: 'ROC curve', dashboard: BENCH_ROC, component: 'roc-demo-viz', controls: { mode: 'roc' },
    filter: range('quality', [50, 100]) },
];

/* Trace count alone is not enough: MultiQC filters by setting `visible:false`
 * rather than dropping traces, so a working sample filter leaves the count
 * unchanged. Point count alone is not enough either, for the same reason in
 * reverse. Comparing all three is what makes this test able to fail honestly. */
function fingerprint(spec) {
  const data = spec.data || [];
  return {
    traces: data.length,
    visible: data.filter((trace) => trace.visible !== false).length,
    points: data.reduce(
      (sum, trace) =>
        sum + ((trace.x && trace.x.length) || (trace.y && trace.y.length) || (trace.z && trace.z.length) || 0),
      0,
    ),
  };
}

async function fetchSpec(apiBase, entry, filters) {
  const url = exportUrl(apiBase, {
    dashboard: entry.dashboard,
    component: entry.component,
    format: 'json',
    controls: entry.controls || null,
    filters,
  });
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function run() {
  const site = await (await fetch(API_HINT)).json();
  const rows = document.getElementById('rows');
  const summary = document.getElementById('summary');

  let passed = 0;
  let failed = 0;

  for (const entry of CASES) {
    const row = document.createElement('tr');
    row.innerHTML =
      `<td>${escapeHtml(entry.name)}</td>` +
      `<td>${escapeHtml(entry.filter.column_name)}</td>` +
      '<td class="num">…</td><td class="num">…</td><td class="num">…</td>' +
      '<td>running</td><td></td>';
    rows.appendChild(row);

    try {
      const plain = fingerprint(await fetchSpec(site.apiBase, entry, null));
      const spec = await fetchSpec(site.apiBase, entry, [entry.filter]);
      const filtered = fingerprint(spec);
      const ignored = (spec.meta || {}).unmatched_filter_columns || [];

      const changed =
        plain.traces !== filtered.traces ||
        plain.visible !== filtered.visible ||
        plain.points !== filtered.points;
      changed ? (passed += 1) : (failed += 1);

      const cell = (before, after) =>
        `<td class="num">${before}${before === after ? '' : ` → ${after}`}</td>`;

      row.innerHTML =
        `<td>${escapeHtml(entry.name)}</td>` +
        `<td>${escapeHtml(entry.filter.column_name)}</td>` +
        cell(plain.traces, filtered.traces) +
        cell(plain.visible, filtered.visible) +
        cell(plain.points, filtered.points) +
        `<td class="${changed ? 'ok' : 'bad'}">${changed ? 'filtered' : 'NO EFFECT'}</td>` +
        `<td class="${ignored.length ? 'bad' : ''}">${escapeHtml(ignored.join(', '))}</td>`;
    } catch (error) {
      failed += 1;
      row.innerHTML =
        `<td>${escapeHtml(entry.name)}</td>` +
        `<td>${escapeHtml(entry.filter.column_name)}</td>` +
        '<td class="num">—</td><td class="num">—</td><td class="num">—</td>' +
        `<td class="bad">${escapeHtml(String(error))}</td><td></td>`;
    }

    summary.textContent = `${passed} filtered · ${failed} failed · ${CASES.length - passed - failed} to go`;
  }

  summary.textContent = `${passed}/${CASES.length} filters changed the figure` +
    (failed ? ` — ${failed} did not` : '');
  summary.className = failed ? 'fail' : 'pass';
}

run().catch((error) => {
  const summary = document.getElementById('summary');
  summary.textContent = `self-test failed: ${error.message}`;
  summary.className = 'fail';
});
