/**
 * Access to the embedded bundle manifest for the static runtime.
 *
 * `main.tsx` parses the `<script id="bundle-manifest">` JSON onto
 * `window.__DEPICTIO_BUNDLE__` before anything else runs; the api shims read
 * it through `bundle()`. Keying rules mirror the manifest contract: frozen
 * payloads are keyed by component index (`StoredMetadata.index`), and
 * interactive lookups are resolved dc_id+column -> component index via the
 * dashboard document.
 *
 * Tab families (manifest `tabs`): a bundle carries EVERY tab's document, and
 * the runtime switches between them in place. `bundle()` therefore returns a
 * *view* of the manifest whose `dashboard` section is the active tab — every
 * existing `bundle().dashboard.doc` reader (fetchDashboard, the figure/table
 * dc_id lookups, …) follows the active tab without knowing tabs exist. Only
 * `dashboard` is per-tab: data_refs / tiers / frozen / bindings / prologues /
 * links are component- or dc-keyed and span the whole family.
 */
import { parseManifest, type BundleManifest, type TabEntry } from 'depictio-static-core';

import type { DashboardSummary } from '../../../../packages/depictio-react-core/src/api';

declare global {
  interface Window {
    __DEPICTIO_BUNDLE__?: BundleManifest;
  }
}

/** Tab currently rendered. Seeded from `dashboard.id`, moved by `setActiveTab`. */
let activeTabId: string | null = null;
/**
 * Memoized per-tab view. `bundle()` is called on every render-path lookup, so
 * the swapped-`dashboard` object is built once per tab switch rather than per
 * call — and callers that compare `bundle().dashboard.doc` by identity (the
 * shim's document cache) keep seeing one object per tab.
 */
let activeView: BundleManifest | null = null;

export function loadBundleFromDocument(): BundleManifest {
  const el = document.getElementById('bundle-manifest');
  const manifest = parseManifest(JSON.parse(el?.textContent || 'null'));
  window.__DEPICTIO_BUNDLE__ = manifest;
  activeTabId = manifest.dashboard.id;
  activeView = null;
  return manifest;
}

/** The manifest exactly as the producer wrote it — entry tab, never swapped. */
export function rawBundle(): BundleManifest {
  const manifest = window.__DEPICTIO_BUNDLE__;
  if (!manifest) {
    throw new Error('static runtime: bundle manifest not loaded (main.tsx must run first)');
  }
  return manifest;
}

/** The manifest with `dashboard` pointing at the tab currently being shown. */
export function bundle(): BundleManifest {
  const raw = rawBundle();
  if (!activeTabId || activeTabId === raw.dashboard.id) return raw;
  if (activeView && activeView.dashboard.id === activeTabId) return activeView;
  const tab = bundledTabs().find((t) => t.id === activeTabId);
  if (!tab) return raw;
  activeView = { ...raw, dashboard: { id: tab.id, title: tab.title, doc: tab.doc } };
  return activeView;
}

/**
 * The family's tabs, main tab first then by `tab_order`. Empty for a
 * single-tab bundle (and for manifests written before the field existed).
 */
export function bundledTabs(): TabEntry[] {
  const tabs = rawBundle().tabs ?? [];
  return [...tabs].sort((a, b) => {
    if (a.is_main_tab !== b.is_main_tab) return a.is_main_tab ? -1 : 1;
    return (a.tab_order ?? 0) - (b.tab_order ?? 0);
  });
}

/** True when `/dashboard/<id>` is a tab this bundle can render in place. */
export function isBundledTab(id: string): boolean {
  const raw = rawBundle();
  return id === raw.dashboard.id || (raw.tabs ?? []).some((t) => t.id === id);
}

/** Id of the tab currently on screen. */
export function currentTabId(): string {
  return activeTabId ?? rawBundle().dashboard.id;
}

/**
 * Point the runtime at another tab of the family. Callers must re-render App
 * afterwards (main.tsx remounts it): `extractDashboardId()` reads the global
 * once per render and is not reactive.
 */
export function setActiveTab(id: string): void {
  if (!isBundledTab(id)) return;
  activeTabId = id;
  // App has no /dashboard/<id> route to read on file:// or a static host —
  // extractDashboardId() falls back to this global.
  window.__DEPICTIO_STATIC_DASHBOARD_ID__ = id;
}

/**
 * The family in the shape `fetchAllDashboards()` returns, so the left rail
 * builds its pills from the manifest exactly as it does from the API list.
 * Empty for a single-tab bundle — the rail then renders as it does today.
 */
export function tabSummaries(): DashboardSummary[] {
  const tabs = bundledTabs();
  if (tabs.length === 0) return [];
  const main = tabs.find((t) => t.is_main_tab) ?? tabs[0];
  return tabs.map((t) => ({
    dashboard_id: t.id,
    title: t.title,
    // App derives the family (and the Sidebar "is this the main tab?" test)
    // from this field, so the main tab must carry a null parent.
    parent_dashboard_id: t.id === main.id ? null : main.id,
    tab_order: t.tab_order,
    icon: t.icon ?? undefined,
    icon_color: t.icon_color ?? undefined,
  }));
}

/** Frozen payload for a component index; throws a readable error on a miss. */
export function frozenPayload<T>(componentIndex: string, kind: string): T {
  const entry = bundle().frozen[componentIndex];
  if (!entry) {
    throw new Error(`static bundle: no frozen ${kind} payload for "${componentIndex}"`);
  }
  return entry.payload as T;
}

interface ComponentMeta {
  index?: string;
  component_type?: string;
  interactive_component_type?: string;
  dc_id?: string | null;
  column_name?: string;
  [key: string]: unknown;
}

/**
 * Every component of the family, active tab first.
 *
 * Family-wide because a component declared on one tab can drive another: a
 * floating map filters every tab, so its (dc_id, column) must resolve from
 * whichever tab is on screen. Component indices are uuids and never collide
 * across tabs; active-first ordering keeps the on-screen component winning
 * whenever two tabs declare the same (dc_id, column) pair.
 */
function storedMetadata(): ComponentMeta[] {
  const activeDoc = bundle().dashboard.doc as { stored_metadata?: ComponentMeta[] };
  const own = activeDoc.stored_metadata ?? [];
  const tabs = rawBundle().tabs ?? [];
  if (tabs.length === 0) return own;
  const seen = new Set(own.map((c) => String(c.index ?? '')));
  const rest: ComponentMeta[] = [];
  for (const tab of tabs) {
    const meta = (tab.doc as { stored_metadata?: ComponentMeta[] }).stored_metadata ?? [];
    for (const c of meta) {
      const index = String(c.index ?? '');
      if (seen.has(index)) continue;
      seen.add(index);
      rest.push(c);
    }
  }
  return [...own, ...rest];
}

/** Resolve an interactive component's index from the (dc_id, column) its
 *  renderer passes to fetchUniqueValues / fetchColumnRange / fetchSpecs. */
export function interactiveIndexFor(dcId: string, columnName?: string): string | undefined {
  return storedMetadata().find(
    (c) =>
      c.component_type === 'interactive' &&
      String(c.dc_id ?? '') === dcId &&
      (columnName === undefined || c.column_name === columnName),
  )?.index;
}
