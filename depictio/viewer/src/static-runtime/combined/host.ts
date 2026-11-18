/**
 * The combined file's host: a rendered Quarto report that also holds the full
 * interactive dashboard, behind a "Report | Dashboard" switch.
 *
 * The page is the report. The dashboard is the viewer App, opened the first
 * time it is asked for in a same-origin iframe written from what the page
 * already holds: the runtime's script text, its stylesheet text, the manifest
 * and the add-ons. Nothing is stored twice in the file; Quarto's Bootstrap and
 * Mantine never share a document; Plotly and 3Dmol inject their styles into
 * the document they draw in.
 *
 * Between the two views: one filter state (`FilterChannel`, held here and read
 * by the iframe through `parent`), cross-links ("Open in dashboard" on each
 * report tile, "Show in report" on each dashboard tile and tab the report
 * holds), deep links (`#dashboard`, `#dashboard/<tab>`, `#report/<anchor>`),
 * the view a file opens on (chosen at export, then remembered per file), and
 * the colour scheme of the switch, which follows the view on screen.
 *
 * Plain DOM, no React: this is chrome around two documents, and the report's
 * own scripts (Quarto's, the export's fold script) own the rest of the page.
 */
import {
  COMBINED_HOST_GLOBAL,
  REPORT_CONFIG_ID,
  REPORT_MANIFEST_ID,
  REPORT_TILE_ATTR,
  componentFor,
  formatCombinedHash,
  landingView,
  parseCombinedHash,
  parseTileRefs,
  viewMemoryKey,
  type BundleManifest,
  type CombinedHostApi,
  type CombinedRoute,
  type CombinedView,
  type DashboardController,
  type FilterChannel,
  type RouteTab,
} from 'depictio-static-core';

/** Marks the runtime's script, stylesheet text and add-ons in a combined file. */
export const RUNTIME_ATTR = 'data-depictio-runtime';
/** Attribute of a report tab heading naming its dashboard tab. */
export const REPORT_TAB_ATTR = 'data-depictio-tab';

export interface CombinedConfig {
  /** The view a file opens on when its link names none (chosen at export). */
  default_view?: CombinedView;
}

interface HostOptions {
  manifest: BundleManifest;
  channel: FilterChannel;
  config: CombinedConfig;
}

function readJson<T>(id: string): T | null {
  try {
    const raw = document.getElementById(id)?.textContent;
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/** The combined section of the report's config (`depictio-report-config`). */
export function readCombinedConfig(): CombinedConfig {
  const config = readJson<{ combined?: CombinedConfig }>(REPORT_CONFIG_ID);
  return config?.combined ?? {};
}

function runtimeText(kind: 'js' | 'css'): string {
  return document.querySelector(`script[${RUNTIME_ATTR}="${kind}"]`)?.textContent ?? '';
}

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage blocked: the view is simply not remembered */
  }
}

const HOST_CSS = `
.dpx-dashboard-frame{position:fixed;inset:0;width:100%;height:100%;border:0;z-index:2147483000;
  background:#fff;visibility:hidden}
html.dpx-view-dashboard{overflow:hidden}
html.dpx-view-dashboard .dpx-dashboard-frame{visibility:visible}
.dpx-open-dashboard{display:inline-flex;align-items:center;gap:6px;margin-inline-end:8px}
.dpx-open-dashboard svg{width:14px;height:14px;flex:none}
.dpx-tile-links{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin:0 0 4px}
.dpx-tile-links .dpx-tile-open{all:unset;box-sizing:border-box;display:inline-flex;align-items:center;gap:5px;
  cursor:pointer;height:26px;padding:0 10px;border-radius:999px;
  font:600 12px/1 var(--dpx-font,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif);
  color:var(--gl-muted,#868e96);border:1px solid var(--gl-hair,rgba(33,37,41,.11));
  background:var(--gl-paper,#fff);transition:color .12s ease,background-color .12s ease}
.dpx-tile-links .dpx-tile-open svg{width:13px;height:13px;flex:none}
.dpx-tile-links .dpx-tile-open:hover{color:var(--gl-accent-fg,#1c7ed6);background:var(--gl-accent-soft,rgba(28,126,214,.08))}
.dpx-tile-links .dpx-tile-open:focus-visible{outline:2px solid var(--gl-accent,#228be6);outline-offset:2px}
.dpx-flash{animation:dpx-flash 1.6s ease-out 1}
@keyframes dpx-flash{0%,30%{box-shadow:0 0 0 3px rgba(34,139,230,.55)}100%{box-shadow:0 0 0 3px rgba(34,139,230,0)}}
@media print{.dpx-open-dashboard,.dpx-dashboard-frame,.dpx-tile-links{display:none!important}
  html.dpx-view-dashboard{overflow:visible}}
`;

/** Styles the host writes into the dashboard's document. */
const FRAME_CSS = `
html,body{margin:0}
.dpx-show-in-report{position:fixed;z-index:2147483000;display:none;cursor:pointer;
  font:500 12px/1 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:6px 10px;
  border-radius:999px;border:1px solid rgba(0,0,0,.12);background:rgba(255,255,255,.95);color:#1c7ed6;
  box-shadow:0 2px 8px rgba(0,0,0,.15)}
[data-mantine-color-scheme="dark"] .dpx-show-in-report{background:rgba(37,38,43,.95);
  color:#74c0fc;border-color:rgba(255,255,255,.14)}
.dpx-flash{animation:dpx-flash 1.6s ease-out 1}
@keyframes dpx-flash{0%,30%{box-shadow:0 0 0 3px rgba(34,139,230,.6)}100%{box-shadow:0 0 0 3px rgba(34,139,230,0)}}
`;

function escapeStyle(css: string): string {
  return css.replace(/<\/style/gi, '<\\/style');
}

/** The report's tile placeholders, by `<tab>:<index>`. */
function tileHosts(): Map<string, HTMLElement> {
  const out = new Map<string, HTMLElement>();
  for (const host of Array.from(document.querySelectorAll<HTMLElement>(`[${REPORT_TILE_ATTR}]`))) {
    const refs = parseTileRefs(host.getAttribute(REPORT_TILE_ATTR));
    // A stable anchor per tile (`#report/tile-<index>`), so a link to one
    // survives a reload; a highlight drawing the same tile twice keeps the
    // first.
    const anchor = refs[0] ? `tile-${refs[0].index}` : '';
    if (anchor && !host.id && !document.getElementById(anchor)) host.id = anchor;
    for (const ref of refs) {
      const key = `${ref.tabId}:${ref.index}`;
      if (!out.has(key)) out.set(key, host);
    }
  }
  return out;
}

/** The report's part for a dashboard tab: its heading (written with the tab's
 *  id since this host exists), else the section around the tab's first tile. */
function tabTarget(tabId: string, hosts: Map<string, HTMLElement>): HTMLElement | null {
  // The Quarto section a heading opens carries the heading's id: the anchor
  // the contents list links to, and the one a `#report/<anchor>` link names.
  const sectionOf = (heading: Element | null): HTMLElement | null => {
    const section = heading?.parentElement;
    return section && section.tagName === 'SECTION' && section.id ? section : null;
  };
  // The mark on the heading itself: Quarto copies a heading's markup into the
  // contents list (and the sticky contents keep it first in the document), so
  // the first match is a link in `#TOC`, which is no place to scroll to.
  const marks = Array.from(
    document.querySelectorAll<HTMLElement>(`[${REPORT_TAB_ATTR}="${CSS.escape(tabId)}"]`),
  );
  const mark =
    marks.find((m) => !m.closest('nav, #TOC, #quarto-margin-sidebar') && m.closest('h1,h2,h3,h4,h5,h6')) ??
    null;
  if (mark) {
    const heading = mark.closest('h1,h2,h3,h4,h5,h6');
    return sectionOf(heading) ?? (heading as HTMLElement | null) ?? mark;
  }
  for (const [key, host] of hosts) {
    if (!key.startsWith(`${tabId}:`)) continue;
    // The innermost Quarto section holding a tab heading (the export marks
    // those `data-dpx-kind="tab"`).
    let el: HTMLElement | null = host;
    while (el && el !== document.body) {
      if (el.tagName === 'SECTION') {
        const heading = el.querySelector(':scope > h1,:scope > h2,:scope > h3,:scope > h4');
        if (heading?.querySelector('[data-dpx-kind="tab"]')) return el;
      }
      el = el.parentElement;
    }
    return host;
  }
  return null;
}

/**
 * Open every fold of the report on the way to `el`, with the export's own
 * fold script: it opens folds for a click on any `a[href^="#"]` (in the
 * capture phase), so a click on a throwaway anchor to `el`'s id does it, and
 * the anchor's own default (moving the hash) is cancelled.
 */
function unfoldTo(el: HTMLElement): void {
  if (!el.id) return;
  const a = document.createElement('a');
  a.href = `#${el.id}`;
  a.hidden = true;
  a.addEventListener('click', (ev) => ev.preventDefault());
  document.body.appendChild(a);
  try {
    a.click();
  } finally {
    a.remove();
  }
}

function flash(el: Element): void {
  el.classList.remove('dpx-flash');
  void (el as HTMLElement).offsetWidth;
  el.classList.add('dpx-flash');
  window.setTimeout(() => el.classList.remove('dpx-flash'), 1800);
}

/** Wait (a few seconds at most) for `find` to return an element. */
function waitFor<T>(find: () => T | null, timeoutMs = 8000): Promise<T | null> {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      const hit = find();
      if (hit) return resolve(hit);
      if (Date.now() - start > timeoutMs) return resolve(null);
      window.setTimeout(tick, 80);
    };
    tick();
  });
}

export interface CombinedHost {
  api: CombinedHostApi;
  show(view: CombinedView, route?: CombinedRoute): void;
}

export function installCombinedHost({ manifest, channel, config }: HostOptions): CombinedHost {
  const style = document.createElement('style');
  style.setAttribute(RUNTIME_ATTR, 'host-css');
  style.textContent = HOST_CSS;
  document.head.appendChild(style);

  const tabs: RouteTab[] = (manifest.tabs ?? []).length
    ? (manifest.tabs ?? []).map((t) => ({ id: t.id, title: t.title }))
    : [{ id: manifest.dashboard.id, title: manifest.dashboard.title }];
  const memoryKey = viewMemoryKey(manifest.dashboard.id, manifest.built_at);
  const hosts = tileHosts();

  let view: CombinedView = 'report';
  let frame: HTMLIFrameElement | null = null;
  let controller: DashboardController | null = null;
  let pendingTab: string | null = null;
  let pendingTile: string | null = null;
  const whenAttached: Array<(c: DashboardController) => void> = [];

  // ── The way in ──────────────────────────────────────────────────────────
  // No floating control: the report gets a "Dashboard" button where Quarto
  // already puts its own ("</> Code", top right of the title), and the
  // dashboard gets a "Report" row in its rail (chrome/variants/glass,
  // `ReportRow`, through `showReport`).
  const GRID_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>';
  const openButton = document.createElement('button');
  openButton.type = 'button';
  openButton.className = 'btn code-tools-button dpx-open-dashboard';
  openButton.setAttribute(RUNTIME_ATTR, 'open-dashboard');
  openButton.title = 'Open the interactive dashboard: every tab, live filters, offline';
  openButton.innerHTML = GRID_ICON;
  openButton.append(document.createTextNode('Dashboard'));
  openButton.addEventListener('click', () => show('dashboard', undefined, true));
  const codeTools = document.getElementById('quarto-code-tools-source');
  const title = document.querySelector('#title-block-header h1.title, h1.title');
  if (codeTools?.parentElement) codeTools.parentElement.insertBefore(openButton, codeTools);
  else if (title) title.insertAdjacentElement('afterend', openButton);
  else document.body.prepend(openButton);

  const reportScheme = (): 'light' | 'dark' =>
    document.body.classList.contains('quarto-dark') ? 'dark' : 'light';
  const frameScheme = (): 'light' | 'dark' =>
    frame?.contentDocument?.documentElement.getAttribute('data-mantine-color-scheme') === 'dark'
      ? 'dark'
      : 'light';

  // The dashboard opens in the report's scheme and follows the report's
  // toggle while it is hidden; it shares the file's storage, and Mantine's
  // own manager reads its key and listens for `storage` events on it (as the
  // app's theme toggle replays one, `chrome/variants/glass/parts.tsx`).
  const MANTINE_SCHEME_KEY = 'mantine-color-scheme-value';
  function frameFollowsReport(): void {
    const scheme = reportScheme();
    const win = frame?.contentWindow as (Window & typeof globalThis) | null | undefined;
    if (!win || frameScheme() === scheme) return;
    storageSet(MANTINE_SCHEME_KEY, scheme);
    try {
      win.dispatchEvent(
        new win.StorageEvent('storage', {
          key: MANTINE_SCHEME_KEY,
          newValue: scheme,
          storageArea: win.localStorage,
        }),
      );
    } catch {
      /* storage blocked: the dashboard keeps its own scheme */
    }
  }
  new MutationObserver(frameFollowsReport).observe(document.body, {
    attributes: true,
    attributeFilter: ['class'],
  });

  function syncChrome(): void {
    document.documentElement.classList.toggle('dpx-view-dashboard', view === 'dashboard');
    if (frame) {
      frame.toggleAttribute('inert', view !== 'dashboard');
      frame.setAttribute('aria-hidden', String(view !== 'dashboard'));
    }
  }

  function setHash(route: CombinedRoute, push: boolean): void {
    const hash = formatCombinedHash(route);
    if (location.hash === hash) return;
    try {
      if (push) history.pushState(null, '', hash);
      else history.replaceState(null, '', hash);
    } catch {
      /* a document that cannot rewrite its URL keeps the old hash */
    }
  }

  // ── The dashboard view ──────────────────────────────────────────────────
  function buildFrame(): HTMLIFrameElement {
    storageSet(MANTINE_SCHEME_KEY, reportScheme());
    const el = document.createElement('iframe');
    el.className = 'dpx-dashboard-frame';
    el.title = 'Dashboard';
    el.setAttribute(RUNTIME_ATTR, 'dashboard-frame');
    document.body.appendChild(el);
    const doc = el.contentDocument!;
    const title = (manifest.dashboard.title || document.title || 'Dashboard').replace(/</g, '&lt;');
    doc.open();
    doc.write(
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width, initial-scale=1">' +
        '<meta name="color-scheme" content="light dark">' +
        `<title>${title}</title>` +
        `<style ${RUNTIME_ATTR}="app-css">${escapeStyle(runtimeText('css'))}</style>` +
        `<style ${RUNTIME_ATTR}="frame-css">${FRAME_CSS}</style>` +
        '</head><body><div id="root"></div></body></html>',
    );
    doc.close();
    // The manifest, the add-ons and the script: copied as DOM, not written as
    // markup, so 12 MB of script text is never re-parsed as HTML.
    const manifestEl = doc.createElement('script');
    manifestEl.type = 'application/json';
    manifestEl.id = 'bundle-manifest';
    manifestEl.textContent = document.getElementById(REPORT_MANIFEST_ID)?.textContent ?? 'null';
    doc.body.appendChild(manifestEl);
    for (const node of Array.from(
      document.querySelectorAll<HTMLScriptElement>(
        'script[data-depictio-addon], script[data-pya], script#depictio-pyodide-meta',
      ),
    )) {
      const copy = doc.createElement('script');
      for (const attr of Array.from(node.attributes)) copy.setAttribute(attr.name, attr.value);
      copy.textContent = node.textContent;
      doc.body.appendChild(copy);
    }
    const script = doc.createElement('script');
    script.setAttribute(RUNTIME_ATTR, 'js');
    script.textContent = runtimeText('js');
    doc.body.appendChild(script);
    // The switch follows the dashboard's scheme; a report that has a dark
    // theme of its own follows it too.
    new MutationObserver(() => {
      syncChrome();
      const toggle = (window as unknown as { quartoToggleColorScheme?: () => void })
        .quartoToggleColorScheme;
      if (toggle && view === 'dashboard' && frameScheme() !== reportScheme()) toggle();
    }).observe(doc.documentElement, {
      attributes: true,
      attributeFilter: ['data-mantine-color-scheme'],
    });
    installShowInReport(doc);
    return el;
  }

  /** "Show in report" over the dashboard tile under the pointer. */
  function installShowInReport(doc: Document): void {
    const chip = doc.createElement('button');
    chip.type = 'button';
    chip.className = 'dpx-show-in-report';
    chip.textContent = 'Show in report';
    chip.setAttribute(RUNTIME_ATTR, 'show-in-report');
    doc.body.appendChild(chip);
    let current: { tab: string; index: string; tile: HTMLElement } | null = null;
    const hide = () => {
      chip.style.display = 'none';
      current = null;
    };
    // The tile's bottom-right corner, kept on screen for a tile taller or
    // wider than the view.
    const place = (tile: HTMLElement) => {
      const r = tile.getBoundingClientRect();
      const view = doc.defaultView;
      const height = view?.innerHeight ?? r.bottom;
      if (r.bottom <= 0 || r.top >= height) return hide();
      const maxTop = height - 40;
      const maxLeft = (view?.innerWidth ?? r.right) - 136;
      chip.style.display = 'block';
      chip.style.top = `${Math.max(4, Math.min(r.bottom - 34, maxTop))}px`;
      chip.style.left = `${Math.max(4, Math.min(r.right - 128, maxLeft))}px`;
    };
    doc.addEventListener('mouseover', (ev) => {
      const target = ev.target as Element | null;
      if (!target || chip.contains(target)) return;
      const tile = target.closest?.('[data-component-index]') as HTMLElement | null;
      const index = tile?.getAttribute('data-component-index');
      const tab = controller?.currentTab();
      if (!tile || !index || !tab || !api.reportHas(tab, index)) return hide();
      if (current?.index === index) return;
      current = { tab, index, tile };
      place(tile);
    });
    // Any scroll (the page's, or a grid's or a table's inside it) moves the
    // tile, not the chip: follow it.
    doc.addEventListener(
      'scroll',
      () => {
        if (current) place(current.tile);
      },
      true,
    );
    chip.addEventListener('click', () => {
      if (current) api.showInReport(current.tab, current.index);
      hide();
    });
  }

  function onController(c: DashboardController): void {
    controller = c;
    c.onTabChange((id) => {
      if (view === 'dashboard') setHash({ view: 'dashboard', tab: id }, false);
      syncChrome();
    });
    for (const fn of whenAttached.splice(0)) fn(c);
    syncChrome();
  }

  function withController(fn: (c: DashboardController) => void): void {
    if (controller) fn(controller);
    else whenAttached.push(fn);
  }

  async function scrollToDashboardTile(index: string): Promise<void> {
    const doc = frame?.contentDocument;
    if (!doc) return;
    const sel = `[data-component-index="${CSS.escape(index)}"]`;
    const el = await waitFor(() => doc.querySelector<HTMLElement>(sel));
    if (!el) return;
    el.scrollIntoView({ block: 'center' });
    flash(el);
  }

  // ── Switching ───────────────────────────────────────────────────────────
  function show(next: CombinedView, route?: CombinedRoute, push = false): void {
    view = next;
    // The reader's own switches are remembered for this file; a link that
    // opened it on a view is not a choice.
    if (push) storageSet(memoryKey, next);
    if (next === 'dashboard') {
      if (route?.tab) pendingTab = route.tab;
      // `#dashboard/<tab>/<component>`: the tile is scrolled to and flashed.
      if (route?.component) pendingTile = route.component;
      if (!frame) frame = buildFrame();
      else if (route?.tab) withController((c) => c.switchTab(route.tab!));
      const tab = route?.tab ?? controller?.currentTab() ?? pendingTab ?? undefined;
      setHash(
        { view: 'dashboard', tab: tab ?? undefined, component: route?.component },
        push,
      );
      if (pendingTile) {
        const index = pendingTile;
        pendingTile = null;
        void scrollToDashboardTile(index);
      }
      frame.contentWindow?.focus();
    } else {
      setHash({ view: 'report', anchor: route?.anchor }, push);
      if (route?.anchor) {
        const el = document.getElementById(route.anchor);
        if (el) {
          unfoldTo(el);
          el.scrollIntoView({ block: 'start' });
        }
      }
    }
    syncChrome();
  }

  // ── Cross-links from the report ─────────────────────────────────────────
  // Each tile's action row: the report's own (its "i", written by the
  // export's chrome script) when it has one, so the tile keeps one row with
  // "Open in dashboard" first and the "i" at the end, as the dashboard orders
  // a tile's actions.
  for (const host of new Set(hosts.values())) {
    const refs = parseTileRefs(host.getAttribute(REPORT_TILE_ATTR));
    const ref = refs.find((r) => componentFor(manifest, r));
    if (!ref) continue;
    let row = host.querySelector<HTMLElement>(':scope > .dpx-tile-links');
    if (!row) {
      row = document.createElement('div');
      row.className = 'dpx-tile-links';
      host.insertBefore(row, host.firstChild);
    }
    row.setAttribute(RUNTIME_ATTR, 'tile-links');
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'dpx-tile-open';
    open.innerHTML = GRID_ICON;
    open.append(document.createTextNode('Open in dashboard'));
    open.title = 'Show this tile in the interactive dashboard';
    open.setAttribute('aria-label', 'Open this tile in the dashboard');
    open.addEventListener('click', () => {
      show('dashboard', { view: 'dashboard', tab: ref.tabId, component: ref.index }, true);
    });
    row.insertBefore(open, row.firstChild);
  }
  // The report's chrome script places what it owns in those rows (the "i",
  // the figures' anchors) whenever they change.
  document.dispatchEvent(new Event('dpx:tile-actions'));

  const api: CombinedHostApi = {
    filters: channel,
    reportHas(tabId, index) {
      if (index) return hosts.has(`${tabId}:${index}`);
      if (document.querySelector(`[${REPORT_TAB_ATTR}="${CSS.escape(tabId)}"]`)) return true;
      for (const key of hosts.keys()) if (key.startsWith(`${tabId}:`)) return true;
      return false;
    },
    showInReport(tabId, index) {
      const target = index ? (hosts.get(`${tabId}:${index}`) ?? null) : tabTarget(tabId, hosts);
      if (!target) return false;
      show('report', undefined, true);
      unfoldTo(target);
      // After the switch has given the page its scrollbar back.
      window.requestAnimationFrame(() => {
        target.scrollIntoView({ block: index ? 'center' : 'start' });
        flash(target);
        setHash({ view: 'report', anchor: target.id }, false);
      });
      return true;
    },
    showReport() {
      // The tab on screen when the report holds it, else the report's top.
      const tab = controller?.currentTab();
      if (tab && api.showInReport(tab, null)) return;
      show('report', undefined, true);
    },
    requestedTab: () => pendingTab,
    attachDashboard: onController,
  };
  (window as unknown as Record<string, unknown>)[COMBINED_HOST_GLOBAL] = api;

  // ── Deep links ──────────────────────────────────────────────────────────
  const route = parseCombinedHash(location.hash, tabs);
  const first = landingView(route, storageGet(memoryKey), config.default_view ?? 'report');
  if (first === 'dashboard') show('dashboard', route ?? { view: 'dashboard' });
  else if (route?.anchor) show('report', route);
  else syncChrome();


  const onLocation = () => {
    const next = parseCombinedHash(location.hash, tabs);
    // A plain `#anchor` (the contents list, a link in the text) is the
    // report's own: it brings the report back if the dashboard is up.
    if (!next) {
      if (view === 'dashboard') show('report');
      return;
    }
    if (next.view === 'dashboard' && view === 'dashboard' && next.tab) {
      if (next.tab !== controller?.currentTab()) withController((c) => c.switchTab(next.tab!));
      if (next.component) void scrollToDashboardTile(next.component);
      return;
    }
    show(next.view, next);
  };
  window.addEventListener('hashchange', onLocation);
  window.addEventListener('popstate', onLocation);

  return { api, show };
}
