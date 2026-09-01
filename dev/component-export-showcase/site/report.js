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
/* Resolved from /site-data.json at init, because a dashboard id is minted at
 * import and pinning one here breaks the page on the next re-seed.
 *
 * Two of them, because this page draws from two dashboards of the same project:
 * `community` carries the composition figures, the cards, the tables and every
 * control in the deck; `ampliseq` carries the pipeline's MultiQC report, which
 * is what the Overview tab's quality panels are. A host page is not restricted
 * to one dashboard's worth of components, and demonstrating that is worth more
 * than the tidiness of a single id. */
const DASHBOARDS = { community: null, ampliseq: null };

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
  {
    id: 'phylum',
    kind: 'checklist',
    label: 'Phylum',
    hint: 'Any number of phyla',
    column: 'Phylum',
  },
  {
    id: 'abundance',
    kind: 'range',
    label: 'Relative abundance',
    hint: 'Restrict the range',
    column: 'rel_abundance',
  },
];

/* Every figure on the page, and which panel it belongs to.
 *
 * `tab` is the panel the figure lives in. A figure is only fetched once its tab
 * has been opened, and a filter change only refetches what is on screen; the
 * rest is marked stale and redrawn when its tab is next shown. Eleven figures
 * refetched on every drag of a slider would be the obvious way to write this
 * and the wrong one.
 *
 * `dashboard` keys into DASHBOARDS. The QC panels come from the project's
 * ampliseq tab, so the filter deck drives components from two dashboards at
 * once; the taxonomic filters are meaningless to a MultiQC module and come back
 * reported as ignored, which is the response saying so rather than this page
 * guessing which filters to withhold.
 */
const FIGURES = [
  // Overview: the pipeline's own quality report, module by module. A MultiQC
  // panel has no title of its own, so it is addressed by the module and plot it
  // displays, which is what the dashboard itself selects.
  { slot: 'qc-general', tab: 'overview', dashboard: 'ampliseq', find: { module: 'general_stats' } },
  { slot: 'qc-counts', tab: 'overview', dashboard: 'ampliseq', find: { module: 'fastqc', plot: 'Sequence Counts' } },
  { slot: 'qc-filtered', tab: 'overview', dashboard: 'ampliseq', find: { module: 'cutadapt', plot: 'Filtered Reads' } },
  { slot: 'qc-quality', tab: 'overview', dashboard: 'ampliseq', find: { module: 'fastqc', plot: 'Sequence Quality Histograms' } },
  { slot: 'qc-lengths', tab: 'overview', dashboard: 'ampliseq', find: { module: 'fastqc', plot: 'Sequence Length Distribution' } },
  { slot: 'qc-adapters', tab: 'overview', dashboard: 'ampliseq', find: { module: 'fastqc', plot: 'Adapter Content' } },

  // Community composition. The quantitative panel is the dashboard's only plain
  // figure component, so its type identifies it on its own.
  { slot: 'quant', tab: 'composition', dashboard: 'community', find: { type: 'figure' } },
  { slot: 'stacked', tab: 'composition', dashboard: 'community', find: { tag: 'adv-stacked-taxonomy' } },

  // Taxonomic flow.
  { slot: 'sunburst', tab: 'flow', dashboard: 'community', find: { tag: 'adv-sunburst' } },
  { slot: 'sankey', tab: 'flow', dashboard: 'community', find: { tag: 'adv-sankey' } },
  { slot: 'upset', tab: 'flow', dashboard: 'community', find: { tag: 'adv-upset' } },
];

/* A table drawn by this page from its rows.
 *
 * `format=data` returns {columns, rows, total}, so a table does not have to be
 * framed to appear on a host page. It is the same argument as `format=json` for
 * a figure: the host gets the data and keeps its own typography, its own
 * alignment, its own pager. A frame for twelve rows means shipping a whole
 * Depictio bundle to render them, in a scroll box this page cannot theme.
 *
 * `Sample Metadata` on the Methodology tab is deliberately left as a frame, so
 * the page shows both answers for the same component type and the footers say
 * which is which. */
const TABLES = [
  {
    key: 'taxonomy-table',
    tab: 'composition',
    dashboard: 'community',
    find: { type: 'table', title: 'Taxonomy Relative Abundance' },
    title: 'Taxonomy Relative Abundance',
    pageSize: 12,
    // Rendered right-aligned and rounded; everything else is left as text.
    numeric: ['rel_abundance'],
  },
];

/* Components with no form but a rendered one, mounted as frames when their tab
 * is first opened. A card is a styled number and Depictio's grid is AG Grid, so
 * `html` is what these are. */
const FRAMES = [
  {
    key: 'sample-table',
    tab: 'methodology',
    dashboard: 'ampliseq',
    find: { type: 'table', title: 'Sample Metadata' },
    title: 'Sample Metadata',
    height: 400,
  },
];

/* The overview stat band. Ordered as a portal orders one, broadest first: what
 * was sampled, then what was found, then how it is distributed. All four of the
 * dashboard's cards, because three of four leaves the row unfinished. */
const CARDS = [
  { dashboard: 'community', find: { type: 'card', title: 'Habitat groups' }, label: 'Habitat groups' },
  { dashboard: 'community', find: { type: 'card', title: 'Phyla detected' }, label: 'Phyla detected' },
  { dashboard: 'community', find: { type: 'card', title: 'Distinct taxa' }, label: 'Distinct taxa' },
  {
    dashboard: 'community',
    find: { type: 'card', title: 'Rel. abundance (distribution)' },
    label: 'Rel. abundance (distribution)',
  },
];

const state = {
  apiBase: '',
  filters: [],
  manifest: [],
  qcManifest: [],
  // Column names per data collection, from the manifests. Keyed by dc_id, so
  // one entry serves every component drawing from that collection.
  columns: {},
  spare: null,
  tab: null,
  stale: new Set([...FIGURES.map((entry) => entry.slot), ...TABLES.map((entry) => entry.key)]),
  framed: new Set(),
  // Which page of each host-rendered table is on screen.
  pages: Object.fromEntries(TABLES.map((entry) => [entry.key, 0])),
};

/* Every filter is sent to every figure, and the server decides what it means.
 *
 * This used to require the filter's collection to equal the figure's, which
 * silently disabled most of the deck: `habitat` and `sampling_date` live on the
 * sample metadata collection and no figure on this page reads that collection
 * directly. Only `Kingdom` ever reached the API.
 *
 * Dropping them client-side was the bug. The project declares links between its
 * collections, so Depictio resolves the join server-side and a habitat filter
 * genuinely reaches a taxonomy figure. It is the same rule /qc-report uses.
 *
 * The converse case is real too and is left to the server on purpose: a
 * taxonomic filter means nothing to a MultiQC module, and the response says so
 * in `meta.unmatched_filter_columns`, which each panel reports. A page that
 * withheld those filters on a guess would have to guess correctly about every
 * component type, and would silently be wrong the first time it did not. */
/* ---- addressing components -------------------------------------------------
 *
 * A component id is minted when a dashboard is imported, so re-seeding an
 * instance issues new ones and every id a page like this pinned becomes a 404.
 * That is not hypothetical: it is what happened to this page when the project
 * was re-seeded from a newer template, and nothing about the page said so. The
 * figures simply stopped arriving.
 *
 * So nothing here is addressed by id. Every panel declares what it wants and
 * the manifest is searched for it, by properties the dashboard's YAML actually
 * declares and a re-seed preserves:
 *
 *   tag     a YAML `tag:`, which is already a stable id and is used as one
 *   title   the component's title, for the components that have one
 *   type    narrows the search, and on its own means "the only one of these"
 *   module  a MultiQC panel's module and plot, which is what it displays
 *
 * A descriptor matching nothing, or matching more than one component, is a bug
 * in this page and is shown as one on the panel. The alternative is a request
 * for `undefined` and an HTTP 404 that reads like the API is broken.
 */
function findComponent(find, manifest) {
  const hits = (manifest || []).filter((entry) => {
    if (find.tag && entry.component_id !== find.tag) return false;
    if (find.type && entry.component_type !== find.type) return false;
    if (find.title !== undefined && (entry.title || '') !== find.title) return false;
    if (find.module && (entry.multiqc || {}).module !== find.module) return false;
    if (find.plot && (entry.multiqc || {}).plot !== find.plot) return false;
    return true;
  });
  if (hits.length === 1) return { entry: hits[0] };
  return {
    reason: hits.length
      ? `${hits.length} components match`
      : 'no component matches',
  };
}

/* Resolve every panel on the page against the manifests, once, at load.
 *
 * Also where each panel learns its data collection: `dc_id` comes back with the
 * component, so the page never has to carry a table of collection ids either. */
function bindComponents() {
  const manifests = { community: state.manifest, ampliseq: state.qcManifest };
  for (const spec of [...FIGURES, ...TABLES, ...FRAMES, ...CARDS]) {
    const dashboard = spec.dashboard || 'community';
    const wanted = Object.entries(spec.find)
      .map(([key, value]) => `${key}="${value}"`)
      .join(', ');
    const { entry, reason } = findComponent(spec.find, manifests[dashboard]);
    spec.component = entry ? entry.component_id : null;
    spec.dc = entry ? entry.dc_id : null;
    spec.componentType = entry ? entry.component_type : null;
    spec.unresolved = entry ? null : `${reason}: ${wanted} on the ${dashboard} dashboard`;
    if (!entry) console.warn(`report: unresolved component — ${spec.unresolved}`);
  }
}

/* Put a hover label's text back inside its own box.
 *
 * Plotly places the box and the text of a hover label separately, and on some
 * figures it gets the text wrong by exactly the label group's own vertical
 * translation: the box path is centred on the group origin while the text is
 * written at `4.5 - translateY`, which is the right offset expressed in the
 * wrong coordinate system. The text then floats above its box by however far
 * down the page the hovered point sits.
 *
 * It is not this page's styling and it is not the font. It reproduces on the
 * raw exported spec drawn with a bare `Plotly.newPlot` and no restyling, in
 * plotly.js 2.35.2 and 3.0.1 alike, on the two figures here whose layout is
 * unusual: the UpSet, three subplots with explicit domains, and the sankey,
 * which has no cartesian axes at all. Everything else on the page is fine.
 *
 * So it is corrected rather than avoided, and corrected by measurement rather
 * than by reproducing Plotly's arithmetic: if the text's centre is not the
 * box's centre, move it there. A no-op wherever Plotly is already right.
 */
function alignHoverLabels(gd) {
  for (const group of gd.querySelectorAll('.hoverlayer .hovertext')) {
    const box = group.querySelector('path');
    // A label is `.nums`, the body, optionally beside a `.name`. Plotly places
    // the name against the box's *edge* rather than its centre, so measuring
    // the drift from whichever text happens to come first in the DOM would
    // centre the name on the body and print the two on top of each other.
    // Measure the body, then move every text by that one drift, which leaves
    // the name where it was put relative to the body.
    const texts = [...group.querySelectorAll('text')];
    const body = group.querySelector('text.nums') || texts[0];
    if (!box || !body) continue;
    const boxRect = box.getBoundingClientRect();
    const bodyRect = body.getBoundingClientRect();
    if (!boxRect.height || !bodyRect.height) continue;
    const drift = boxRect.top + boxRect.height / 2 - (bodyRect.top + bodyRect.height / 2);
    if (Math.abs(drift) < 2) continue;
    for (const text of texts) {
      for (const node of [text, ...text.querySelectorAll('tspan[y]')]) {
        node.setAttribute('y', String(parseFloat(node.getAttribute('y') || '0') + drift));
      }
    }
  }
}

/* How big the drawn figure is, in whatever unit that figure has.
 *
 * The panel footers used to say "N traces", which for a sunburst or a sankey is
 * the constant 1: filtering one from 43 segments down to 18 left the footer
 * reading exactly as before, so a filter that worked looked like a filter that
 * did nothing. Count what the figure is actually made of instead.
 */
function figureSize(data) {
  const first = data[0] || {};
  if (first.type === 'sankey') {
    const nodes = (first.node || {}).label || [];
    const links = (first.link || {}).value || [];
    return `${nodes.length} nodes · ${links.length} links`;
  }
  if (['sunburst', 'treemap', 'icicle', 'pie'].includes(first.type)) {
    return `${(first.labels || []).length} segments`;
  }
  // MultiQC filters by hiding traces rather than dropping them, so a raw count
  // does not move under a filter and reads as broken. Say how many of them are
  // actually shown when the two differ.
  const shown = data.filter((trace) => trace.visible !== false).length;
  const traces = shown === data.length ? `${data.length} traces` : `${shown} of ${data.length} traces shown`;
  // The longest of the three, not the first that exists: a horizontal bar
  // carries its categories in `y` and its values in `x`, and a trace can carry
  // an empty one of the pair.
  const points = data.reduce(
    (total, trace) =>
      total +
      Math.max(
        (trace.x || []).length || 0,
        (trace.y || []).length || 0,
        (trace.values || []).length || 0,
      ),
    0,
  );
  return points ? `${traces} · ${points} points` : traces;
}

/* Filters this page is sending that the given collection cannot answer.
 *
 * A filter naming a column a collection does not have is dropped by the render
 * path, and the response is a healthy 200 carrying an unchanged figure. That is
 * not hypothetical here: the taxonomy collection spells its habitat column
 * `habitat` and the sunburst and sankey collections spell theirs `Habitat`, and
 * the stacked-taxonomy collection carries no `Phylum` column at all, holding
 * rank and taxon instead. So three panels on this page quietly ignore a filter
 * the deck presents as global, and the only honest thing to do is say which.
 *
 * The manifest publishes each component's columns for exactly this, under
 * `?include_columns=true`. It describes the collection and not the join graph,
 * so it is not consulted for MultiQC panels: those answer a sample filter
 * through a declared link, on a column their own collection does not carry.
 */
function notApplicableTo(dcId) {
  const columns = state.columns[dcId];
  if (!columns) return [];
  return state.filters
    .filter((entry) => {
      const filter = entry.filter;
      if (!filter.column_name || columns.includes(filter.column_name)) return false;
      // A collection can carry the same distinction without carrying the
      // column: the UpSet collection has one column per habitat rather than a
      // habitat column, and a habitat filter does reach it. If the filter's
      // values name columns here, this collection addresses it after all.
      const values = Array.isArray(filter.value) ? filter.value : [filter.value];
      return !values.some((value) => columns.includes(String(value)));
    })
    .map((entry) => entry.filter.column_name);
}

/* What a panel shows in place of a component this page could not find. */
function unresolvedNote(spec) {
  const box = document.createElement('div');
  box.className = 'pp-error';
  box.innerHTML =
    'This page asked for a component the dashboard does not publish. ' +
    `<span>${escapeHtml(spec.unresolved)}</span>`;
  return box;
}

function filtersFor() {
  return state.filters.map((entry) => entry.filter);
}

/* Draw one export in the portal's plotly idiom.
 *
 * The portal's figures share a recognisable treatment: white plot area, a thin
 * mirrored axis frame in #d6d6d6, pale horizontal gridlines only, a small
 * legend, and tight margins. Reproducing it here is the whole point — the same
 * Depictio spec would look like a foreign object with Depictio's own layout.
 */
async function drawFigure(host, spec, componentType) {
  // Plotly sizes every box it draws around text (hover labels above all) by
  // measuring the text in the browser, once. This page loads IBM Plex Sans from
  // Google with `display=swap`, so on a cold load the first measurement happens
  // in the fallback face and the paint happens in Plex: the label's box and the
  // label's text end up sized for two different fonts, and the text sits off
  // its container. Waiting costs nothing once the face is cached, and
  // `fonts.ready` is already resolved on every draw after the first.
  if (document.fonts && document.fonts.ready) await document.fonts.ready;

  const { height: _h, width: _w, ...inherited } = spec.layout || {};

  // Strip decorative per-trace colour so the portal sequence applies, but leave
  // colour that *encodes* a value untouched.
  //
  // "Encodes a value" was originally taken to mean an array or a colorscale.
  // That reading is too narrow, and the UpSet is the counter-example: its
  // membership matrix is two sets of traces distinguished by nothing but a flat
  // colour, `#C2C2C2` for the dots of sets a taxon is absent from and one
  // colour per set for the dots it belongs to. Strip those and every dot is
  // repainted from the portal sequence, so every column reads as belonging to
  // every habitat, which is the opposite of what an UpSet plot is for.
  //
  // An advanced-viz figure has already spent its colour on meaning: set
  // membership here, the taxonomic hierarchy in the sunburst, flow in the
  // sankey. A plain figure's trace colour is Depictio's default palette, which
  // is what this page is entitled to overrule.
  const recolour = componentType !== 'advanced_viz';
  const data = (spec.data || []).map((trace) => {
    if (!recolour) return trace;
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
      ...(recolour ? { colorway: PP_SEQUENCE } : {}),
      font: { family: 'IBM Plex Sans, Helvetica, Arial, sans-serif', size: 12, color: PP.ink },
      margin: { l: 60, r: 20, t: 30, b: 50 },
      legend: { ...(inherited.legend || {}), font: { size: 10 } },
      // Stated in full rather than left to Plotly. Plotly derives a hover box's
      // background from the colour of the thing hovered and then picks black or
      // white text against it, which works until a page restyles the traces:
      // this one strips decorative trace colour so the portal sequence applies,
      // and the hover box inherits whatever that sequence landed on. On the
      // pale end of it, and on the sankey's translucent links, that is white
      // text on near-white. A fixed white box with ink text cannot drift.
      // Colours only. `align` is deliberately not set: it is the one hover
      // property here that moves geometry rather than paint, and Plotly's own
      // default is what the label's box was measured against.
      hoverlabel: {
        bgcolor: '#ffffff',
        bordercolor: PP.line,
        font: { family: 'IBM Plex Sans, sans-serif', size: 11, color: PP.ink },
      },
    },
    { ...spec.config, displayModeBar: false, responsive: true },
  );

  // Watched rather than hooked to `plotly_hover`: that event fires when the
  // hovered point changes, and Plotly also moves a label while the pointer
  // travels within one point, which is exactly when the drift is visible. The
  // correction is idempotent, so the writes it makes settle on the next pass.
  const layer = host.querySelector('.hoverlayer');
  if (layer) {
    new MutationObserver(() => alignHoverLabels(host)).observe(layer, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['transform', 'd', 'y'],
    });
  }
}

/* ---- delivery footers ------------------------------------------------------
 *
 * Every component on this page carries the same disclosure, in the same shape:
 * a badge naming which of the two delivery methods it arrived by, a sentence
 * saying what that method means, and a collapsible panel holding the exact
 * request, its parameters and the response's own provenance.
 *
 * It is the difference between a page that asks to be trusted and one that can
 * be checked. It also makes the coverage gap legible: a card and a table say
 * IFRAME because a card and a table have no Plotly form, and saying so on the
 * panel is more useful than leaving the reader to wonder why one figure zooms
 * and another does not.
 */
const DELIVERY = {
  json: {
    badge: 'JSON',
    note: 'Plotly spec fetched by this page, drawn by its own plotly.js',
  },
  html: {
    badge: 'IFRAME',
    note: 'self-contained frame, drawn by Depictio in its own document',
  },
  data: {
    badge: 'DATA',
    note: 'rows fetched by this page, rendered in its own table',
  },
  manifest: {
    badge: 'MANIFEST',
    note: 'the component list this page binds its controls against',
  },
  failed: {
    badge: 'FAILED',
    note: 'the export did not return a figure',
  },
};

function methodBadge(host, method) {
  if (!host) return;
  const spec = DELIVERY[method];
  host.innerHTML =
    `<span class="pp-badge pp-badge-${method}">${escapeHtml(spec.badge)}</span>` +
    `<span class="pp-foot-note">${escapeHtml(spec.note)}</span>`;
}

/* The same `requestDetails` panel every showcase page uses, with the delivery
 * method spelled into its parameter list so the footer is self-contained when
 * it is the only thing a reader opens. */
function deliveryDetails({ method, url, params = {}, meta = null, etag = null, label }) {
  return requestDetails({
    url,
    params: { method: DELIVERY[method].note, ...params },
    meta,
    etag,
    label,
  });
}

async function loadFigure(entry) {
  const section = document.querySelector(`[data-slot="${entry.slot}"]`);
  if (!section) return;
  const stage = section.querySelector('.pp-stage');
  const status = section.querySelector('.pp-status');
  const method = section.querySelector('.pp-method');
  const filters = filtersFor();
  const dashboard = DASHBOARDS[entry.dashboard || 'community'];

  if (!entry.component) {
    stage.replaceChildren(unresolvedNote(entry));
    status.textContent = 'unresolved';
    methodBadge(method, 'failed');
    return;
  }

  // The portal dims a panel while htmx is in flight; same affordance here, for
  // the same reason: a figure that silently swaps is hard to trust.
  section.classList.add('is-loading');

  const url = exportUrl(state.apiBase, {
    dashboard,
    component: entry.component,
    format: 'json',
    filters,
  });

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const spec = await response.json();
    await drawFigure(stage, spec, entry.componentType);

    const drawn = figureSize(spec.data || []);
    const unmatched = (spec.meta || {}).unmatched_filter_columns;
    const inapplicable = entry.componentType === 'multiqc' ? [] : notApplicableTo(entry.dc);
    status.textContent = filters.length
      ? `${drawn} · ${filters.length} filter${filters.length === 1 ? '' : 's'} applied`
      : `${drawn} · unfiltered`;
    // A filter that reached no control is a real state and the API now reports
    // it, so say so rather than showing an unchanged figure as if it worked.
    if (unmatched && unmatched.length) {
      status.textContent += ` · ignored: ${unmatched.join(', ')}`;
    }
    // The same honesty for the other half of the problem: the filter reached a
    // control, and then this component's collection had no such column.
    if (inapplicable.length) {
      status.textContent += ` · not in this collection: ${inapplicable.join(', ')}`;
    }

    methodBadge(method, 'json');
    section.querySelector('.pp-req').replaceChildren(
      deliveryDetails({
        method: 'json',
        url,
        params: {
          format: 'json',
          dashboard,
          component: entry.component,
          filters: filters.length ? JSON.stringify(filters) : '(none)',
          dc_id: entry.dc,
          drawn,
          not_in_collection: inapplicable.length ? inapplicable.join(', ') : '(none)',
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
    methodBadge(method, 'failed');
    section.querySelector('.pp-req').replaceChildren(
      deliveryDetails({
        method: 'failed',
        url,
        params: { format: 'json', error: String(error) },
        label: 'The request that failed',
      }),
    );
  } finally {
    section.classList.remove('is-loading');
  }
}

/* Refetch what is visible; remember what is not.
 *
 * `force` is for the first paint of a tab, where the figure has never been
 * drawn and so is stale by definition. */
/* Everything the deck drives, keyed by the panel it lives in. A figure is drawn
 * from a Plotly spec and a table from its rows, but both go stale the same way
 * when a filter changes and both are redrawn when their tab comes back. */
function panelsFor(tab) {
  return [
    ...FIGURES.filter((entry) => entry.tab === tab).map((entry) => [entry.slot, () => loadFigure(entry)]),
    ...TABLES.filter((entry) => entry.tab === tab).map((entry) => [entry.key, () => loadTable(entry)]),
  ];
}

function redrawAll() {
  const keys = new Set(panelsFor(state.tab).map(([key]) => key));
  panelsFor(state.tab).forEach(([, draw]) => draw());
  for (const entry of [...FIGURES.map((f) => f.slot), ...TABLES.map((t) => t.key)]) {
    if (!keys.has(entry)) state.stale.add(entry);
  }
  refreshFramed();
}

/* Re-point the framed components at the filters that just changed.
 *
 * A figure is refetched by asking for a new spec and handing it to plotly, but
 * a card and a framed table are whole Depictio documents, and the embed only
 * ever posts *out* — there is no inbound channel to push a filter into one
 * that is already mounted. Its `?filters=` is fixed when its `src` is set, so
 * the only way to filter one is to send it to a new URL.
 *
 * Which is done by navigating the frame that is already there, never by
 * building a new one. A fresh `<iframe>` paints white the instant it is
 * inserted and stays white until several megabytes of self-contained document
 * have parsed; navigating the existing frame leaves the old render on screen
 * until the new one is ready to paint. Over four cards at once that is the
 * difference between the deck feeling live and the page appearing to break on
 * every change. Each mounted host therefore keeps an `update` holding exactly
 * the parts of it that depend on the filters.
 *
 * Only what is mounted is touched; a tab nobody has opened builds its URL from
 * the current filters on the way in.
 */
function refreshFramed() {
  const cards = mounted.has('overview')
    ? [...document.querySelectorAll('#overview-cards .pp-card')]
    : [];
  const frames = FRAMES.filter((spec) => state.framed.has(spec.key)).map((spec) =>
    document.querySelector(`[data-frame="${spec.key}"]`),
  );
  for (const host of [...cards, ...frames]) if (host && host.update) host.update();
}

function drawStaleIn(tab) {
  panelsFor(tab).forEach(([key, draw]) => {
    if (!state.stale.has(key)) return;
    state.stale.delete(key);
    draw();
  });
}

function setFilter(id, dc, filter) {
  state.filters = state.filters.filter((entry) => entry.id !== id);
  const value = filter && filter.value;
  const empty = value == null || (Array.isArray(value) && value.length === 0) || value === '';
  if (!empty) state.filters.push({ id, dc, filter });
  // Page 20 of a result that just became three rows long is not a page a reader
  // asked for; a changed filter restarts every table at its first page.
  for (const key of Object.keys(state.pages)) state.pages[key] = 0;
  renderActiveFilters();
  redrawAll();
}

function renderActiveFilters() {
  const host = document.getElementById('active-filters');
  if (!host) return;

  // The chip row and the count live outside the collapsing part of the deck,
  // so folding it away never hides what is being filtered.
  const count = document.getElementById('filters-count');
  if (count) count.textContent = state.filters.length ? String(state.filters.length) : '';
  const reset = document.getElementById('filters-reset');
  if (reset) reset.disabled = state.filters.length === 0;

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

/* A many-valued categorical control.
 *
 * `Phylum` publishes 31 options, which is past what a <select> is pleasant for
 * and past what the portal's own single-choice widgets cover. A filterable
 * checkbox list is the portal-plausible answer and, unlike a multi-select, it
 * shows the current selection without being opened.
 */
function buildChecklist(spec, control) {
  const cell = document.createElement('div');
  cell.className = 'pp-control';
  const options = (control.filter.options || {}).values || [];
  const id = `pp:${control.component_id}`;

  cell.innerHTML =
    `<div class="pp-control-head pp-control-head-plain"><span>${escapeHtml(spec.label)}</span></div>` +
    `<div class="pp-control-body"><div class="pp-control-hint">${escapeHtml(spec.hint)}</div></div>`;

  const body = cell.querySelector('.pp-control-body');

  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'pp-checklist-search';
  search.placeholder = `Search ${options.length} values`;
  search.setAttribute('aria-label', `Search ${spec.label} values`);

  const list = document.createElement('div');
  list.className = 'pp-checklist';
  const boxes = options.map((value) => {
    const row = document.createElement('label');
    row.className = 'pp-checklist-row';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.value = value;
    row.append(box, Object.assign(document.createElement('span'), { textContent: value }));
    list.appendChild(row);
    return box;
  });

  const foot = document.createElement('div');
  foot.className = 'pp-checklist-foot';
  const readout = document.createElement('span');
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'pp-linkbutton';
  clear.textContent = 'clear';
  foot.append(readout, clear);

  const push = () => {
    const chosen = boxes.filter((box) => box.checked).map((box) => box.value);
    readout.textContent = chosen.length ? `${chosen.length} of ${options.length}` : 'all';
    clear.hidden = chosen.length === 0;
    setFilter(id, control.dc_id, {
      interactive_component_type: control.filter.interactive_component_type,
      column_name: control.filter.column_name,
      value: chosen,
    });
  };

  boxes.forEach((box) => box.addEventListener('change', push));
  clear.addEventListener('click', () => {
    boxes.forEach((box) => {
      box.checked = false;
    });
    push();
  });
  search.addEventListener('input', () => {
    const needle = search.value.trim().toLowerCase();
    for (const row of list.children) {
      row.hidden = needle !== '' && !row.textContent.toLowerCase().includes(needle);
    }
  });

  readout.textContent = 'all';
  clear.hidden = true;
  body.append(search, list, foot);
  return cell;
}

/* A numeric range.
 *
 * The contract reports a RangeSlider as kind:"range" with numeric bounds, and
 * `rel_abundance` spans four orders of magnitude, so the two sliders address a
 * fixed integer track that is mapped onto the real bounds rather than carrying
 * float steps. The filter is pushed on `change`, not `input`: a fetch per pixel
 * dragged would be five figures per pixel.
 */
function buildRange(spec, control) {
  const cell = document.createElement('div');
  cell.className = 'pp-control';
  const options = control.filter.options || {};
  const id = `pp:${control.component_id}`;
  const min = Number(options.min);
  const max = Number(options.max);

  cell.innerHTML =
    `<div class="pp-control-head pp-control-head-plain"><span>${escapeHtml(spec.label)}</span></div>` +
    `<div class="pp-control-body"><div class="pp-control-hint">${escapeHtml(spec.hint)}</div></div>`;

  const STEPS = 1000;
  const toValue = (tick) => min + ((max - min) * Number(tick)) / STEPS;
  const format = (value) => (value >= 0.01 ? value.toFixed(3) : value.toExponential(1));

  const wrap = document.createElement('div');
  wrap.className = 'pp-range';
  const low = document.createElement('input');
  const high = document.createElement('input');
  for (const [input, tick, label] of [[low, 0, 'lower bound'], [high, STEPS, 'upper bound']]) {
    input.type = 'range';
    input.min = '0';
    input.max = String(STEPS);
    input.value = String(tick);
    input.setAttribute('aria-label', `${spec.label} ${label}`);
  }
  const readout = document.createElement('div');
  readout.className = 'pp-range-readout';

  const bounds = () => {
    // Either handle may be dragged past the other; order them rather than
    // letting the pair express an empty range.
    const ticks = [Number(low.value), Number(high.value)].sort((a, b) => a - b);
    return [toValue(ticks[0]), toValue(ticks[1])];
  };
  const paint = () => {
    const [lo, hi] = bounds();
    readout.textContent = `${format(lo)} – ${format(hi)}`;
  };
  const push = () => {
    paint();
    const [lo, hi] = bounds();
    const whole = Number(low.value) === 0 && Number(high.value) === STEPS;
    setFilter(id, control.dc_id, {
      interactive_component_type: 'RangeSlider',
      column_name: control.filter.column_name,
      // The full span is not a filter, it is the absence of one. Sending it
      // would put a chip on screen and a parameter on the URL that change
      // nothing.
      value: whole ? [] : [lo, hi],
    });
  };
  for (const input of [low, high]) {
    input.addEventListener('input', paint);
    input.addEventListener('change', push);
  }

  paint();
  wrap.append(low, high);
  cell.querySelector('.pp-control-body').append(wrap, readout);
  return cell;
}

function mountControls() {
  const host = document.getElementById('plot-filters');
  host.replaceChildren();

  // Both manifests, because the deck is not one dashboard's control panel: the
  // sampling window is published by the QC dashboard and the taxonomic columns
  // by the community one. A filter carries its column and its collection, not
  // the dashboard it was read from, so where the control was found makes no
  // difference to what the filter reaches.
  const byColumn = new Map();
  const source = new Map();
  for (const [dashboard, manifest] of [
    ['community', state.manifest],
    ['ampliseq', state.qcManifest],
  ]) {
    for (const entry of manifest || []) {
      if (entry.component_type !== 'interactive') continue;
      if (!entry.filter || !entry.filter.column_name) continue;
      if (byColumn.has(entry.filter.column_name)) continue;
      byColumn.set(entry.filter.column_name, entry);
      source.set(entry.filter.column_name, dashboard);
    }
  }

  let mounted = 0;
  const bound = [];
  for (const spec of CONTROLS) {
    const control = byColumn.get(spec.column);
    if (!control) continue; // no control for that column: omit rather than fake
    bound.push(`${spec.column} (${source.get(spec.column)})`);
    const builder = {
      toggle: buildToggle,
      select: buildSelect,
      dates: buildDates,
      checklist: buildChecklist,
      range: buildRange,
    }[spec.kind];
    host.appendChild(builder(spec, control));
    mounted += 1;
  }

  // The portal's grey control heads run as a continuous band across a row, and
  // five controls in a three-column grid leave the last band stopping halfway.
  // Fillers finish it. They go away with the grid: below 900px the deck is one
  // column, where there is no row to finish.
  for (let missing = mounted % 3; missing && missing < 3; missing += 1) {
    const filler = document.createElement('div');
    filler.className = 'pp-control pp-control-filler';
    filler.innerHTML = '<div class="pp-control-head pp-control-head-plain">&nbsp;</div>';
    host.appendChild(filler);
  }

  const url =
    `${state.apiBase}/export/dashboards/${DASHBOARDS.community}` +
    '/components?include_filter_options=true';
  const missing = CONTROLS.filter((spec) => !byColumn.has(spec.column)).map((spec) => spec.column);

  // The deck gets the same footer as every panel: it is a component of this
  // page too, and the request that built it is as inspectable as the ones that
  // drew the figures.
  methodBadge(document.getElementById('plot-filters-method'), 'manifest');
  const status = document.getElementById('plot-filters-status');
  if (status) {
    status.textContent = `${mounted} of ${CONTROLS.length} controls bound · unfiltered`;
  }
  document.getElementById('plot-filters-req').replaceChildren(
    deliveryDetails({
      method: 'manifest',
      url,
      params: {
        include_filter_options: 'true',
        dashboards: `${DASHBOARDS.community} (community), ${DASHBOARDS.ampliseq} (ampliseq)`,
        bound: `${mounted} of ${CONTROLS.length} portal controls`,
        columns: bound.join(', '),
        unbound: missing.length ? missing.join(', ') : '(none)',
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
function mountEmbeddedControl() {
  const host = document.getElementById('embedded-control');
  const control = state.spare;
  if (!host || !control) return;

  const url = exportUrl(state.apiBase, {
    dashboard: DASHBOARDS.community,
    component: control.component_id,
    format: 'html',
  });

  const frame = document.createElement('iframe');
  frame.src = url;
  frame.className = 'pp-control-frame';
  frame.title = 'Depictio interactive component';
  frame.loading = 'lazy';
  host.replaceChildren(frame);

  methodBadge(document.getElementById('embedded-control-method'), 'html');
  document.getElementById('embedded-control-req').replaceChildren(
    deliveryDetails({
      method: 'html',
      url,
      params: {
        format: 'html',
        dashboard: DASHBOARDS.community,
        component: control.component_id,
        column: (control.filter || {}).column_name,
        note: 'the real Depictio widget, framed; it posts its filter back out',
      },
      label: 'How this control is embedded',
    }),
  );

  window.addEventListener('message', (event) => {
    // Only trust messages from the API origin we asked for; without this any
    // framed page could push filters into this dashboard.
    if (state.apiBase && !state.apiBase.startsWith(event.origin)) return;
    const message = event.data;
    if (!message || message.source !== 'depictio-embed' || message.type !== 'filter') return;
    // `control.dc_id`, never `message.dcId`: the embed payload rewrites an
    // interactive component's dc_id to a synthetic `embed::<component id>` so
    // the offline shim can key several controls off one collection, and that
    // value matches no figure here. The manifest's dc_id is the real one.
    setFilter(`embed:${control.component_id}`, control.dc_id, message.filter);
  });
}

/* ---- tabs -------------------------------------------------------------------
 *
 * The portal's tab strip is five Django views; here it is five panels on one
 * page, because a page that hands its visitor off to a differently-styled
 * showcase route the moment they click "Overview" is not demonstrating an
 * embedded dashboard. Keeping them in-page also keeps the filter deck's state:
 * pick a habitat on one tab and the figures on the next tab are already
 * filtered by it.
 *
 * Content that costs a request is mounted on first visit rather than at load.
 */
const MOUNTERS = {
  overview: mountOverviewCards,
  methodology: mountEmbeddedControl,
  components: mountComponentTable,
};
const mounted = new Set();

function showTab(id) {
  const target = document.getElementById(`panel-${id}`);
  if (!target) return showTab('composition');
  state.tab = id;

  document.querySelectorAll('.pp-tabpanel').forEach((panel) => {
    panel.hidden = panel !== target;
  });
  document.querySelectorAll('#pp-tabs .pp-tab').forEach((tab) => {
    const current = tab.dataset.tab === id;
    tab.classList.toggle('pp-tab-current', current);
    tab.setAttribute('aria-selected', String(current));
  });

  // Two of the five tabs have no figure to filter, so the deck goes with the
  // panel rather than sitting above prose it does not affect.
  document.getElementById('filter-deck').hidden = target.dataset.deck !== 'yes';

  if (location.hash.slice(1) !== id) history.replaceState(null, '', `#${id}`);

  if (!mounted.has(id)) {
    mounted.add(id);
    if (MOUNTERS[id]) MOUNTERS[id]();
  }

  FRAMES.filter((spec) => spec.tab === id && !state.framed.has(spec.key)).forEach((spec) => {
    state.framed.add(spec.key);
    mountFrame(spec);
  });

  drawStaleIn(id);
  // A figure drawn before its panel was hidden keeps the width it had then, so
  // a window resized on another tab leaves it stretched or clipped. Cheap to
  // re-measure, and only the already-drawn ones can need it.
  FIGURES.filter((entry) => entry.tab === id).forEach((entry) => {
    const stage = document.querySelector(`[data-slot="${entry.slot}"] .pp-stage`);
    if (stage && stage.classList.contains('js-plotly-plot')) Plotly.Plots.resize(stage);
  });
}

function initTabs() {
  document.querySelectorAll('#pp-tabs .pp-tab').forEach((tab) => {
    tab.addEventListener('click', () => showTab(tab.dataset.tab));
  });
  // Prose that points at another tab should move the reader there rather than
  // reload the page at an anchor.
  document.querySelectorAll('.pp-inline-tab').forEach((link) => {
    link.addEventListener('click', () => showTab(link.dataset.goto));
  });
  window.addEventListener('hashchange', () => {
    const id = location.hash.slice(1);
    if (id && id !== state.tab) showTab(id);
  });
  showTab(location.hash.slice(1) || 'composition');
}

/* ---- the collapsible deck --------------------------------------------------
 *
 * Five controls is a tall thing to scroll past on the way to a figure, so the
 * grid folds away. Only the grid: the chip row and the count stay in the head,
 * so a collapsed deck still says what it is filtering.
 */
function initDeck() {
  const deck = document.getElementById('filter-deck');
  const toggle = document.getElementById('filters-toggle');
  const body = document.getElementById('filters-body');

  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!open));
    deck.classList.toggle('is-collapsed', open);
    body.hidden = open;
  });

  document.getElementById('filters-reset').addEventListener('click', () => {
    state.filters = [];
    // Rebuilding the deck from the manifest is how every widget returns to its
    // own default; tracking a reset path per control kind would be five places
    // to forget one.
    mountControls();
    const frame = document.querySelector('#embedded-control iframe');
    // Depictio's own widget holds its selection inside the frame, where this
    // page cannot reach it. Reloading it is the only honest way to clear it.
    if (frame) frame.src = frame.src;
    renderActiveFilters();
    redrawAll();
  });
}

/* ---- a table this page draws itself ----------------------------------------
 *
 * `format=data` returns {columns, rows, total}, which is to a table what
 * `format=json` is to a figure: the content, without Depictio's rendering of it.
 * The markup below is ordinary portal table markup, so the result matches the
 * rest of the page rather than sitting in a frame with its own fonts and its own
 * scrollbar.
 *
 * Paging is the caller's: the response carries `total` and the window it served,
 * and the pager below asks for the next window. Nothing is cached client-side,
 * because a filter can change the row set under any page.
 */
async function loadTable(spec) {
  const host = document.querySelector(`[data-table="${spec.key}"]`);
  if (!host) return;

  if (!spec.component) {
    host.replaceChildren(unresolvedNote(spec));
    return;
  }

  const filters = filtersFor();
  const dashboard = DASHBOARDS[spec.dashboard];
  const start = (state.pages[spec.key] || 0) * spec.pageSize;
  const url = exportUrl(state.apiBase, {
    dashboard,
    component: spec.component,
    format: 'data',
    filters,
    start,
    limit: spec.pageSize,
  });

  host.classList.add('is-loading');
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    renderTable(host, spec, payload, { url, etag: response.headers.get('etag'), filters, dashboard });
  } catch (error) {
    host.replaceChildren(
      Object.assign(document.createElement('div'), {
        className: 'pp-error',
        textContent: `The table could not be loaded. ${error}`,
      }),
    );
  } finally {
    host.classList.remove('is-loading');
  }
}

function renderTable(host, spec, payload, { url, etag, filters, dashboard }) {
  const columns = payload.columns || [];
  const rows = payload.rows || [];
  const total = payload.total || 0;
  const numeric = new Set(spec.numeric || []);

  const table = document.createElement('table');
  table.className = 'pp-table pp-datatable';
  table.innerHTML =
    '<thead><tr>' +
    columns
      .map(
        (column) =>
          `<th${numeric.has(column.field) ? ' class="pp-num"' : ''}>` +
          `${escapeHtml(column.headerName || column.field)}</th>`,
      )
      .join('') +
    '</tr></thead><tbody></tbody>';

  const body = table.querySelector('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = columns
      .map((column) => {
        const value = row[column.field];
        const isNumber = numeric.has(column.field) && typeof value === 'number';
        // Four significant digits reads better than seventeen; the exact value
        // stays available as a title, because rounding in a report should never
        // be the only copy of the number.
        const text = isNumber ? value.toPrecision(4) : String(value ?? '');
        return (
          `<td${isNumber ? ' class="pp-num"' : ''}` +
          `${isNumber ? ` title="${escapeHtml(String(value))}"` : ''}>` +
          `${escapeHtml(text)}</td>`
        );
      })
      .join('');
    body.appendChild(tr);
  }

  const page = state.pages[spec.key] || 0;
  const pages = Math.max(1, Math.ceil(total / spec.pageSize));
  const first = total === 0 ? 0 : page * spec.pageSize + 1;
  const last = Math.min(total, page * spec.pageSize + rows.length);

  const pager = document.createElement('div');
  pager.className = 'pp-pager';
  const label = document.createElement('span');
  label.textContent = total
    ? `${first} to ${last} of ${total} rows`
    : 'no rows match the current filters';
  const previous = document.createElement('button');
  previous.type = 'button';
  previous.className = 'pp-linkbutton';
  previous.textContent = '‹ previous';
  previous.disabled = page === 0;
  const next = document.createElement('button');
  next.type = 'button';
  next.className = 'pp-linkbutton';
  next.textContent = 'next ›';
  next.disabled = page >= pages - 1;
  for (const [button, delta] of [[previous, -1], [next, 1]]) {
    button.addEventListener('click', () => {
      state.pages[spec.key] = (state.pages[spec.key] || 0) + delta;
      loadTable(spec);
    });
  }
  pager.append(label, previous, next);

  const foot = document.createElement('div');
  foot.className = 'pp-panel-foot';
  const method = document.createElement('span');
  method.className = 'pp-method';
  const status = document.createElement('span');
  status.className = 'pp-status';
  status.textContent = filters.length
    ? `${total} rows · ${filters.length} filter${filters.length === 1 ? '' : 's'} applied`
    : `${total} rows · unfiltered`;
  const unmatched = (payload.meta || {}).unmatched_filter_columns;
  if (unmatched && unmatched.length) status.textContent += ` · ignored: ${unmatched.join(', ')}`;
  const inapplicable = notApplicableTo(spec.dc);
  if (inapplicable.length) {
    status.textContent += ` · not in this collection: ${inapplicable.join(', ')}`;
  }
  foot.append(method, status);
  methodBadge(method, 'data');

  const req = document.createElement('div');
  req.className = 'pp-req';
  req.appendChild(
    deliveryDetails({
      method: 'data',
      url,
      params: {
        format: 'data',
        dashboard,
        component: spec.component,
        start: String(state.pages[spec.key] * spec.pageSize),
        limit: String(spec.pageSize),
        filters: filters.length ? JSON.stringify(filters) : '(none)',
        returned: `${rows.length} of ${total} rows`,
      },
      meta: payload.meta,
      etag,
      label: 'How these rows were fetched',
    }),
  );

  // Wide content scrolls inside its own box; a table with eight columns must
  // not be what makes the whole page scroll sideways.
  const scroller = document.createElement('div');
  scroller.className = 'pp-tablewrap';
  scroller.appendChild(table);

  host.replaceChildren(scroller, pager, foot, req);
}

/* ---- framed components -----------------------------------------------------
 *
 * A card is a styled number and a table is AG Grid, so `format=html` is not a
 * fallback for these: it is the only form they have. Both mount when their tab
 * is first opened. Each frame is a full Depictio bundle, so three of them
 * behind a tab nobody clicked would be three downloads nobody asked for.
 */
function mountOverviewCards() {
  const host = document.getElementById('overview-cards');
  if (!host) return;
  host.replaceChildren(...CARDS.map(buildCardCell));
}

/* A framed component that can change URL without ever showing a hole.
 *
 * Navigating the frame in place avoids the white flash of a freshly inserted
 * element, but only up to the moment the incoming document commits: from then
 * on the frame paints its own empty canvas and stays empty for as long as
 * several megabytes of self-contained bundle take to boot. So the new URL is
 * loaded in a second frame stacked invisibly over the live one, and the two
 * trade places only once it has loaded. The reader keeps the previous number
 * on screen until there is a new one to put there, and a load that never
 * finishes leaves the old one up rather than a blank.
 */
function frameStack({ title, className = '' }) {
  const stack = document.createElement('div');
  stack.className = `pp-frame-stack ${className}`.trim();

  const build = (url) => {
    const frame = document.createElement('iframe');
    frame.title = title;
    // A frame on a tab nobody has opened is not near any viewport, so it does
    // not load and does not swap; it does both when that tab is shown.
    frame.loading = 'lazy';
    frame.dataset.url = url;
    frame.src = url;
    return frame;
  };

  stack.show = (url) => {
    if (stack.dataset.wanted === url) return;
    stack.dataset.wanted = url;

    if (!stack.firstElementChild) {
      stack.appendChild(build(url));
      return;
    }

    const next = build(url);
    next.classList.add('is-incoming');
    next.addEventListener(
      'load',
      () => {
        // Two quick filter changes leave two frames in flight and they can
        // finish out of order, so only the one still being asked for is
        // promoted; the other drops itself here.
        if (next.dataset.url !== stack.dataset.wanted) {
          next.remove();
          return;
        }
        for (const other of [...stack.children]) if (other !== next) other.remove();
        next.classList.remove('is-incoming');
      },
      { once: true },
    );
    stack.appendChild(next);
  };

  return stack;
}

function buildCardCell(card) {
  const cell = document.createElement('div');
  cell.className = 'pp-card';

  if (!card.component) {
    cell.appendChild(unresolvedNote(card));
    return cell;
  }

  const dashboard = DASHBOARDS[card.dashboard || 'community'];

  const stack = frameStack({ title: card.label });

  const foot = document.createElement('div');
  foot.className = 'pp-panel-foot';
  const method = document.createElement('span');
  method.className = 'pp-method';
  foot.appendChild(method);
  methodBadge(method, 'html');

  const req = document.createElement('div');
  req.className = 'pp-req';

  cell.update = () => {
    const filters = filtersFor();
    const url = exportUrl(state.apiBase, {
      dashboard,
      component: card.component,
      format: 'html',
      filters,
    });
    stack.show(url);
    req.replaceChildren(
      deliveryDetails({
        method: 'html',
        url,
        params: {
          format: 'html',
          dashboard,
          component: card.component,
          component_type: 'card',
          filters: filters.length ? JSON.stringify(filters) : '(none)',
          note: 'a card has no Plotly form, so json is not offered for it',
        },
        label: 'How this card was fetched',
      }),
    );
  };
  cell.update();

  cell.append(stack, foot, req);
  return cell;
}

/* The tables, mounted into the `data-frame` slot their tab declares. */
function mountFrame(spec) {
  const host = document.querySelector(`[data-frame="${spec.key}"]`);
  if (!host) return;

  if (!spec.component) {
    host.replaceChildren(unresolvedNote(spec));
    return;
  }

  const stack = frameStack({ title: spec.title, className: 'pp-component-stack' });
  stack.style.height = `${spec.height}px`;

  const foot = document.createElement('div');
  foot.className = 'pp-panel-foot';
  const method = document.createElement('span');
  method.className = 'pp-method';
  const status = document.createElement('span');
  status.className = 'pp-status';
  status.textContent = spec.title;
  foot.append(method, status);
  methodBadge(method, 'html');

  const req = document.createElement('div');
  req.className = 'pp-req';

  // Same contract as a card's: everything that depends on the filters, and
  // nothing else, so a filter change navigates this frame instead of replacing
  // it. See `refreshFramed`.
  host.update = () => {
    const filters = filtersFor();
    const url = exportUrl(state.apiBase, {
      dashboard: DASHBOARDS[spec.dashboard],
      component: spec.component,
      format: 'html',
      filters,
    });
    stack.show(url);
    req.replaceChildren(
      deliveryDetails({
        method: 'html',
        url,
        params: {
          format: 'html',
          dashboard: DASHBOARDS[spec.dashboard],
          component: spec.component,
          component_type: 'table',
          filters: filters.length ? JSON.stringify(filters) : '(none)',
          note: 'a table is AG Grid, not Plotly, so json is not offered for it',
        },
        label: 'How this table was fetched',
      }),
    );
  };
  host.update();

  host.replaceChildren(stack, foot, req);
}

/* ---- the manifests, as a table ---------------------------------------------
 *
 * The one request a host makes before it knows anything about a dashboard, for
 * both of the dashboards this page draws from. The two columns that matter are
 * published rather than inferred: which formats a component supports, and why
 * not, when it does not.
 */
function mountComponentTable() {
  const host = document.getElementById('component-table');
  if (!host) return;

  const sections = [
    {
      dashboard: 'community',
      label: 'Community & Diversity',
      note: 'composition figures, cards, tables and every control in the deck',
      manifest: state.manifest,
    },
    {
      dashboard: 'ampliseq',
      label: 'Pipeline QC (ampliseq)',
      note: "the pipeline's MultiQC report, one module per component",
      manifest: state.qcManifest,
    },
  ];

  const nodes = [];
  for (const section of sections) {
    const caption = document.createElement('h5');
    caption.className = 'pp-table-caption';
    caption.textContent = `${section.label} · ${section.manifest.length} components`;

    const note = document.createElement('p');
    note.className = 'pp-table-note';
    note.textContent = section.note;

    const table = document.createElement('table');
    table.className = 'pp-table';
    table.innerHTML =
      '<thead><tr><th>Component</th><th>Type</th><th>Exports as</th>' +
      '<th>Why not JSON</th><th></th></tr></thead><tbody></tbody>';
    const tbody = table.querySelector('tbody');

    for (const entry of section.manifest) {
      const formats = entry.formats || [];
      const row = document.createElement('tr');
      row.innerHTML =
        `<td><b>${escapeHtml(entry.title || '(untitled)')}</b>` +
        `<div class="pp-mono">${escapeHtml(entry.component_id)}</div></td>` +
        `<td>${escapeHtml(entry.component_type)}` +
        (entry.viz_kind ? `<div class="pp-mono">${escapeHtml(entry.viz_kind)}</div>` : '') +
        '</td>' +
        `<td>${formats
          .map((f) => `<span class="pp-badge pp-badge-${escapeHtml(f)}">${escapeHtml(f)}</span>`)
          .join(' ')}</td>` +
        `<td class="pp-reason">${escapeHtml(entry.json_unavailable_reason || '')}</td>`;

      const actions = document.createElement('td');
      actions.className = 'pp-actions';
      for (const format of ['json', 'data']) {
        if (!formats.includes(format)) continue;
        const link = document.createElement('a');
        link.href = exportUrl(state.apiBase, {
          dashboard: DASHBOARDS[section.dashboard],
          component: entry.component_id,
          format,
        });
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = format === 'json' ? 'spec' : 'rows';
        actions.appendChild(link);
      }
      if (formats.includes('html')) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'pp-linkbutton';
        button.textContent = 'frame it';
        button.addEventListener('click', () => frameComponent(entry, section.dashboard));
        actions.appendChild(button);
      }
      row.appendChild(actions);
      tbody.appendChild(row);
    }

    nodes.push(caption, note, table);
  }

  host.replaceChildren(...nodes);
}

/* One frame slot, not one per row: each frame is a full Depictio bundle, and
 * thirty of them at once is how a page exhausts the browser's per-origin WebGL
 * budget and starts rendering "WebGL is not supported" instead of figures. */
function frameComponent(entry, dashboardKey) {
  const host = document.getElementById('component-frame');
  if (!host) return;
  const dashboard = DASHBOARDS[dashboardKey];
  const url = exportUrl(state.apiBase, {
    dashboard,
    component: entry.component_id,
    format: 'html',
  });

  const frame = document.createElement('iframe');
  frame.src = url;
  frame.className = 'pp-component-frame';
  frame.title = entry.title || entry.component_id;

  const foot = document.createElement('div');
  foot.className = 'pp-panel-foot';
  const method = document.createElement('span');
  method.className = 'pp-method';
  const status = document.createElement('span');
  status.className = 'pp-status';
  status.textContent = entry.title || entry.component_id;
  foot.append(method, status);
  methodBadge(method, 'html');

  const req = document.createElement('div');
  req.className = 'pp-req';
  req.appendChild(
    deliveryDetails({
      method: 'html',
      url,
      params: {
        format: 'html',
        dashboard,
        component: entry.component_id,
        component_type: entry.component_type,
      },
      label: 'How this component was fetched',
    }),
  );

  host.replaceChildren(frame, foot, req);
  host.hidden = false;
  frame.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function init() {
  const site = await (await fetch(API_HINT)).json();
  state.apiBase = site.apiBase;
  DASHBOARDS.community = dashboardId(site, 'community');
  DASHBOARDS.ampliseq = dashboardId(site, 'ampliseq');
  mountSharedNav(site.pages, { backHref: '/', backLabel: 'index' });

  const manifestUrl = (dashboard) =>
    `${state.apiBase}/export/dashboards/${dashboard}/components` +
    '?include_filter_options=true&include_columns=true';

  // Both manifests up front: they are small, and the component table needs each
  // of them anyway. The components they describe are what stays lazy.
  const [manifest, qcManifest] = await Promise.all([
    fetch(manifestUrl(DASHBOARDS.community)).then((response) => response.json()),
    fetch(manifestUrl(DASHBOARDS.ampliseq)).then((response) => response.json()),
  ]);
  state.manifest = manifest;
  state.qcManifest = qcManifest;
  for (const entry of [...manifest, ...qcManifest]) {
    if (entry.dc_id && entry.dc_columns) state.columns[entry.dc_id] = entry.dc_columns;
  }

  bindComponents();
  mountControls();
  initDeck();

  // Depictio's own control covers the one column the rebuilt deck does not, so
  // the two approaches complement rather than fight over a column.
  const covered = new Set(CONTROLS.map((spec) => spec.column));
  state.spare = manifest.find(
    (entry) =>
      entry.component_type === 'interactive' &&
      entry.filter &&
      entry.filter.column_name &&
      !covered.has(entry.filter.column_name),
  );

  renderActiveFilters();
  // Mounts the opening tab's content and draws its figures; the other tabs draw
  // when they are first opened.
  initTabs();
}

init().catch((err) => {
  const banner = document.getElementById('active-filters');
  if (banner) banner.textContent = `failed: ${err.message}`;
});
