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
