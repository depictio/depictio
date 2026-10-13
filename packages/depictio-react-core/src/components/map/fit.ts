/**
 * Framing a map inside the box it actually got.
 *
 * `render_map` fits against a guessed 600x400 viewport, because the server has
 * no idea who is rendering. A grid tile is close enough to that; a docked panel
 * is neither as wide nor anywhere near as tall, so the server's zoom comes back
 * about a level too tight and the outer points fall off the edge. The server
 * therefore ships the bounding box it fitted and MapRenderer redoes the same
 * arithmetic here against the container it measured.
 */

/** MapLibre's world is one 512px tile at zoom 0. */
const WORLD_TILE_PX = 512;

/**
 * What the server framed, as forwarded in `metadata.fit`: the bounding box of
 * everything it plotted plus the constants it fitted with. The constants ride
 * along on purpose, so the two ends of this cannot drift apart when one of
 * them is tuned — see `_fit_payload` in
 * depictio/api/v1/services/map/render.py.
 */
export interface MapFitSpec {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
  padding: number;
  maxZoom: number;
  singlePointZoom: number;
}

/** A fit we have handed Plotly, and the revision that made it stick. */
export interface AppliedFit {
  center: { lat: number; lon: number };
  zoom: number;
  revision: string;
}

export function parseMapFit(metadata: unknown): MapFitSpec | null {
  const fit = (metadata as { fit?: unknown } | undefined)?.fit;
  if (!fit || typeof fit !== 'object') return null;
  const raw = fit as Record<string, unknown>;
  const num = (key: string): number | null => {
    const value = raw[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  };
  const minLat = num('min_lat');
  const maxLat = num('max_lat');
  const minLon = num('min_lon');
  const maxLon = num('max_lon');
  if (minLat == null || maxLat == null || minLon == null || maxLon == null) return null;
  return {
    minLat,
    maxLat,
    minLon,
    maxLon,
    padding: num('padding') ?? 0.5,
    maxZoom: num('max_zoom') ?? 12,
    singlePointZoom: num('single_point_zoom') ?? 9,
  };
}

/** Web-Mercator ordinate of a latitude, halved and clamped to the projection's
 *  usable range. Same function as `_lat_rad` server-side and `latRad` in
 *  CoordinatesMapPreview. */
export function mercatorY(lat: number): number {
  const sin = Math.sin((lat * Math.PI) / 180);
  const y = Math.log((1 + sin) / (1 - sin)) / 2;
  return Math.max(Math.min(y, Math.PI), -Math.PI) / 2;
}

/** Inverse of `mercatorY`. */
export function latFromMercatorY(y: number): number {
  return (Math.asin(Math.tanh(y * 2)) * 180) / Math.PI;
}

/**
 * Center and zoom that frame `spec` inside a `widthPx` x `heightPx` drawing
 * area. The same fit the server does, run again against the box we measured
 * rather than the 600x400 it has to assume.
 *
 * The center is the middle of the *projected* latitude span: Mercator stretches
 * towards the poles, so the mean of two latitudes is not the latitude halfway
 * down the viewport, and the gap grows as the box gets shorter.
 *
 * The zoom keeps its fraction where the server floors it. Flooring is the
 * server hedging against a viewport it guessed at; with a measured one there
 * is nothing to hedge, and a floor here would throw away most of a level.
 */
export function computeMapFit(
  spec: MapFitSpec,
  widthPx: number,
  heightPx: number,
): { center: { lat: number; lon: number }; zoom: number } {
  const center = {
    lat: latFromMercatorY((mercatorY(spec.minLat) + mercatorY(spec.maxLat)) / 2),
    lon: (spec.minLon + spec.maxLon) / 2,
  };
  if (spec.minLat === spec.maxLat && spec.minLon === spec.maxLon) {
    return { center, zoom: spec.singlePointZoom };
  }
  const latFraction = (mercatorY(spec.maxLat) - mercatorY(spec.minLat)) / Math.PI;
  let lonDiff = spec.maxLon - spec.minLon;
  if (lonDiff < 0) lonDiff += 360;
  const lonFraction = lonDiff / 360;
  const latZoom = Math.log2(heightPx / WORLD_TILE_PX / (latFraction || Number.EPSILON));
  const lonZoom = Math.log2(widthPx / WORLD_TILE_PX / (lonFraction || Number.EPSILON));
  let zoom = Math.min(latZoom, lonZoom) - spec.padding;
  if (!Number.isFinite(zoom)) zoom = spec.singlePointZoom;
  return { center, zoom: Math.max(1, Math.min(zoom, spec.maxZoom)) };
}

/** Whether a recomputed fit is close enough to the applied one to leave alone.
 *  Below these thresholds the map would not move a pixel, and re-applying
 *  would cost a `uirevision` bump for nothing. */
export function sameFit(a: AppliedFit, b: { center: { lat: number; lon: number }; zoom: number }): boolean {
  return (
    Math.abs(a.zoom - b.zoom) < 0.01 &&
    Math.abs(a.center.lat - b.center.lat) < 1e-6 &&
    Math.abs(a.center.lon - b.center.lon) < 1e-6
  );
}

/**
 * Which layout key carries the live map subplot.
 *
 * `render_map` builds with the MapLibre constructors (px.scatter_map /
 * density_map / choropleth_map), so the subplot is `layout.map` and
 * `layout.mapbox` is only where a legacy figure would keep it. `map` is tested
 * first and not last because plotly.py serialises an empty `layout.mapbox`
 * alongside the real `layout.map`, and an empty object is truthy: keying off
 * `mapbox` first sends the fit to a subplot nothing draws, so the map silently
 * keeps the server's framing.
 */
export function mapSubplotKey(layout: Record<string, unknown> | undefined | null): 'map' | 'mapbox' {
  if (layout?.map) return 'map';
  if (layout?.mapbox) return 'mapbox';
  return 'map';
}
