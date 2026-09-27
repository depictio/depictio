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

/**
 * Orthographic camera that shows the whole image centred in the viewport.
 *
 * deck's orthographic zoom is log2 of screen pixels per world unit, so the
 * image fits when 2^zoom times its larger relative side equals the viewport.
 * `padding` is a fraction of the viewport kept clear on each axis.
 */
export function fitViewState(
  imageWidth: number,
  imageHeight: number,
  viewWidth: number,
  viewHeight: number,
  padding = 0.02,
): { target: [number, number, number]; zoom: number } {
  const target: [number, number, number] = [imageWidth / 2, imageHeight / 2, 0];
  if (imageWidth <= 0 || imageHeight <= 0 || viewWidth <= 0 || viewHeight <= 0) {
    return { target, zoom: 0 };
  }
  const scale = Math.min(viewWidth / imageWidth, viewHeight / imageHeight) * (1 - 2 * padding);
  return { target, zoom: Math.log2(scale) };
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
