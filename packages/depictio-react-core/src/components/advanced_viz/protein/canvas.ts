/**
 * Canvas plumbing shared by the protein panels: DPR-aware sizing, virtualised
 * row / column windows, letter fitting, ruler ticks and scroll-to-reveal.
 * The arithmetic is pure and unit-tested in `canvas.test.ts`; only
 * `prepareCanvas` touches a DOM object.
 */

/** Resize a canvas to `cssW` by `cssH` CSS pixels at the device pixel ratio
 *  and return its 2D context, scaled so drawing code works in CSS pixels. */
export function prepareCanvas(
  canvas: HTMLCanvasElement,
  cssW: number,
  cssH: number,
): CanvasRenderingContext2D | null {
  const dpr = typeof window !== 'undefined' ? Math.max(1, window.devicePixelRatio || 1) : 1;
  const w = Math.max(1, Math.round(cssW * dpr));
  const h = Math.max(1, Math.round(cssH * dpr));
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
  canvas.style.width = `${cssW}px`;
  canvas.style.height = `${cssH}px`;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  return ctx;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/**
 * The cells of a scrolled axis that intersect the viewport, plus `overscan`
 * on each side: `[first, last]` inclusive, or `[0, -1]` when there are none.
 */
export function visibleWindow(
  scroll: number,
  viewport: number,
  cell: number,
  count: number,
  overscan = 1,
): [number, number] {
  if (count <= 0 || cell <= 0 || viewport <= 0) return [0, -1];
  const first = clamp(Math.floor(scroll / cell) - overscan, 0, count - 1);
  const last = clamp(Math.ceil((scroll + viewport) / cell) + overscan - 1, 0, count - 1);
  return [first, last];
}

/** Smallest cell, in CSS pixels, that still carries a readable letter. */
export const MIN_LETTER_PX = 7;

export function lettersFit(cellW: number, cellH: number, min = MIN_LETTER_PX): boolean {
  return cellW >= min && cellH >= min + 2;
}

/** Cell width that fits `count` cells into `viewport` pixels, clamped. */
export function fitCellWidth(viewport: number, count: number, min = 1, max = 16): number {
  if (count <= 0 || viewport <= 0) return max;
  return clamp(viewport / count, min, max);
}

/** A 1-2-5 step, in residues, that keeps ruler labels `minGapPx` apart. */
export function rulerStep(pxPerUnit: number, minGapPx = 48): number {
  if (!(pxPerUnit > 0)) return 1;
  const raw = minGapPx / pxPerUnit;
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  for (const m of [1, 2, 5, 10]) {
    if (m * pow >= raw) return m * pow;
  }
  return 10 * pow;
}

/**
 * The scroll offset that brings `[start, end]` (pixel span on the scrolled
 * axis) into a viewport at `scroll`, or null when it is already fully visible.
 * A span wider than the viewport is aligned on its start.
 */
export function scrollToReveal(
  scroll: number,
  viewport: number,
  start: number,
  end: number,
  margin = 16,
): number | null {
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  if (lo >= scroll && hi <= scroll + viewport) return null;
  if (hi - lo + 2 * margin >= viewport) return Math.max(0, lo - margin);
  const centred = (lo + hi) / 2 - viewport / 2;
  return Math.max(0, centred);
}

/** Begin a rounded-rectangle path, a plain one where the canvas lacks `roundRect`. */
export function roundRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
  else ctx.rect(x, y, w, h);
}

/** `text` cut with an ellipsis to fit `maxWidth` under `ctx`'s current font. */
export function fitText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (maxWidth <= 0) return '';
  if (ctx.measureText(text).width <= maxWidth) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (ctx.measureText(`${text.slice(0, mid)}…`).width <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  return lo > 0 ? `${text.slice(0, lo)}…` : '';
}
