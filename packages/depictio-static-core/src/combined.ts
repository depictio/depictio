/**
 * The combined file: one HTML holding a rendered Quarto report AND the full
 * interactive dashboard, behind a "Report | Dashboard" switch.
 *
 * The outer document is the report (its contents, prose, code, print); the
 * dashboard is the viewer App, opened in a same-origin iframe built on demand
 * from the runtime script and manifest already in the page. This module is
 * the part of that host with no DOM and no React, so it is unit-tested here:
 *
 *   - the shared filter state of the two views (`createFilterChannel`), held
 *     by the report's window and read by the dashboard through `parent`;
 *   - the deep links (`#dashboard`, `#dashboard/<tab>`, `#report/<anchor>`)
 *     and the choice of the view a file opens on (`landingView`);
 *   - scoping a stylesheet onto the runtime's roots (`scopeSelector`,
 *     `splitSelectorList`), which the report host applies in the page to the
 *     one unscoped stylesheet the file carries, and the report runtime's build
 *     applies at build time (`vite-plugins/scope-css.ts`).
 */

// ── Shared filter state ─────────────────────────────────────────────────────

/** The filter list as the viewer's filter store holds it (`InteractiveFilter[]`). */
export type SharedFilters = unknown[];

export type FilterListener = (filters: SharedFilters, source: string) => void;

/**
 * One filter state for two views of a file, possibly in two realms.
 *
 * The value is kept as JSON text: the dashboard's App lives in an iframe, and
 * handing it the report's arrays would mix two realms' objects (an
 * `instanceof Array` across them is false). Each reader parses its own copy.
 * A write equal to the current state notifies nobody, which is what stops two
 * views that echo each other's updates from looping.
 */
export interface FilterChannel {
  /** The current filters, or null while nobody has written any. */
  get(): SharedFilters | null;
  /** Replace the state; listeners other than `source` hear of it. Returns
   *  whether anything changed. */
  set(filters: SharedFilters, source: string): boolean;
  /** Listen for writes made by anybody but `source`. */
  subscribe(source: string, listener: FilterListener): () => void;
  /** The state the file opened on: "Back to the exported state" returns here. */
  initial(): SharedFilters | null;
}

export function createFilterChannel(initial: SharedFilters | null = null): FilterChannel {
  const initialText = initial == null ? null : JSON.stringify(initial);
  let text: string | null = initialText;
  const listeners = new Map<FilterListener, string>();
  return {
    get: () => (text == null ? null : (JSON.parse(text) as SharedFilters)),
    initial: () => (initialText == null ? null : (JSON.parse(initialText) as SharedFilters)),
    set(filters, source) {
      const next = JSON.stringify(filters ?? []);
      if (next === text) return false;
      text = next;
      for (const [listener, owner] of Array.from(listeners)) {
        if (owner === source) continue;
        try {
          listener(JSON.parse(next) as SharedFilters, source);
        } catch (err) {
          // One broken view must not stop the other from hearing the update.
          console.warn('[depictio] a filter listener failed', err);
        }
      }
      return true;
    },
    subscribe(source, listener) {
      listeners.set(listener, source);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/** The global a combined file's report window holds its host API under. */
export const COMBINED_HOST_GLOBAL = '__DEPICTIO_COMBINED__';

/** What the report window offers the dashboard iframe (and tests). */
export interface CombinedHostApi {
  filters: FilterChannel;
  /** Report view, scrolled to the tile showing `index` of `tabId`. False when
   *  the report holds no such tile. */
  showInReport(tabId: string, index?: string | null): boolean;
  /** Whether the report holds a tile for this component (or any, for a tab). */
  reportHas(tabId: string, index?: string | null): boolean;
  /** The tab the dashboard view should open on (read once, at its boot). */
  requestedTab?(): string | null;
  /** The dashboard view hands its controller over once it has booted. */
  attachDashboard?(controller: DashboardController): void;
}

/** What the dashboard view's App lets the report window drive. */
export interface DashboardController {
  currentTab(): string;
  /** False when `id` is not a tab of this file. */
  switchTab(id: string): boolean;
  onTabChange(cb: (id: string) => void): () => void;
}

/**
 * The combined host this window can reach: its own, or its parent's when it is
 * the dashboard iframe of a combined file. Null everywhere else (a plain
 * bundle, the server app), and when the parent is another origin.
 */
export function findCombinedHost(win: Window | null | undefined): CombinedHostApi | null {
  const candidates: Array<Window | null | undefined> = [win];
  try {
    if (win && win.parent && win.parent !== win) candidates.push(win.parent);
  } catch {
    /* cross-origin parent */
  }
  for (const w of candidates) {
    try {
      const api = (w as unknown as Record<string, unknown> | null)?.[COMBINED_HOST_GLOBAL];
      if (api && typeof api === 'object') return api as CombinedHostApi;
    } catch {
      /* cross-origin: no host */
    }
  }
  return null;
}

// ── Views and deep links ────────────────────────────────────────────────────

export type CombinedView = 'report' | 'dashboard';

export interface CombinedRoute {
  view: CombinedView;
  /** Dashboard view: the tab asked for (an id of the family). */
  tab?: string;
  /** Report view: the element id to scroll to. */
  anchor?: string;
}

export interface RouteTab {
  id: string;
  title?: string | null;
}

/** A tab's name in a link: lower case, words joined by `-`. */
export function tabSlug(title: string): string {
  return title
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function decode(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

/** The tab a link names, by id or by its title's slug; null when none. */
export function resolveTab(key: string, tabs: RouteTab[]): string | null {
  if (!key) return null;
  const exact = tabs.find((t) => t.id === key);
  if (exact) return exact.id;
  const slug = tabSlug(key);
  const byTitle = tabs.find((t) => t.title && tabSlug(t.title) === slug);
  return byTitle ? byTitle.id : null;
}

/**
 * What a location hash asks for, or null when it asks for nothing this host
 * owns (an empty hash, or a plain `#anchor` the report itself answers: the
 * contents list and the report's own links keep working as they always did).
 */
export function parseCombinedHash(hash: string, tabs: RouteTab[] = []): CombinedRoute | null {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!raw) return null;
  const [head, ...rest] = raw.split('/');
  const tail = decode(rest.join('/'));
  if (head === 'dashboard') {
    const tab = tail ? resolveTab(tail, tabs) : null;
    return tab ? { view: 'dashboard', tab } : { view: 'dashboard' };
  }
  if (head === 'report') {
    return tail ? { view: 'report', anchor: tail } : { view: 'report' };
  }
  return null;
}

/** The hash naming a route; tab ids are written as ids (titles can repeat). */
export function formatCombinedHash(route: CombinedRoute): string {
  if (route.view === 'dashboard') {
    return route.tab ? `#dashboard/${encodeURIComponent(route.tab)}` : '#dashboard';
  }
  return route.anchor ? `#report/${encodeURIComponent(route.anchor)}` : '#report';
}

/**
 * The view a file opens on: what its link asks for, else the reader's last
 * view of this file, else the one chosen at export.
 */
export function landingView(
  route: CombinedRoute | null,
  remembered: string | null | undefined,
  exportDefault: CombinedView = 'report',
): CombinedView {
  if (route) return route.view;
  if (remembered === 'report' || remembered === 'dashboard') return remembered;
  return exportDefault;
}

/** The storage key a file's last view is remembered under: one per export. */
export function viewMemoryKey(dashboardId: string, builtAt: string | null | undefined): string {
  return `depictio-combined-view:${dashboardId}:${builtAt ?? ''}`;
}

// ── Scoping a stylesheet onto the runtime's roots ───────────────────────────

const HEAD_ROOT = /^(?::root|html|body)(?![\w-])/i;
const HEAD_ELEMENT = /^(?:\*|[a-z][\w-]*|::)/i;

/**
 * One selector, rewritten onto `rootSelector`:
 *
 *   - `:root…`, `html…`, `body…` at its head become the root
 *     (`:root[data-chrome='glass'] .x` → `.root[data-chrome='glass'] .x`);
 *   - one that starts on an element, `*` or a pseudo-element gets the root in
 *     front (`*, ::before` → `.root *, .root ::before`; `a` → `.root a`);
 *   - everything that starts on a class, an id, an attribute or a
 *     pseudo-class is left alone: it only ever matches the runtime's markup.
 */
export function scopeSelector(selector: string, rootSelector: string): string {
  const s = selector.trim();
  if (!s) return s;
  if (HEAD_ROOT.test(s)) return s.replace(HEAD_ROOT, rootSelector);
  if (HEAD_ELEMENT.test(s)) return `${rootSelector} ${s}`;
  return s;
}

/** `a, :is(b, c), d` → `['a', ':is(b, c)', 'd']`: commas inside brackets,
 *  parentheses and strings do not split. */
export function splitSelectorList(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let start = 0;
  for (let i = 0; i < list.length; i++) {
    const ch = list[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1);
    else if (ch === ',' && depth === 0) {
      out.push(list.slice(start, i).trim());
      start = i + 1;
    }
  }
  out.push(list.slice(start).trim());
  return out.filter(Boolean);
}

/** A whole selector list scoped, duplicates dropped (`html, body` → one root). */
export function scopeSelectorList(list: string, rootSelector: string): string {
  const scoped = splitSelectorList(list).map((s) => scopeSelector(s, rootSelector));
  return Array.from(new Set(scoped)).join(', ');
}
