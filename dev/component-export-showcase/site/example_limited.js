/* Where it stops — the same treatment, on a dashboard that does not
 * export cleanly.
 *
 * This is the honest counterpart to the clean page. It takes a whole real
 * dashboard (nf-core/viralrecon) *as it is* — every component, in dashboard
 * order, nothing curated away — and runs the identical rendering loop. Where a
 * component cannot be a Plotly spec, the page says so and falls back to an
 * embedded HTML render rather than quietly dropping the panel.
 *
 * Two limitations show up, and they are different in kind:
 *
 *   Inherent — a `text` block is prose and an `interactive` component is a
 *   widget. Neither is a figure, and no amount of work on the exporter will
 *   make them one. `format=html` is the right answer, permanently.
 *
 *   Cost — the HTML fallback is a self-contained page carrying the whole React
 *   bundle, about 7 MB each. Three fallbacks on one page is ~21 MB against a
 *   few hundred KB for the specs beside them. That is the number that should
 *   drive an integration towards JSON wherever it has the choice.
 */

const API_HINT = '/site-data.json';
const VIRALRECON = '746b0f3c1e4a2d7f8e5b9ca2';

const THEME = {
  colorway: ['#1f6feb', '#d1642a', '#2a9d5c', '#8250df', '#b3541e', '#0e7490'],
  font: { family: 'Inter Tight, system-ui, sans-serif', size: 11, color: '#1f2328' },
  grid: '#e6e8eb',
  paper: '#ffffff',
  plot: '#ffffff',
};

/* Wide panels for the plots worth reading in detail; everything else halves. */
const WIDE = new Set(['dc03abc8', '3f9fcc72', '05c68041']);

/* Written per component type rather than per component, because the reason a
 * panel degrades is a property of its type. */
const NOTES = {
  text: 'A prose block. Not a figure in any representation — <code>format=html</code> is the only sensible answer, and always will be.',
  interactive:
    'A live control. It has no figure to export, but framing it is genuinely useful: the embedded widget can post its selection back to this page.',
  multiqc: 'A MultiQC panel, exported as a finished Plotly spec.',
  figure: 'A dashboard figure, exported as a spec.',
  card: 'A metric card. The value is computed server-side; there is no plot behind it.',
  table: 'A data table. Rows, not traces.',
  advanced_viz: 'An advanced visualisation.',
};

async function init() {
  const site = await (await fetch(API_HINT)).json();
  mountSharedNav(site.pages, { backHref: '/', backLabel: 'index' });

  const manifest = await fetchManifest(site.apiBase, VIRALRECON);

  // Everything, in dashboard order. Curating this list would defeat the point.
  const panels = manifest.map((component) => {
    const short = component.component_id.slice(0, 8);
    const type = component.component_type;
    const declared = component.formats || [];
    const canJson = declared.includes('json');

    let note = NOTES[type] || '';
    if (!canJson && component.json_unavailable_reason) {
      note +=
        ` <span class="ex-reason">The manifest says so up front: ` +
        `“${escapeHtml(component.json_unavailable_reason)}”</span>`;
    }

    return {
      dashboard: VIRALRECON,
      component: component.component_id,
      kind: `${type}${component.viz_kind ? ` · ${component.viz_kind}` : ''}`,
      title: component.title || `(untitled ${type})`,
      span: WIDE.has(short) ? 12 : 6,
      note,
    };
  });

  const summary = document.getElementById('manifest-summary');
  if (summary) {
    const byType = {};
    for (const c of manifest) {
      const key = c.component_type;
      byType[key] = byType[key] || { total: 0, json: 0 };
      byType[key].total += 1;
      if ((c.formats || []).includes('json')) byType[key].json += 1;
    }
    summary.innerHTML = Object.entries(byType)
      .sort((a, b) => b[1].total - a[1].total)
      .map(
        ([type, counts]) =>
          `<li><code>${escapeHtml(type)}</code> <strong>${counts.json}/${counts.total}</strong> export as JSON</li>`,
      )
      .join('');
  }

  // The manifest is checked *before* any request is made, which is the part
  // worth copying: a host can plan its layout from the manifest alone and never
  // discover a limitation halfway through rendering.
  const requestPanel = document.getElementById('manifest-req');
  if (requestPanel) {
    requestPanel.replaceChildren(
      requestDetails({
        url: `${site.apiBase}/export/dashboards/${VIRALRECON}/components`,
        params: { note: 'declares formats[] per component before you fetch anything' },
        label: 'The manifest this page planned from',
      }),
    );
  }

  await runExample({
    apiBase: site.apiBase,
    panels,
    theme: THEME,
    mount: document.getElementById('panels'),
    scoreboard: document.getElementById('scoreboard'),
    allowFrameFallback: true,
  });
}

init().catch((err) => {
  document.getElementById('scoreboard').textContent = `failed: ${err.message}`;
});
