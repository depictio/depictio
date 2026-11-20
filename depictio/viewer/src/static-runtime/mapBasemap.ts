/**
 * A frozen map's basemap in a static bundle: the dashboard's own, when the
 * reader can reach it, and a blank background in the reader's theme when not.
 *
 * Producers freeze maps with the component's `map_style` (see
 * `depictio/serverless/maps.py`), so OpenStreetMap / Carto tiles draw like
 * they do on the instance whenever the bundle is opened online. Offline is the
 * case this module exists for. Plotly hands MapLibre a Carto style as a URL,
 * and MapLibre adds the trace layers only once that style has loaded: with no
 * network the style never loads, so the map would lose its MARKERS, not just
 * its tiles. So before the figure reaches Plotly, the basemap host is probed
 * once per page (the Carto style.json itself, or one OpenStreetMap tile);
 * unreachable → the style is replaced by an inline background-only
 * style that needs no network at all, and the markers draw on it.
 *
 * A probe that succeeds inlines the style document it fetched (see
 * `withReachableBasemap` for why), keeping the style's name in its metadata
 * for the basemap picker; an OpenStreetMap style is inline already and keeps
 * its name. Tiles that fail later
 * (a flaky connection) only reach MapLibre's error event, which Plotly turns
 * into a rejected promise that react-plotly.js catches: the markers stay.
 *
 * The probe only ever contacts `BASEMAP_HOSTS`, the hosts the styles below
 * reach anyway (mirrored by `BASEMAP_HOSTS` in `depictio/serverless/maps.py`
 * and allowed, and only they, by the e2e offline map spec).
 */
import { DEFAULT_THEME } from '@mantine/core';

import type { ThemeName } from './mantinePlotlyTemplate';

export const BASEMAP_HOSTS: readonly string[] = [
  'basemaps.cartocdn.com',
  'tiles.basemaps.cartocdn.com',
  'tiles-a.basemaps.cartocdn.com',
  'tiles-b.basemaps.cartocdn.com',
  'tiles-c.basemaps.cartocdn.com',
  'tiles-d.basemaps.cartocdn.com',
  'tile.openstreetmap.org',
];

const CARTO = 'https://basemaps.cartocdn.com/gl';
/** The style URL plotly.js resolves each network style name to
 *  (`src/plots/map/constants.js`, plotly.js 2.35). */
const STYLE_URLS: Record<string, string> = {
  'carto-positron': `${CARTO}/positron-gl-style/style.json`,
  'carto-darkmatter': `${CARTO}/dark-matter-gl-style/style.json`,
  'carto-voyager': `${CARTO}/voyager-gl-style/style.json`,
  'carto-positron-nolabels': `${CARTO}/positron-nolabels-gl-style/style.json`,
  'carto-darkmatter-nolabels': `${CARTO}/dark-matter-nolabels-gl-style/style.json`,
  'carto-voyager-nolabels': `${CARTO}/voyager-nolabels-gl-style/style.json`,
  basic: `${CARTO}/voyager-gl-style/style.json`,
  streets: `${CARTO}/voyager-gl-style/style.json`,
  outdoors: `${CARTO}/voyager-gl-style/style.json`,
  light: `${CARTO}/positron-gl-style/style.json`,
  dark: `${CARTO}/dark-matter-gl-style/style.json`,
  // An inline raster style: it loads offline, but every tile errors, and the
  // probe says so before the reader sees a grey void.
  'open-street-map': 'https://tile.openstreetmap.org/0/0/0.png',
};

const MAP_SUBPLOTS = ['map', 'mapbox'] as const;
/** `layout.map.style` when the figure sets none (plotly.js 2.35). */
const PLOTLY_DEFAULT_STYLE = 'basic';
const PROBE_TIMEOUT_MS = 4000;
/** Where an inlined style keeps the name it was resolved from (read back by
 *  `MapRenderer`'s basemap picker). */
export const STYLE_NAME_KEY = 'depictio:style';

/** `render_map`'s theme rule (`services/map/render.py`), applied in the
 *  browser: the payload was frozen under the light theme. */
export function themedMapStyle(style: unknown, theme: ThemeName): unknown {
  if (theme === 'dark' && (style === 'open-street-map' || style === 'carto-positron')) {
    return 'carto-darkmatter';
  }
  if (theme !== 'dark' && style === 'carto-darkmatter') return 'carto-positron';
  return style;
}

/** The URL whose reachability decides whether `style` can draw, or null when
 *  it needs no network (`white-bg`, an inline style object). */
export function probeUrlFor(style: unknown): string | null {
  if (typeof style !== 'string') return null;
  if (STYLE_URLS[style]) return STYLE_URLS[style];
  return /^https?:\/\//.test(style) ? style : null;
}

/** The one source a blank style carries: an empty, inline GeoJSON. */
export const BLANK_SOURCE_ID = 'depictio-blank';

/**
 * A background-only MapLibre style: no glyphs, no tiles, no network.
 *
 * `sources` must never be an empty object. On every update after the first,
 * Plotly carries the old full layout over with `relinkPrivateKeys`, which
 * deletes any plain object left empty — and `map.style` is the user's own
 * object, held by reference. The style then reached MapLibre's `setStyle`
 * without `sources` ("missing required property"), MapLibre fired `error`,
 * and Plotly rejected with `Error: Map error.` as a page error: the first
 * filter change after an offline open did it, on the floating map and on any
 * grid map alike. One inline, empty GeoJSON source keeps it non-empty.
 */
export function blankStyle(theme: ThemeName): Record<string, unknown> {
  const colour = theme === 'dark' ? DEFAULT_THEME.colors.dark[7] : DEFAULT_THEME.white;
  return {
    version: 8,
    name: 'depictio-offline-blank',
    sources: {
      [BLANK_SOURCE_ID]: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    },
    layers: [{ id: 'blank-bg', type: 'background', paint: { 'background-color': colour } }],
  };
}

/**
 * Drop the empty plain objects of an inlined style document, the ones Plotly
 * would delete on the next update anyway (see `blankStyle`), and give it a
 * `sources` entry if it would otherwise be left without one. Arrays are kept
 * as they are: MapLibre reads their positions.
 */
export function plotlySafeStyle(style: Record<string, unknown>): Record<string, unknown> {
  const prune = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(prune);
    if (value === null || typeof value !== 'object') return value;
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      const kept = prune(child);
      if (
        kept !== null &&
        typeof kept === 'object' &&
        !Array.isArray(kept) &&
        Object.keys(kept as Record<string, unknown>).length === 0
      ) {
        continue;
      }
      out[key] = kept;
    }
    return out;
  };
  const safe = prune(style) as Record<string, unknown>;
  if (!safe.sources) safe.sources = blankStyle('light').sources;
  return safe;
}

/** What a probe learned: the style document (a Carto style.json, fetched with
 *  CORS as MapLibre would), `true` for a reachable raster tile host, or `null`
 *  when the host did not answer. */
type Probe = Record<string, unknown> | true | null;

const probes = new Map<string, Promise<Probe>>();

/** Probe `url` once per page. */
export function probeBasemap(url: string): Promise<Probe> {
  let probe = probes.get(url);
  if (probe === undefined) {
    probe = runProbe(url);
    probes.set(url, probe);
  }
  return probe;
}

async function runProbe(url: string): Promise<Probe> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return null;
  if (typeof fetch !== 'function') return null;
  const controller = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS) : null;
  try {
    if (!url.endsWith('.json')) {
      // A raster tile: an opaque answer is enough to know the host is there.
      await fetch(url, { mode: 'no-cors', signal: controller?.signal });
      return true;
    }
    const res = await fetch(url, { signal: controller?.signal });
    if (!res.ok) return null;
    const style = (await res.json()) as unknown;
    return style !== null && typeof style === 'object' && !Array.isArray(style)
      ? (style as Record<string, unknown>)
      : null;
  } catch {
    return null;
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

/** True when a figure draws on a MapLibre subplot (`map` / legacy `mapbox`). */
export function hasMapSubplot(layout: Record<string, unknown> | undefined): boolean {
  return MAP_SUBPLOTS.some((key) => {
    const sub = layout?.[key];
    return sub !== null && typeof sub === 'object';
  });
}

/** Theme the frozen map's basemap, then swap it for a blank one if its host
 *  cannot be reached. Returns a new payload; the manifest stays pristine.
 *
 *  `retheme: false` is for a figure tile that happens to draw a map (a
 *  `px.scatter_map` in a code figure): the server never swaps its style by
 *  colour scheme, only `render_map` does, so only the reachability half
 *  applies. Every path that hands Plotly a map goes through here, or offline
 *  the style fetch fails and Plotly throws `Map error.`. */
export async function withReachableBasemap<
  T extends { figure?: { data?: unknown[]; layout?: Record<string, unknown> } },
>(payload: T, theme: ThemeName, { retheme = true }: { retheme?: boolean } = {}): Promise<T> {
  if (!hasMapSubplot(payload.figure?.layout)) return payload;
  const layout = { ...(payload.figure?.layout ?? {}) };
  for (const key of MAP_SUBPLOTS) {
    const sub = layout[key];
    if (sub === null || typeof sub !== 'object') continue;
    const subplot = { ...(sub as Record<string, unknown>) };
    // An unset style is Plotly's default, which is a network style too.
    const own = subplot.style ?? (key === 'map' ? PLOTLY_DEFAULT_STYLE : undefined);
    const name = retheme ? themedMapStyle(own, theme) : own;
    subplot.style = name;
    const url = probeUrlFor(name);
    if (url !== null) {
      const probe = await probeBasemap(url);
      if (probe === null) {
        subplot.style = blankStyle(theme);
      } else if (probe !== true) {
        // Hand MapLibre the document it would have fetched. A style URL loads
        // asynchronously, and plotly.js adds its trace sources on a second
        // `Plotly.react` without waiting for it ("Style is not done loading",
        // an uncaught rejection that drops the markers); an inline document
        // is in place by then. The name rides along for the basemap picker.
        subplot.style = plotlySafeStyle({
          ...probe,
          metadata: {
            ...((probe.metadata as Record<string, unknown> | undefined) ?? {}),
            [STYLE_NAME_KEY]: name,
          },
        });
      }
    }
    layout[key] = subplot;
  }
  return { ...payload, figure: { ...(payload.figure ?? {}), layout } };
}
