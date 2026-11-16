/**
 * The report host of the static runtime: which placeholder of a rendered
 * Quarto report the runtime may fill, and with what.
 *
 * One manifest contract, two hosts. The bundle host (`static.html`) mounts the
 * whole viewer App; the report host mounts the same renderers into the tiles
 * a Quarto export laid out (`<div data-depictio-tile="<tab_id>:<index>">`,
 * written by `notebook_export/generator.py`). Each placeholder already holds
 * the export's own output for that tile (a native renderer, a snapshot, a
 * code cell's figure) as its fallback; the runtime only replaces it when it
 * can draw the same thing, at the same state:
 *
 *   - `live` / `partial` tiles are recomputed in the page from the bundled
 *     data, under the report's filters — so they open on the exported state
 *     (`initial_filters`) and follow the filter panel;
 *   - a `frozen` tile is a payload computed at the dashboard's DEFAULT state.
 *     It replaces the fallback only when the report opens on that state (no
 *     initial filter); otherwise the fallback, computed at the exported state,
 *     is the honest one and stays;
 *   - `omitted` tiles, and anything the manifest does not hold, keep the
 *     fallback.
 *
 * Pure (no DOM, no React) so the rules are unit-tested here and read the same
 * from the runtime and from the tests.
 */
import type { BundleManifest } from './manifest';

/** Attribute naming the component(s) a placeholder shows: `<tab_id>:<index>`,
 *  several separated by whitespace (a row of cards is one placeholder). */
export const REPORT_TILE_ATTR = 'data-depictio-tile';
/** Attribute of the filter-panel placeholder; its value is the entry tab id. */
export const REPORT_FILTERS_ATTR = 'data-depictio-filters';
/** `<script type="application/json">` holding the manifest in a report. */
export const REPORT_MANIFEST_ID = 'depictio-report-manifest';
/** `<script type="application/json">` holding the report's look (brand). */
export const REPORT_CONFIG_ID = 'depictio-report-config';
/** Set on a placeholder once the runtime drew it; its fallback is then hidden. */
export const REPORT_MOUNTED_ATTR = 'data-depictio-mounted';

export interface TileRef {
  tabId: string;
  index: string;
}

/** `"<tab>:<index> <tab>:<index>"` → refs; malformed entries are dropped. */
export function parseTileRefs(value: string | null | undefined): TileRef[] {
  if (!value) return [];
  const refs: TileRef[] = [];
  for (const token of value.trim().split(/\s+/)) {
    const at = token.indexOf(':');
    if (at <= 0 || at === token.length - 1) continue;
    refs.push({ tabId: token.slice(0, at), index: token.slice(at + 1) });
  }
  return refs;
}

export type MountVerdict = { mount: true } | { mount: false; reason: string };

interface DocComponent {
  index?: unknown;
  component_type?: unknown;
}

function tabDoc(manifest: BundleManifest, tabId: string): Record<string, unknown> | null {
  const tabs = manifest.tabs ?? [];
  if (tabs.length === 0) {
    return manifest.dashboard.id === tabId ? manifest.dashboard.doc : null;
  }
  return tabs.find((t) => t.id === tabId)?.doc ?? null;
}

/** The component a ref names, from its own tab's document. */
export function componentFor(
  manifest: BundleManifest,
  ref: TileRef,
): Record<string, unknown> | null {
  const doc = tabDoc(manifest, ref.tabId);
  const meta = (doc?.stored_metadata as DocComponent[] | undefined) ?? [];
  return (meta.find((m) => String(m.index ?? '') === ref.index) as Record<string, unknown>) ?? null;
}

/** Whether the runtime replaces this tile's fallback, and if not, why. */
export function tileMountVerdict(manifest: BundleManifest, ref: TileRef): MountVerdict {
  if (!tabDoc(manifest, ref.tabId)) {
    return { mount: false, reason: `tab ${ref.tabId} is not in the bundled family` };
  }
  const component = componentFor(manifest, ref);
  if (!component) {
    return { mount: false, reason: `component ${ref.index} is not in tab ${ref.tabId}` };
  }
  const tier = manifest.tiers?.[ref.index];
  if (!tier) return { mount: false, reason: 'the manifest gives it no tier' };
  if (tier.tier === 'omitted') {
    return { mount: false, reason: tier.detail || 'omitted from the bundle' };
  }
  if (tier.tier === 'frozen' && (manifest.initial_filters?.length ?? 0) > 0) {
    return {
      mount: false,
      reason:
        "frozen at the dashboard's default state, and the report opens on another; " +
        'the export drew it at that state',
    };
  }
  return { mount: true };
}

/** A placeholder of several tiles (a card row) mounts whole or not at all:
 *  its fallback is one output, so half of it cannot be replaced. */
export function groupMountVerdict(manifest: BundleManifest, refs: TileRef[]): MountVerdict {
  if (refs.length === 0) return { mount: false, reason: 'the placeholder names no component' };
  for (const ref of refs) {
    const verdict = tileMountVerdict(manifest, ref);
    if (!verdict.mount) return { mount: false, reason: `${ref.index}: ${verdict.reason}` };
  }
  return { mount: true };
}

/** The colours a tab's tiles resolve categories against (`CategoryColorSource`
 *  in depictio-react-core): its own `category_colors`, over the main tab's as
 *  `inherited_category_colors`, with the brand fields riding along. The viewer
 *  gets the inherited half from the API (`/dashboards/get`); a report reads
 *  both halves from the manifest's tab documents. Null when the tab is not in
 *  the bundle. */
export function reportCategorySource(
  manifest: BundleManifest,
  tabId: string,
): Record<string, unknown> | null {
  const doc = tabDoc(manifest, tabId);
  if (!doc) return null;
  const tabs = manifest.tabs ?? [];
  const main = tabs.find((t) => t.is_main_tab)?.doc ?? (tabs.length ? tabs[0].doc : null);
  const inherited =
    main && main !== doc ? (main.category_colors as Record<string, unknown> | null) : null;
  return {
    category_colors: doc.category_colors ?? null,
    inherited_category_colors: doc.inherited_category_colors ?? inherited ?? null,
    brand_theme: doc.brand_theme ?? null,
    inherited_brand_theme:
      doc.inherited_brand_theme ?? (main !== doc ? main?.brand_theme : null) ?? null,
  };
}

/** The style a map draws its basemap with: Plotly's `map` subplot (MapLibre)
 *  or the older `mapbox` one. */
const MAP_SUBPLOTS = ['map', 'mapbox'] as const;

/** A frozen map's figure is drawn on a blank `white-bg` style, so a bundle
 *  opened with no network shows no broken tiles. A report is a web page read
 *  online, beside the export's own Quarto map, which keeps the dashboard's
 *  basemap: the mounted map gets the dashboard's `map_style` back (as long as
 *  the author set one). Returns how many maps it restored; mutates `manifest`. */
export function restoreReportBasemaps(manifest: BundleManifest): number {
  let restored = 0;
  const styleOf = new Map<string, string>();
  const docs = (manifest.tabs ?? []).length
    ? (manifest.tabs ?? []).map((t) => t.doc)
    : [manifest.dashboard.doc];
  for (const doc of docs) {
    for (const m of (doc?.stored_metadata as Record<string, unknown>[] | undefined) ?? []) {
      const style = m.map_style;
      if (
        m.component_type === 'map' &&
        typeof style === 'string' &&
        style &&
        style !== 'white-bg'
      ) {
        styleOf.set(String(m.index ?? ''), style);
      }
    }
  }
  for (const [index, entry] of Object.entries(manifest.frozen ?? {})) {
    const style = styleOf.get(index);
    const layout = (entry?.payload?.figure as { layout?: Record<string, unknown> } | undefined)
      ?.layout;
    if (!style || !layout) continue;
    for (const key of MAP_SUBPLOTS) {
      const sub = layout[key] as Record<string, unknown> | undefined;
      if (sub && typeof sub === 'object' && sub.style === 'white-bg') {
        sub.style = style;
        restored += 1;
      }
    }
  }
  return restored;
}

/** A filter section spec, as far as the report's panel reads one. */
export interface ReportSectionSpec {
  name: string;
  collapsed?: boolean | null;
  [key: string]: unknown;
}

/** The filter panel's sections, compact for a report: every section folded,
 *  except one holding a filter that is narrowing the exported view, which the
 *  reader should see without a click. Sections the panel would only infer
 *  from its components' `section` (a section's own filter bar on the
 *  dashboard) are declared here too, so they fold as well. */
export function compactPanelSections(
  specs: readonly ReportSectionSpec[] | null | undefined,
  components: readonly { index?: unknown; section?: unknown }[],
  activeIndexes: ReadonlySet<string>,
  extraSpecs: readonly ReportSectionSpec[] = [],
): ReportSectionSpec[] {
  const active = new Set<string>();
  for (const c of components) {
    if (typeof c.section === 'string' && activeIndexes.has(String(c.index ?? ''))) {
      active.add(c.section);
    }
  }
  const out: ReportSectionSpec[] = [];
  const seen = new Set<string>();
  const add = (spec: ReportSectionSpec) => {
    if (!spec?.name || seen.has(spec.name)) return;
    seen.add(spec.name);
    out.push({ ...spec, collapsed: !active.has(spec.name) });
  };
  for (const spec of specs ?? []) add(spec);
  for (const spec of extraSpecs) {
    if (!components.some((c) => c.section === spec.name)) continue;
    // A grid section's look (`appearance`, `card_variant`, its bar) is the
    // grid's; in the panel it reads as one more filter section.
    const { name, icon, color, description } = spec;
    add({ name, icon, color, description });
  }
  return out;
}
