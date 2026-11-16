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

/** A background-only MapLibre style: no source, no glyphs, no network. */
export function blankStyle(theme: ThemeName): Record<string, unknown> {
  const colour = theme === 'dark' ? DEFAULT_THEME.colors.dark[7] : DEFAULT_THEME.white;
  return {
    version: 8,
    name: 'depictio-offline-blank',
    sources: {},
    layers: [{ id: 'blank-bg', type: 'background', paint: { 'background-color': colour } }],
  };
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

/** Theme the frozen map's basemap, then swap it for a blank one if its host
 *  cannot be reached. Returns a new payload; the manifest stays pristine. */
export async function withReachableBasemap<
  T extends { figure?: { data?: unknown[]; layout?: Record<string, unknown> } },
>(payload: T, theme: ThemeName): Promise<T> {
  const layout = { ...(payload.figure?.layout ?? {}) };
  for (const key of MAP_SUBPLOTS) {
    const sub = layout[key];
    if (sub === null || typeof sub !== 'object') continue;
    const subplot = { ...(sub as Record<string, unknown>) };
    const name = themedMapStyle(subplot.style, theme);
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
        subplot.style = {
          ...probe,
          metadata: {
            ...((probe.metadata as Record<string, unknown> | undefined) ?? {}),
            [STYLE_NAME_KEY]: name,
          },
        };
      }
    }
    layout[key] = subplot;
  }
  return { ...payload, figure: { ...(payload.figure ?? {}), layout } };
}
