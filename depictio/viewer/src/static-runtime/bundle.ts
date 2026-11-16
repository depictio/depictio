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
  return summariesFromTabs(bundledTabs(), rawBundle().project?.id ?? null);
}

/** A string field of a tab document, blank and non-strings read as unset. */
function docString(doc: Record<string, unknown>, key: string): string | undefined {
  const v = doc[key];
  return typeof v === 'string' && v.trim() ? v : undefined;
}

/** The entry's own field when the manifest has it, the document's otherwise.
 *  `null` on the entry is an answer (the producer read the field and found it
 *  unset); only a manifest written before the field existed (`undefined`)
 *  falls back to the document — which carries the same stored field. */
function entryOrDoc(
  entry: string | null | undefined,
  doc: Record<string, unknown>,
  key: string,
): string | undefined {
  if (entry === undefined) return docString(doc, key);
  return entry ?? undefined;
}

/**
 * Every field the server's tab list (`/dashboards/list?include_child_tabs=true`)
 * gives the rail, built from the bundled family. Main tab first, then
 * `tab_order` — the order `bundledTabs()` already sorts by.
 *
 * Read by the Sidebar, the Paper rail and the tab links of text tiles:
 *   - `tab_group` draws the rail's sections (missing, the rail was flat);
 *   - `main_tab_name` names the main pill (else the dashboard's title);
 *   - `tab_icon` is the only place a CHILD tab takes an image icon from — the
 *     MultiQC logo — so without it the MultiQC tab fell back to a generic
 *     chart glyph, in the rail and in every `[MultiQC](tab:MultiQC)` link;
 *   - `subtitle` describes a tab in its links; `show_guide` / `guide_intro`
 *     (main tab only) set the Guide up the way the server's list does.
 */
export function summariesFromTabs(
  tabs: TabEntry[],
  projectId: string | null = null,
): DashboardSummary[] {
  if (tabs.length === 0) return [];
  const main = tabs.find((t) => t.is_main_tab) ?? tabs[0];
  return tabs.map((t) => {
    const doc = (t.doc ?? {}) as Record<string, unknown>;
    const isMain = t.id === main.id;
    const tabIcon = entryOrDoc(t.tab_icon, doc, 'tab_icon');
    const summary: DashboardSummary = {
      dashboard_id: t.id,
      title: t.title || docString(doc, 'title'),
      // App derives the family (and the Sidebar "is this the main tab?" test)
      // from this field, so the main tab must carry a null parent.
      parent_dashboard_id: isMain ? null : main.id,
      tab_order: t.tab_order,
      main_tab_name: isMain ? entryOrDoc(t.main_tab_name, doc, 'main_tab_name') : undefined,
      tab_group: isMain ? null : (entryOrDoc(t.tab_group, doc, 'tab_group') ?? null),
      tab_icon: tabIcon,
      tab_icon_color: entryOrDoc(t.tab_icon_color, doc, 'tab_icon_color'),
      // `icon` is the dashboard-level one on the server list. The entry's
      // `icon` is "tab icon, else dashboard icon", so the document's own
      // field is the faithful read; the entry's is the fallback for a
      // document that does not carry it.
      icon: docString(doc, 'icon') ?? t.icon ?? undefined,
      icon_color: docString(doc, 'icon_color') ?? t.icon_color ?? undefined,
      subtitle: entryOrDoc(t.subtitle, doc, 'subtitle'),
    };
    if (projectId) summary.project_id = projectId;
    if (isMain) {
      if (typeof doc.show_guide === 'boolean') summary.show_guide = doc.show_guide;
      const intro = docString(doc, 'guide_intro');
      if (intro) summary.guide_intro = intro;
    }
    return summary;
  });
}

/** Frozen payload for a component index; throws a readable error on a miss.
 *
 *  A miss has two very different causes and the reader deserves to be told
 *  which. Usually the producer decided this component could not be included at
 *  all — it is `omitted` in the manifest, with a `detail` naming the reason —
 *  and the renderer that mounted anyway would otherwise show "no frozen newick
 *  payload", which reads as a bug in the bundle rather than as a component the
 *  export could not carry. Only a genuinely inconsistent manifest (a tier that
 *  claims frozen with nothing behind it) falls through to the internal wording.
 */
export function frozenPayload<T>(componentIndex: string, kind: string): T {
  const entry = bundle().frozen[componentIndex];
  if (!entry) {
    const tier = bundle().tiers?.[componentIndex];
    if (tier?.tier === 'omitted') {
      throw new Error(
        tier.detail
          ? `This view could not be included in the export: ${tier.detail}`
          : 'This view could not be included in the export.',
      );
    }
    throw new Error(`static bundle: no frozen ${kind} payload for "${componentIndex}"`);
  }
  return entry.payload as T;
}

export interface ComponentMeta {
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
export function familyMetadata(): ComponentMeta[] {
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
  return familyMetadata().find(
    (c) =>
      c.component_type === 'interactive' &&
      String(c.dc_id ?? '') === dcId &&
      (columnName === undefined || c.column_name === columnName),
  )?.index;
}
