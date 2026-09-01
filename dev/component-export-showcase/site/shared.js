/* Shared helpers for every showcase page.
 *
 * Two things every page needs and should not each reimplement: the export URL
 * builder (one place that knows the parameter surface), and the collapsible
 * request-details panel that makes a figure's provenance inspectable.
 *
 * Loaded as a classic script, not a module, so a page can drop in a <script>
 * tag with no build step — which is the point being demonstrated.
 */

/* Single source of truth for the export parameter surface. Every page builds
 * its URLs through here, so adding a parameter is one edit and no page can
 * silently disagree about the contract. */

/* Dashboard ids, resolved by title server-side and delivered in /site-data.json.
 *
 * Pages must not hardcode an ObjectId: it is minted at import, so re-seeding a
 * dashboard changes it and every page pinning the old one 404s — with a
 * well-formed request, so nothing looks wrong until a panel is simply missing.
 * Component ids *are* safe to hardcode; they are the YAML tags.
 *
 * Throws rather than returning undefined, because `.../dashboards/undefined/...`
 * fails later and further from the cause.
 */
// Which script seeds which dashboard. The `bench_*` ones are imported from YAML
// by seed_benchmark_dashboards.py; the rest come from a reference project's
// `.db_seeds/*.json` at db_init time, so the fix there is to seed the project,
// not to run that script.
const SEEDED_BY = {
  bench_ci: 'python seed_benchmark_dashboards.py',
  bench_confusion: 'python seed_benchmark_dashboards.py',
  bench_pr: 'python seed_benchmark_dashboards.py',
  bench_roc: 'python seed_benchmark_dashboards.py',
};

function dashboardId(site, name) {
  const id = (site.dashboards || {})[name];
  if (!id) {
    const fix = SEEDED_BY[name]
      || 'seed the reference project this dashboard belongs to (db_init / /reseed)';
    throw new Error(`Dashboard "${name}" is not seeded on this instance. Fix: ${fix}`);
  }
  return id;
}

function exportUrl(apiBase, { dashboard, component, format = 'json', theme = 'light',
                             filters = null, controls = null, expectVersion = null,
                             start = null, limit = null } = {}) {
  const params = new URLSearchParams({ format, theme });
  if (filters && filters.length) params.set('filters', JSON.stringify(filters));
  if (controls && Object.keys(controls).length) params.set('controls', JSON.stringify(controls));
  if (expectVersion != null) params.set('expect_version', String(expectVersion));
  // `format=data` only: which page of a table's rows. Sent only when asked for,
  // so every other format's URL is unchanged and still cache-shares with itself.
  if (start != null) params.set('start', String(start));
  if (limit != null) params.set('limit', String(limit));
  return `${apiBase}/export/dashboards/${dashboard}/components/${component}?${params}`;
}

/* Render the URL with its query keys highlighted, so the parameter surface is
 * legible rather than one long opaque string. */
function highlightUrl(url) {
  const [base, query] = String(url).split('?');
  if (!query) return escapeHtml(base);
  const parts = query.split('&').map((pair) => {
    const [key, ...rest] = pair.split('=');
    const value = decodeURIComponent(rest.join('='));
    return `<span class="k">${escapeHtml(key)}</span>=<span class="v">${escapeHtml(value)}</span>`;
  });
  return `${escapeHtml(base)}?<wbr>${parts.join('&amp;<wbr>')}`;
}

/**
 * Collapsible "how this figure was fetched" panel.
 *
 * @param {object} opts
 * @param {string} opts.url        the request that produced the figure
 * @param {object} [opts.params]   the parameters, spelled out
 * @param {object} [opts.meta]     the response's `meta` block
 * @param {string} [opts.etag]     the response ETag
 * @param {string} [opts.label]    summary text
 * @returns {HTMLDetailsElement}
 */
function requestDetails({ url, params = {}, meta = null, etag = null, label = 'Request details' }) {
  const details = document.createElement('details');
  details.className = 'req';

  const rows = Object.entries(params)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(
      ([key, value]) =>
        `<div class="row"><span>${escapeHtml(key)}</span><span>${escapeHtml(
          typeof value === 'string' ? value : JSON.stringify(value),
        )}</span></div>`,
    )
    .join('');

  // Provenance is what distinguishes "fetched live" from "pasted here", so it
  // is shown even when the caller passes no params.
  const provenance = meta
    ? [
        ['dashboard', `v${meta.dashboard_version ?? '?'}`],
        ['saved', meta.last_saved_ts || '—'],
        ['contract', meta.export_contract || '—'],
        ['etag', etag || meta.etag || '—'],
        ['fetched', meta.generated_at || '—'],
        ['filtered', String(Boolean(meta.filter_applied))],
      ]
        .map(
          ([key, value]) =>
            `<div class="row"><span>${escapeHtml(key)}</span><span>${escapeHtml(value)}</span></div>`,
        )
        .join('')
    : '';

  details.innerHTML = `
    <summary>${escapeHtml(label)}</summary>
    <div class="req-body">
      <div class="req-line"><b>GET</b><div class="req-url">${highlightUrl(url)}</div></div>
      ${rows ? `<div class="req-line"><b>params</b><div class="req-params">${rows}</div></div>` : ''}
      ${provenance ? `<div class="req-line"><b>response</b><div class="req-params">${provenance}</div></div>` : ''}
      <button class="req-copy" type="button">copy url</button>
    </div>`;

  const copy = details.querySelector('.req-copy');
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(url);
      copy.textContent = 'copied';
    } catch {
      // Clipboard is permission-gated and unavailable over plain http on some
      // browsers; say so rather than appearing to have worked.
      copy.textContent = 'copy blocked — select manually';
    }
    setTimeout(() => {
      copy.textContent = 'copy url';
    }, 1800);
  });

  return details;
}

/* Nav shared by every sub-page, with a link back to the landing page. */
function mountSharedNav(pages, { backHref = '/', backLabel = 'index' } = {}) {
  const host = document.getElementById('sitenav');
  if (!host) return;
  const here = location.pathname.replace(/\/$/, '') || '/';
  const links = (pages || [])
    .map((page) => {
      const current = (page.href.replace(/\/$/, '') || '/') === here;
      return `<li><a href="${page.href}"${current ? ' aria-current="page"' : ''}>${escapeHtml(
        page.label,
      )}</a></li>`;
    })
    .join('');
  host.innerHTML = `<ul>
    <li><a class="backlink" href="${backHref}">← ${escapeHtml(backLabel)}</a></li>
    ${links}
  </ul>`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch],
  );
}
