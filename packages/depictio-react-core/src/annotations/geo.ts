/**
 * Annotations on a Plotly map (scattermap / choroplethmap traces on a
 * MapLibre subplot). A map has no x/y axis, and layout shapes and layout
 * annotations cannot be anchored in longitude / latitude, so every mark is an
 * overlay trace appended after the map's own ones (named like the cartesian
 * overlays, so click-to-edit and the inline editor work unchanged):
 *
 * - marked points: a translucent disc wider than the point (scattermap
 *   markers have no outline to ring them with), or, on a choropleth, the
 *   marked regions outlined and tinted by an overlay choroplethmap trace;
 * - the lassoed / boxed area: a `fill: 'toself'` polygon;
 * - notes: a dot with its numbered label.
 *
 * Labels are map text (MapLibre glyphs): the basemap fonts have no circled
 * digits, so a label is numbered `(n)`, and a text-only trace would get no
 * text offset, so labels ride on a transparent marker.
 *
 * Capture helpers turn the map's selection and click events into the same
 * geometries (`MarkedPoints` with `geo: true`, `GeoNote`). Pure: no React,
 * no DOM beyond the duck-typed subplot handed in.
 */
import type { Data } from 'plotly.js';

import type { AnnotationsToPlotlyResult } from './toPlotly';
import {
  DEFAULT_COLOR,
  DEFAULT_POINT_RING_WIDTH,
  DEFAULT_RANGE_OPACITY,
  OVERLAY_TRACE_PREFIX,
  POINT_MARKER_SIZE,
  PREVIEW_OPACITY_FACTOR,
  withAlpha,
} from './toPlotly';
import type { AnnotationStats } from './summary';
import { annotationHoverText } from './summary';
import { asPlainArray, customdataIds, customdataRow, isOverlayTraceName } from './layer';
import type {
  AnnotationColor,
  GeoNote,
  MarkedPoints,
  PointCoord,
  RenderableAnnotation,
  SelectionRegion,
} from './types';
import { MAX_LATITUDE, MAX_POINT_IDS, MAX_REGION_VERTICES } from './types';

// ---------------------------------------------------------------------------
// Coordinates
// ---------------------------------------------------------------------------

/** A longitude brought back into [-180, 180] (a panned map reports 190 for -170). */
export function wrapLongitude(lon: number): number {
  if (lon >= -180 && lon <= 180) return lon;
  const wrapped = ((((lon + 180) % 360) + 360) % 360) - 180;
  // 180 and -180 are the same meridian: keep the sign the caller had.
  return wrapped === -180 && lon > 0 ? 180 : wrapped;
}

function asLonLat(lon: unknown, lat: unknown): { lon: number; lat: number } | null {
  const a = typeof lon === 'string' && lon !== '' ? Number(lon) : lon;
  const b = typeof lat === 'string' && lat !== '' ? Number(lat) : lat;
  if (typeof a !== 'number' || typeof b !== 'number') return null;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return { lon: wrapLongitude(a), lat: Math.max(-MAX_LATITUDE, Math.min(MAX_LATITUDE, b)) };
}

// ---------------------------------------------------------------------------
// Capture
// ---------------------------------------------------------------------------

/** A point of a map `plotly_selected` / `plotly_click` / `plotly_hover` event. */
export interface GeoEventPoint {
  lon?: unknown;
  lat?: unknown;
  /** choroplethmap: the region's id (`locations` entry). */
  location?: unknown;
  customdata?: unknown;
  curveNumber?: number;
}

/**
 * The parts of a map `plotly_selected` event describing the selected area,
 * keyed by map subplot id (`map`, `map2`, legacy `mapbox`): `range` holds the
 * box's north-west and south-east corners as `[lon, lat]`, `lassoPoints` the
 * traced vertices.
 */
export interface GeoSelectionEvent {
  points?: GeoEventPoint[];
  range?: Record<string, unknown> | null;
  lassoPoints?: Record<string, unknown> | null;
}

/** The value of the first map subplot key of a `range` / `lassoPoints` object. */
function onMapSubplot(obj: Record<string, unknown> | null | undefined): unknown {
  if (!obj || typeof obj !== 'object') return undefined;
  const key = Object.keys(obj).find((k) => /^map(box)?\d*$/.test(k));
  return key ? obj[key] : undefined;
}

function lonLatPairs(value: unknown): Array<{ lon: number; lat: number }> | null {
  if (!Array.isArray(value)) return null;
  const out: Array<{ lon: number; lat: number }> = [];
  for (const pair of value) {
    if (!Array.isArray(pair)) return null;
    const p = asLonLat(pair[0], pair[1]);
    if (p) out.push(p);
  }
  return out;
}

/** At most `max` items, picked evenly so a long lasso keeps its outline. */
function thin<T>(values: T[], max: number): T[] {
  if (values.length <= max) return values;
  const step = values.length / max;
  return Array.from({ length: max }, (_, i) => values[Math.floor(i * step)]);
}

/**
 * The area a map selection covered, in degrees: a box (`x` = longitude,
 * `y` = latitude, ordered) or a lasso polygon. Null when the event carries
 * neither. A polygon drawn across the antimeridian is not split: its
 * longitudes are wrapped one by one.
 */
export function geoRegionFromSelection(ev: GeoSelectionEvent | null | undefined): SelectionRegion | null {
  if (!ev) return null;
  const box = lonLatPairs(onMapSubplot(ev.range));
  if (box && box.length >= 2) {
    const [a, b] = box;
    if (a.lon !== b.lon && a.lat !== b.lat) {
      return {
        shape: 'box',
        x0: Math.min(a.lon, b.lon),
        x1: Math.max(a.lon, b.lon),
        y0: Math.min(a.lat, b.lat),
        y1: Math.max(a.lat, b.lat),
      };
    }
  }
  const lasso = lonLatPairs(onMapSubplot(ev.lassoPoints));
  if (lasso && lasso.length >= 3) {
    const kept = thin(lasso, MAX_REGION_VERTICES);
    return { shape: 'lasso', x: kept.map((p) => p.lon), y: kept.map((p) => p.lat) };
  }
  return null;
}

/**
 * Where a map's point ids come from: a selection column's slot in each
 * point's customdata (scattermap), or the region id a choroplethmap reports
 * as `location`.
 */
export interface GeoIdSource {
  column: string;
  from: 'customdata' | 'location';
  /** customdata slot, for `from: 'customdata'`. Default 0. */
  slot?: number;
}

function asId(v: unknown): string | number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v !== '') return v;
  return null;
}

function pointId(p: GeoEventPoint, source: GeoIdSource): string | number | null {
  if (source.from === 'location') return asId(p.location);
  const slot = source.slot ?? 0;
  const row = customdataRow(p.customdata);
  return asId(Array.isArray(row) ? row[slot] : slot === 0 ? row : undefined);
}

/**
 * Marked points from a map `plotly_selected` event (overlay points already
 * stripped): ids when `ids` says where to read them and the points carry
 * them, else longitude / latitude coordinates. Deduped, capped at
 * MAX_POINT_IDS, the selected area kept as `region`. Null for an empty
 * selection.
 */
export function geoPointsFromSelection(
  ev: GeoSelectionEvent | null | undefined,
  ids?: GeoIdSource | null,
): MarkedPoints | null {
  const points = ev?.points ?? [];
  if (!points.length) return null;
  const region = geoRegionFromSelection(ev);
  const finish = (g: MarkedPoints): MarkedPoints => (region ? { ...g, geo: true, region } : { ...g, geo: true });

  if (ids?.column) {
    const out: Array<string | number> = [];
    const seen = new Set<string>();
    for (const p of points) {
      const id = pointId(p, ids);
      if (id == null) continue;
      const key = `${typeof id}:${id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(id);
      if (out.length >= MAX_POINT_IDS) break;
    }
    if (out.length) return finish({ kind: 'points', column: ids.column, ids: out });
  }

  const coords: PointCoord[] = [];
  const seen = new Set<string>();
  for (const p of points) {
    const pos = asLonLat(p.lon, p.lat);
    if (!pos) continue;
    const trace = typeof p.curveNumber === 'number' ? p.curveNumber : null;
    const key = `${trace}|${pos.lon}|${pos.lat}`;
    if (seen.has(key)) continue;
    seen.add(key);
    coords.push(trace == null ? { x: pos.lon, y: pos.lat } : { x: pos.lon, y: pos.lat, trace });
    if (coords.length >= MAX_POINT_IDS) break;
  }
  return coords.length ? finish({ kind: 'points', coords }) : null;
}

/** A note at a map position, or null when it is not one. */
export function geoNoteAt(lon: unknown, lat: unknown): GeoNote | null {
  const p = asLonLat(lon, lat);
  return p ? { kind: 'geo_note', lat: p.lat, lon: p.lon } : null;
}

/** The parts of Plotly's map subplot (`_fullLayout.map._subplot`) read here. */
export interface MapSubplotLike {
  map?: { unproject?: (point: [number, number]) => { lng: number; lat: number } } | null;
  div?: { getBoundingClientRect: () => { left: number; top: number; width: number; height: number } } | null;
}

/** The first map subplot of a graph div's `_fullLayout`, or null. */
export function mapSubplotOf(fullLayout: unknown): MapSubplotLike | null {
  const fl = fullLayout as
    | { _subplots?: Record<string, unknown>; [key: string]: unknown }
    | null
    | undefined;
  if (!fl) return null;
  for (const type of ['map', 'mapbox']) {
    const ids = fl._subplots?.[type];
    const id = Array.isArray(ids) ? ids[0] : undefined;
    const sub = typeof id === 'string' ? (fl[id] as { _subplot?: unknown } | undefined)?._subplot : undefined;
    if (sub && typeof sub === 'object') return sub as MapSubplotLike;
  }
  return null;
}

/**
 * Longitude / latitude under a click, through MapLibre's `unproject` on the
 * subplot's own div. Null outside the map or when the subplot cannot convert.
 */
export function pixelToLonLat(
  clientX: number,
  clientY: number,
  subplot: MapSubplotLike | null | undefined,
): { lon: number; lat: number } | null {
  const unproject = subplot?.map?.unproject;
  const rect = subplot?.div?.getBoundingClientRect();
  if (!unproject || !rect) return null;
  const px = clientX - rect.left;
  const py = clientY - rect.top;
  if (px < 0 || py < 0 || px > rect.width || py > rect.height) return null;
  const ll = unproject.call(subplot!.map, [px, py]);
  return ll ? asLonLat(ll.lng, ll.lat) : null;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/** A map trace in the shape `geoAnnotationsToPlotly` reads. */
export interface GeoTraceLike {
  lon?: unknown[];
  lat?: unknown[];
  /** One id per point: the selection id (scattermap) or the region id (choroplethmap). */
  ids?: unknown[];
  /** choroplethmap: what an overlay needs to outline the same regions. */
  regions?: { geojson: unknown; featureidkey?: unknown };
}

const isMapType = (t: unknown, prefix: string) => typeof t === 'string' && t.startsWith(prefix);

/**
 * The figure's map traces in the shape `geoAnnotationsToPlotly` reads,
 * decoded from Plotly's typed-array transport when needed. A choropleth
 * region is positioned at its centroid when `centroids` knows it (see
 * `geoCentroidsFromGraph`). Overlay traces are skipped; other trace types
 * are kept as empty entries so indexes follow the figure's.
 */
export function normalizeGeoTraces(
  data: unknown,
  slot: number,
  centroids?: ReadonlyMap<string, readonly [number, number]> | null,
): GeoTraceLike[] {
  if (!Array.isArray(data)) return [];
  const out: GeoTraceLike[] = [];
  for (const t of data as Array<Record<string, unknown> | null>) {
    if (!t || isOverlayTraceName(t.name)) continue;
    if (isMapType(t.type, 'choroplethmap')) {
      const locations = asPlainArray(t.locations) ?? [];
      out.push({
        ids: locations,
        lon: locations.map((l) => centroids?.get(String(l))?.[0]),
        lat: locations.map((l) => centroids?.get(String(l))?.[1]),
        regions: { geojson: t.geojson, featureidkey: t.featureidkey },
      });
    } else if (isMapType(t.type, 'scattermap')) {
      out.push({ lon: asPlainArray(t.lon), lat: asPlainArray(t.lat), ids: customdataIds(t.customdata, slot) });
    } else {
      out.push({});
    }
  }
  return out;
}

/**
 * Centroid of every choropleth region Plotly drew, by region id, read from
 * the graph div's `calcdata` (Plotly computes them for its own selection).
 * Null when the figure has no choropleth.
 */
export function geoCentroidsFromGraph(gd: unknown): Map<string, [number, number]> | null {
  const calcdata = (gd as { calcdata?: unknown } | null)?.calcdata;
  if (!Array.isArray(calcdata)) return null;
  let out: Map<string, [number, number]> | null = null;
  for (const cd of calcdata) {
    if (!Array.isArray(cd) || !cd.length) continue;
    const trace = (cd[0] as { trace?: { type?: unknown; name?: unknown } } | null)?.trace;
    if (!trace || !isMapType(trace.type, 'choroplethmap') || isOverlayTraceName(trace.name)) continue;
    out ??= new Map();
    for (const di of cd as Array<{ loc?: unknown; ct?: unknown } | null>) {
      const ct = di?.ct;
      if (di?.loc == null || !Array.isArray(ct)) continue;
      const p = asLonLat(ct[0], ct[1]);
      if (p) out.set(String(di.loc), [p.lon, p.lat]);
    }
  }
  return out;
}

/** A cheap key of a centroid map, to store it only when it changed. */
export function centroidsSignature(m: ReadonlyMap<string, readonly [number, number]> | null): string {
  if (!m) return '';
  let s = '';
  m.forEach((v, k) => {
    s += `${k}:${v[0].toFixed(4)},${v[1].toFixed(4)};`;
  });
  return s;
}

export interface GeoAnnotationsOptions {
  resolveColor: (name: AnnotationColor, shade?: number) => string;
  /** Label text colour; defaults to the annotation's own resolved colour. */
  fontColor?: string;
  /** The map's traces (see `normalizeGeoTraces`), to find marked points by id. */
  traces?: GeoTraceLike[];
  /** Annotation drawn emphasised (bigger halo, thicker outline). */
  highlightId?: string | null;
}

/** Opacity of the halo drawn over a marked point. */
export const GEO_HALO_OPACITY = 0.45;
/** Default tint of a marked choropleth region. */
export const GEO_REGION_TINT = 0.35;
/** Size of a note's dot (px). */
export const GEO_NOTE_SIZE = 9;

/** An annotation's label as map text: `(n) label` (see the module comment). */
export function geoLabelText(number: number | null, label: string): string {
  return number == null ? label : `(${number}) ${label}`;
}

interface LonLat {
  lon: number;
  lat: number;
}

interface ResolvedGeoPoints {
  /** Scatter points (or stored coords) to halo. */
  halos: LonLat[];
  /** Per choropleth trace: the marked region ids found, and where they sit. */
  regions: Array<{ trace: GeoTraceLike; locations: unknown[]; centroids: LonLat[] }>;
  found: number;
  expected: number;
}

function resolveGeoPoints(geom: MarkedPoints, traces: GeoTraceLike[] | undefined): ResolvedGeoPoints {
  const ids = geom.ids ?? [];
  const coords = geom.coords ?? [];
  if (ids.length && geom.column) {
    const wanted = new Set(ids.map((v) => String(v)));
    const seen = new Set<string>();
    const halos: LonLat[] = [];
    const regions: ResolvedGeoPoints['regions'] = [];
    for (const trace of traces ?? []) {
      if (!Array.isArray(trace.ids)) continue;
      const locations: unknown[] = [];
      const centroids: LonLat[] = [];
      trace.ids.forEach((raw, i) => {
        if (raw == null) return;
        const key = String(raw);
        if (!wanted.has(key) || seen.has(key)) return;
        const pos = asLonLat(trace.lon?.[i], trace.lat?.[i]);
        if (trace.regions) {
          seen.add(key);
          locations.push(raw);
          if (pos) centroids.push(pos);
        } else if (pos) {
          seen.add(key);
          halos.push(pos);
        }
      });
      if (locations.length) regions.push({ trace, locations, centroids });
    }
    if (seen.size || !coords.length) return { halos, regions, found: seen.size, expected: wanted.size };
  }
  const halos: LonLat[] = [];
  for (const c of coords) {
    const pos = asLonLat(c.x, c.y);
    if (pos) halos.push(pos);
  }
  return { halos, regions: [], found: halos.length, expected: coords.length };
}

/** The region's outline as a closed ring of vertices, or null. */
function regionRing(region: SelectionRegion): LonLat[] | null {
  if (region.shape === 'box') {
    const [x0, x1, y0, y1] = [region.x0, region.x1, region.y0, region.y1];
    if (![x0, x1, y0, y1].every((v) => typeof v === 'number' && Number.isFinite(v))) return null;
    const [a, b, c, d] = [x0, x1, y0, y1] as number[];
    return [
      { lon: a, lat: c },
      { lon: b, lat: c },
      { lon: b, lat: d },
      { lon: a, lat: d },
      { lon: a, lat: c },
    ];
  }
  const ring: LonLat[] = [];
  for (let i = 0; i < Math.min(region.x.length, region.y.length); i++) {
    const p = asLonLat(region.x[i], region.y[i]);
    if (p) ring.push(p);
  }
  if (ring.length < 3) return null;
  return [...ring, ring[0]];
}

/** The northernmost vertex of a ring (the westernmost on a tie): where its label goes. */
function ringTop(ring: LonLat[]): LonLat {
  return ring.reduce((best, p) => (p.lat > best.lat || (p.lat === best.lat && p.lon < best.lon) ? p : best));
}

/**
 * Where labels sharing an anchor go, in turn. MapLibre hides a label that
 * collides with another, so two annotations on the same point must not print
 * in the same spot.
 */
const LABEL_POSITIONS = ['top right', 'bottom right', 'top left', 'bottom left'] as const;

function compareItems(a: RenderableAnnotation, b: RenderableAnnotation): number {
  const an = a.number ?? Number.POSITIVE_INFINITY;
  const bn = b.number ?? Number.POSITIVE_INFINITY;
  if (an !== bn) return an < bn ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Whether an annotation can be drawn on a map. */
export function isGeoAnnotation(item: RenderableAnnotation): boolean {
  const g = item.annotation.geometry;
  return g.kind === 'geo_note' || (g.kind === 'points' && g.geo === true);
}

/**
 * Overlay traces drawing map annotations, in the result shape of
 * `annotationsToPlotly` (no layout shapes or labels: a map cannot anchor
 * them). Annotations that are not geographic are left out. Stats: marked
 * points asked for / found.
 */
export function geoAnnotationsToPlotly(
  items: RenderableAnnotation[],
  opts: GeoAnnotationsOptions,
): AnnotationsToPlotlyResult {
  const overlayTraces: Partial<Data>[] = [];
  const stats: Record<string, AnnotationStats> = {};
  const anchorsUsed = new Map<string, number>();
  const labelPosition = (at: LonLat) => {
    const key = `${at.lon.toFixed(5)},${at.lat.toFixed(5)}`;
    const n = anchorsUsed.get(key) ?? 0;
    anchorsUsed.set(key, n + 1);
    return LABEL_POSITIONS[n % LABEL_POSITIONS.length];
  };

  for (const item of [...items].sort(compareItems)) {
    if (!isGeoAnnotation(item)) continue;
    const { annotation } = item;
    const geom = annotation.geometry;
    const preview = item.preview === true;
    const fade = (v: number) => (preview ? v * PREVIEW_OPACITY_FACTOR : v);
    const style = annotation.style ?? {};
    const color = opts.resolveColor(annotation.color ?? DEFAULT_COLOR);
    const fontColor = opts.fontColor ?? color;
    const hi = !preview && opts.highlightId != null && opts.highlightId === item.id;
    const name = `${OVERLAY_TRACE_PREFIX}${item.id}`;
    const text = geoLabelText(item.number, annotation.label);
    const common = { name, showlegend: false } as const;
    // Filled in once the counts are known (hover shows them).
    const hoverable: Array<Record<string, unknown>> = [];
    const push = (trace: Record<string, unknown>, hover = true) => {
      overlayTraces.push(trace as Partial<Data>);
      if (hover) hoverable.push(trace);
      else trace.hoverinfo = 'skip';
    };
    // The transparent marker, as wide as the halo, gives the text its offset.
    const labelTrace = (at: LonLat, clearance: number) => ({
      type: 'scattermap',
      mode: 'markers+text',
      lon: [at.lon],
      lat: [at.lat],
      text: [text],
      textposition: labelPosition(at),
      textfont: { color: fontColor, size: hi ? 13 : 12 },
      marker: { size: clearance, color: withAlpha(color, 0) },
      opacity: fade(1),
      ...common,
    });

    if (geom.kind === 'geo_note') {
      push({
        type: 'scattermap',
        mode: 'markers+text',
        lon: [geom.lon],
        lat: [geom.lat],
        text: [text],
        textposition: labelPosition({ lon: geom.lon, lat: geom.lat }),
        textfont: { color: fontColor, size: hi ? 13 : 12 },
        marker: { size: hi ? GEO_NOTE_SIZE + 4 : GEO_NOTE_SIZE, color },
        opacity: fade(style.opacity ?? 1),
        ...common,
      });
    } else if (geom.kind === 'points') {
      const { halos, regions, found, expected } = resolveGeoPoints(geom, opts.traces);
      stats[item.id] = { expected, found };
      const width = (style.width ?? DEFAULT_POINT_RING_WIDTH) * (hi ? 1.5 : 1);
      const fill = style.fill_opacity ?? DEFAULT_RANGE_OPACITY;
      const ring = geom.region && fill > 0 ? regionRing(geom.region) : null;
      if (ring) {
        // The selected area, under the marks. Scattermap lines cannot be
        // dashed, so the preview only reads fainter.
        push(
          {
            type: 'scattermap',
            mode: 'lines',
            fill: 'toself',
            lon: ring.map((p) => p.lon),
            lat: ring.map((p) => p.lat),
            fillcolor: withAlpha(color, fade(hi ? Math.min(1, fill + 0.15) : fill)),
            line: { color, width: hi ? 2 : 1 },
            opacity: fade(1),
            ...common,
          },
          false,
        );
      }
      for (const r of regions) {
        // Marked choropleth regions: the same polygons, tinted and outlined.
        push({
          type: 'choroplethmap',
          geojson: r.trace.regions?.geojson,
          ...(r.trace.regions?.featureidkey ? { featureidkey: r.trace.regions.featureidkey } : {}),
          locations: r.locations,
          z: r.locations.map(() => 1),
          zmin: 0,
          zmax: 1,
          colorscale: [
            [0, withAlpha(color, fade(GEO_REGION_TINT))],
            [1, withAlpha(color, fade(GEO_REGION_TINT))],
          ],
          showscale: false,
          marker: { opacity: fade(style.opacity ?? 1), line: { color, width: width * 1.5 } },
          ...common,
        });
      }
      const haloSize = POINT_MARKER_SIZE + 4 * width;
      if (halos.length) {
        // Scattermap markers have no outline: a disc wider than the point,
        // translucent through the trace opacity (a selection restyle only
        // touches marker opacity).
        push({
          type: 'scattermap',
          mode: 'markers',
          lon: halos.map((p) => p.lon),
          lat: halos.map((p) => p.lat),
          marker: { size: haloSize, color },
          opacity: fade((style.opacity ?? 1) * (hi ? Math.min(1, GEO_HALO_OPACITY + 0.2) : GEO_HALO_OPACITY)),
          ...common,
        });
      }
      // The label sits at the top of the shaded area when there is one, else
      // on the first marked point or region.
      const anchor = ring
        ? ringTop(ring)
        : (halos[0] ?? regions.find((r) => r.centroids.length)?.centroids[0] ?? null);
      if (anchor) push(labelTrace(anchor, !ring && halos.length ? haloSize : GEO_NOTE_SIZE));
    }

    const facts = annotationHoverText(annotation, stats[item.id]);
    for (const t of hoverable) {
      if (preview) {
        t.hoverinfo = 'skip';
      } else {
        t.hoverinfo = 'text';
        t.hovertext = `${annotation.label}<br>${facts}`;
      }
    }
  }

  return { shapes: [], annotations: [], overlayTraces, stats, topLabelCount: 0 };
}
