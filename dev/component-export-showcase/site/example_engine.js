/* Two worked integration examples, built from one shared engine.
 *
 *   /qc-report        every panel exports as JSON. Nothing degrades.
 *   /example-limited  the same treatment applied to a dashboard that does not
 *                     export cleanly, so the failure modes are on screen.
 *
 * They share this file because the interesting difference is the *dashboard*,
 * not the page code. If the clean page ran different code, it would prove
 * nothing: any page looks good when it only has to handle the good case. Both
 * run the identical loop, and the limited page simply hits paths the clean one
 * never does.
 *
 * Every panel goes through `renderPanel`, which has exactly four outcomes:
 *
 *   spec      format=json returned a figure — drawn with the host's plotly.js
 *   empty     format=json succeeded but carried no traces (a real state: a
 *             component can be validly configured and have nothing to plot)
 *   frame     JSON refused with a reason; fall back to an iframe of format=html
 *   error     both refused, or the network failed
 *
 * The outcome is recorded per panel and totalled in the header, so the score a
 * reader sees is computed from what actually happened on this page load rather
 * than asserted in prose.
 */

const OUTCOME = {
  SPEC: 'spec',
  EMPTY: 'empty',
  FRAME: 'frame',
  ERROR: 'error',
};

/* Panels are declared as {dashboard, component} pairs resolved at load time
 * against each dashboard's manifest, so a component that gets renamed or
 * removed shows up as a labelled failure rather than a silent gap. */
async function fetchManifest(apiBase, dashboardId) {
  const url = `${apiBase}/export/dashboards/${dashboardId}/components`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
  return response.json();
}

/* Strip decorative per-trace colour so the host's own colourway applies, but
 * never touch colour that encodes a value — an array of per-point colours, or
 * a colorscale — because replacing that destroys meaning rather than restyling.
 */
function restyleTraces(data, { recolour }) {
  if (!recolour) return data;
  return (data || []).map((trace) => {
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
}

/* Draw a fetched spec into a host element.
 *
 * The dashboard tile's own height travels in the spec and would otherwise win
 * over the host's layout, so it is dropped in favour of autosize. This is the
 * single most common surprise when embedding a spec, which is why it lives in
 * the shared path rather than in each page.
 */
async function drawSpec(host, spec, theme) {
  const { height: _h, width: _w, ...inherited } = spec.layout || {};
  await Plotly.newPlot(
    host,
    restyleTraces(spec.data, { recolour: theme.recolour !== false }),
    {
      ...inherited,
      autosize: true,
      paper_bgcolor: theme.paper || 'rgba(0,0,0,0)',
      plot_bgcolor: theme.plot || 'rgba(0,0,0,0)',
      colorway: theme.colorway,
      font: theme.font,
      margin: theme.margin || { l: 56, r: 20, t: 20, b: 46 },
      xaxis: { ...(inherited.xaxis || {}), gridcolor: theme.grid, zerolinecolor: theme.grid },
      yaxis: { ...(inherited.yaxis || {}), gridcolor: theme.grid, zerolinecolor: theme.grid },
      legend: { ...(inherited.legend || {}), font: { size: 10 } },
    },
    { ...spec.config, displayModeBar: false, responsive: true },
  );
}

/* One panel, start to finish.
 *
 * Returns `{outcome, spec}` — the spec as well as the tally, because a host
 * page often wants to read something out of the figure it just drew (a sample
 * count, an AUC) rather than hard-coding a number beside a live figure.
 */
async function renderPanel(panel, { apiBase, theme, allowFrameFallback = true, filters = null }) {
  const stage = panel.node.querySelector('.ex-stage');
  const status = panel.node.querySelector('.ex-status');
  // A filter only means anything where the column exists. `panel.filters`, when
  // present, is the already-scoped list for this panel's data collection.
  const applied = panel.filters !== undefined ? panel.filters : filters;
  const jsonUrl = exportUrl(apiBase, {
    dashboard: panel.dashboard,
    component: panel.component,
    format: 'json',
    controls: panel.controls || null,
    filters: applied,
  });
  const htmlUrl = exportUrl(apiBase, {
    dashboard: panel.dashboard,
    component: panel.component,
    format: 'html',
    filters: applied,
  });

  let outcome = OUTCOME.ERROR;
  let detail = '';
  let meta = null;
  let etag = null;
  let figure = null;

  try {
    const response = await fetch(jsonUrl);
    etag = response.headers.get('etag');

    if (response.ok) {
      const spec = await response.json();
      meta = spec.meta || null;
      figure = spec;
      const traces = (spec.data || []).length;
      if (traces > 0) {
        await drawSpec(stage, spec, theme);
        outcome = OUTCOME.SPEC;
        const visible = (spec.data || []).filter((t) => t.visible !== false).length;
        // MultiQC filters by hiding traces rather than dropping them, so the
        // raw count would not move under a filter and would read as broken.
        detail =
          visible === traces
            ? `${traces} trace${traces === 1 ? '' : 's'} drawn by this page`
            : `${visible} of ${traces} traces shown — filtered`;
      } else {
        outcome = OUTCOME.EMPTY;
        detail = 'exported successfully but carried no traces';
      }
    } else {
      // The API explains itself on refusal; surfacing that reason is the whole
      // point of the limited example, so read it rather than saying "failed".
      let reason = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        const d = body.detail;
        reason = (d && (d.message || d.reason)) || (typeof d === 'string' ? d : reason);
      } catch (_) {
        /* non-JSON error body; the status is all we have */
      }
      if (allowFrameFallback) {
        const frame = document.createElement('iframe');
        frame.src = htmlUrl;
        frame.className = 'ex-frame';
        frame.loading = 'lazy';
        frame.title = panel.title || 'Depictio component';
        stage.replaceChildren(frame);
        outcome = OUTCOME.FRAME;
        detail = reason;
      } else {
        outcome = OUTCOME.ERROR;
        detail = reason;
      }
    }
  } catch (err) {
    outcome = OUTCOME.ERROR;
    detail = err.message;
  }

  panel.node.dataset.outcome = outcome;
  if (status) {
    const badge = {
      [OUTCOME.SPEC]: 'JSON',
      [OUTCOME.EMPTY]: 'EMPTY',
      [OUTCOME.FRAME]: 'HTML fallback',
      [OUTCOME.ERROR]: 'failed',
    }[outcome];
    status.innerHTML =
      `<span class="ex-badge ex-badge-${outcome}">${badge}</span>` +
      `<span class="ex-detail">${escapeHtml(detail)}</span>`;
  }

  const req = panel.node.querySelector('.ex-req');
  if (req) {
    req.replaceChildren(
      requestDetails({
        url: outcome === OUTCOME.FRAME ? htmlUrl : jsonUrl,
        params: {
          format: outcome === OUTCOME.FRAME ? 'html' : 'json',
          controls: panel.controls ? JSON.stringify(panel.controls) : '(default)',
          filters: applied && applied.length ? JSON.stringify(applied) : '(none)',
          outcome,
        },
        meta,
        etag,
        label: 'How this panel was fetched',
      }),
    );
  }

  return { outcome, spec: figure };
}

/* Build the panel DOM for a declared entry.
 *
 * A page can pass its own `panelElement` to `runExample` when its host styling
 * needs different chrome; the only contract is that the node contains
 * `.ex-stage`, `.ex-status` and `.ex-req`.
 */
function panelElement(entry) {
  const article = document.createElement('article');
  article.className = `ex-panel ex-span-${entry.span || 6}`;
  article.innerHTML = `
    <header class="ex-head">
      <div>
        <p class="ex-kind">${escapeHtml(entry.kind || '')}</p>
        <h3>${escapeHtml(entry.title || '')}</h3>
      </div>
    </header>
    <div class="ex-stage"></div>
    <p class="ex-note">${entry.note || ''}</p>
    <div class="ex-status"></div>
    <div class="ex-req"></div>`;
  return article;
}

/* Run a whole example page: render every panel, then report the tally. */
async function runExample({
  apiBase,
  panels,
  theme,
  mount,
  scoreboard,
  allowFrameFallback,
  filters = null,
  makePanel = panelElement,
}) {
  const nodes = panels.map((entry) => {
    const node = makePanel(entry);
    mount.appendChild(node);
    return { ...entry, node };
  });

  const outcomes = [];
  // Sequential rather than parallel: several of these panels are large (the
  // FastQC histogram alone is 96 traces) and a browser asked for all of them at
  // once spends longer contending than it saves.
  for (const panel of nodes) {
    const result = await renderPanel(panel, { apiBase, theme, allowFrameFallback, filters });
    outcomes.push(result.outcome);
    if (panel.onSpec && result.spec) panel.onSpec(result.spec, panel);
  }

  if (scoreboard) {
    const tally = outcomes.reduce((acc, o) => ({ ...acc, [o]: (acc[o] || 0) + 1 }), {});
    const total = outcomes.length;
    const spec = tally[OUTCOME.SPEC] || 0;
    scoreboard.innerHTML = `
      <div class="score-line">
        <strong>${spec}/${total}</strong> panels rendered from a Plotly spec
      </div>
      <ul class="score-detail">
        ${
          tally[OUTCOME.FRAME]
            ? `<li><span class="ex-badge ex-badge-frame">HTML fallback</span> ${tally[OUTCOME.FRAME]} — JSON refused, embedded as a framed page</li>`
            : ''
        }
        ${
          tally[OUTCOME.EMPTY]
            ? `<li><span class="ex-badge ex-badge-empty">EMPTY</span> ${tally[OUTCOME.EMPTY]} — exported, but with nothing to plot</li>`
            : ''
        }
        ${
          tally[OUTCOME.ERROR]
            ? `<li><span class="ex-badge ex-badge-error">failed</span> ${tally[OUTCOME.ERROR]} — neither format returned a usable response</li>`
            : ''
        }
        ${
          spec === total
            ? '<li class="score-clean">Every panel on this page is a JSON spec. No iframes, no fallbacks.</li>'
            : ''
        }
      </ul>`;
  }

  return outcomes;
}
