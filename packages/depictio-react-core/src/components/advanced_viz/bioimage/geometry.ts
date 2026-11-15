/**
 * Pure geometry for the bioimage viewer: ROI hit-testing, the fit-to-view
 * camera and the scale bar length. No deck.gl import, so it is unit-testable
 * and costs nothing on the renderer's eager path.
 *
 * Every coordinate here is in level-0 image pixels (x right, y down), the
 * space the multiscale layer draws in and the points overlay is mapped into.
 */

export type Vec2 = [number, number];

/** A closed polygon, as its vertices in order. The closing edge is implied. */
export type Polygon = Vec2[];

/** Even-odd ray cast. A point exactly on an edge may land either side, which
 *  is fine for a hand-drawn lasso. */
export function pointInPolygon(x: number, y: number, polygon: Polygon): boolean {
  let inside = false;
  const n = polygon.length;
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const crosses = yi > y !== yj > y;
    if (crosses && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Axis-aligned bounds of a polygon, or null for an empty one. */
export function polygonBounds(
  polygon: Polygon,
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (polygon.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of polygon) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

/** The points inside `polygon`, in input order. A polygon with fewer than
 *  three vertices encloses nothing. The bounds check first keeps a small
 *  lasso over a large cell table from ray-casting every cell. */
export function pointsInPolygon<T extends { x: number; y: number }>(
  points: readonly T[],
  polygon: Polygon,
): T[] {
  if (polygon.length < 3) return [];
  const b = polygonBounds(polygon);
  if (!b) return [];
  const out: T[] = [];
  for (const p of points) {
    if (p.x < b.minX || p.x > b.maxX || p.y < b.minY || p.y > b.maxY) continue;
    if (pointInPolygon(p.x, p.y, polygon)) out.push(p);
  }
  return out;
}

/** The rectangle spanned by two drag corners, as a polygon, whichever way the
 *  drag went. */
export function rectToPolygon(a: Vec2, b: Vec2): Polygon {
  const minX = Math.min(a[0], b[0]);
  const maxX = Math.max(a[0], b[0]);
  const minY = Math.min(a[1], b[1]);
  const maxY = Math.max(a[1], b[1]);
  return [
    [minX, minY],
    [maxX, minY],
    [maxX, maxY],
    [minX, maxY],
  ];
}

/** Axis-aligned bounds in level-0 image pixels. */
export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** A point, or a box when it has a width and height (centred on x, y). */
export interface Footprint {
  x: number;
  y: number;
  w?: number;
  h?: number;
}

/**
 * Orthographic camera that shows `bounds` centred in the viewport.
 *
 * deck's orthographic zoom is log2 of screen pixels per world unit, so the
 * bounds fit when 2^zoom times their larger relative side equals the viewport.
 * `padding` is a fraction of the viewport kept clear on each axis.
 */
export function fitBoundsViewState(
  bounds: Bounds,
  viewWidth: number,
  viewHeight: number,
  padding = 0.02,
): { target: [number, number, number]; zoom: number } {
  const width = bounds.maxX - bounds.minX;
  const height = bounds.maxY - bounds.minY;
  const target: [number, number, number] = [
    (bounds.minX + bounds.maxX) / 2,
    (bounds.minY + bounds.maxY) / 2,
    0,
  ];
  if (width <= 0 || height <= 0 || viewWidth <= 0 || viewHeight <= 0) {
    return { target, zoom: 0 };
  }
  const scale = Math.min(viewWidth / width, viewHeight / height) * (1 - 2 * padding);
  return { target, zoom: Math.log2(scale) };
}

/** The camera that shows the whole image (see `fitBoundsViewState`). */
export function fitViewState(
  imageWidth: number,
  imageHeight: number,
  viewWidth: number,
  viewHeight: number,
  padding = 0.02,
): { target: [number, number, number]; zoom: number } {
  const bounds = { minX: 0, minY: 0, maxX: imageWidth, maxY: imageHeight };
  return fitBoundsViewState(bounds, viewWidth, viewHeight, padding);
}

/** What a set of points covers, a box counting its whole extent. Null for none. */
export function footprintBounds(points: readonly Footprint[]): Bounds | null {
  if (points.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of points) {
    const hw = (p.w ?? 0) / 2;
    const hh = (p.h ?? 0) / 2;
    minX = Math.min(minX, p.x - hw);
    minY = Math.min(minY, p.y - hh);
    maxX = Math.max(maxX, p.x + hw);
    maxY = Math.max(maxY, p.y + hh);
  }
  return { minX, minY, maxX, maxY };
}

/** `bounds` grown about their centre to at least `minSize` on each axis. */
export function padBounds(bounds: Bounds | null, minSize: number): Bounds | null {
  if (!bounds) return null;
  const grow = (lo: number, hi: number): [number, number] => {
    const extra = Math.max(0, minSize - (hi - lo)) / 2;
    return [lo - extra, hi + extra];
  };
  const [minX, maxX] = grow(bounds.minX, bounds.maxX);
  const [minY, maxY] = grow(bounds.minY, bounds.maxY);
  return { minX, minY, maxX, maxY };
}

/** How a box shows at a zoom: a dot when it is too small to see, filled
 *  while small (a heat map over an overview), outlined once it is big
 *  enough for the image inside it to matter. */
export type BoxDisplay = 'dot' | 'filled' | 'outline';

/** Screen sizes (px) below which a box is a dot, and above which it is
 *  outlined rather than filled. */
export const BOX_MIN_PX = 4;
export const BOX_FILL_MAX_PX = 48;

export function boxDisplay(box: Footprint, pixelsPerUnit: number): BoxDisplay {
  const side = Math.max(box.w ?? 0, box.h ?? 0) * pixelsPerUnit;
  if (side < BOX_MIN_PX) return 'dot';
  return side < BOX_FILL_MAX_PX ? 'filled' : 'outline';
}

/**
 * The point under (x, y): the smallest box holding it, else the nearest dot
 * within `slack` (world units, the dot radius at the current zoom). Null when
 * nothing is there.
 */
export function pointAt<T extends Footprint>(
  points: readonly T[],
  x: number,
  y: number,
  slack: number,
): T | null {
  let box: T | null = null;
  let boxArea = Infinity;
  let dot: T | null = null;
  let dotDistance = slack * slack;
  for (const p of points) {
    if (p.w != null && p.h != null) {
      if (Math.abs(x - p.x) <= p.w / 2 && Math.abs(y - p.y) <= p.h / 2 && p.w * p.h < boxArea) {
        box = p;
        boxArea = p.w * p.h;
      }
      continue;
    }
    const d = (x - p.x) ** 2 + (y - p.y) ** 2;
    if (d <= dotDistance) {
      dot = p;
      dotDistance = d;
    }
  }
  return box ?? dot;
}

/** Largest 1, 2 or 5 times a power of ten that is at most `value`. */
export function niceFloor(value: number): number {
  if (!(value > 0) || !Number.isFinite(value)) return 0;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const leading = value / magnitude;
  const step = leading >= 5 ? 5 : leading >= 2 ? 2 : 1;
  return step * magnitude;
}

/**
 * A scale bar of a round physical length, drawn at most `maxScreenPx` wide.
 *
 * `physicalPerPixel` is the size of one level-0 pixel in the image's unit and
 * `zoom` the orthographic zoom (screen px per image px = 2^zoom). Returns the
 * bar's screen width and the physical length it stands for, or null when the
 * image has no usable physical size.
 */
export function scaleBarLength(
  physicalPerPixel: number,
  zoom: number,
  maxScreenPx = 120,
): { screenPx: number; value: number } | null {
  if (!(physicalPerPixel > 0) || !Number.isFinite(zoom)) return null;
  const screenPerPixel = 2 ** zoom;
  const maxValue = (maxScreenPx / screenPerPixel) * physicalPerPixel;
  const value = niceFloor(maxValue);
  if (value <= 0) return null;
  return { screenPx: (value / physicalPerPixel) * screenPerPixel, value };
}

/** Whether a point at depth `z` (a plane index, maybe fractional) draws on
 *  plane `plane`: its nearest plane, or any within `tolerance` planes. */
export function onPlane(z: number, plane: number, tolerance = 0): boolean {
  if (!Number.isFinite(z)) return false;
  return tolerance > 0 ? Math.abs(z - plane) <= tolerance : Math.round(z) === plane;
}
