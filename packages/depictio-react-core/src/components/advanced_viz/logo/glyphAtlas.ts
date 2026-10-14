/**
 * Glyph atlas for the logo: each (letter, colour) is rasterised ONCE, at high
 * resolution, into a slot of one offscreen sheet, and every stacked letter is
 * then a scaled `drawImage` of its slot. A logo letter is stretched to fill
 * its box (its height is its information), which `fillText` cannot do
 * without a transform per letter, and text rasterisation is the expensive
 * part of a frame: a 400-state amino logo would otherwise shape ~8000 glyphs
 * on every scroll or hover.
 *
 * The slot keeps only the glyph's ink box (from `measureText`'s actual
 * bounding box), so a stretched letter touches the top and bottom of its
 * share of the stack, as in Skylign and WebLogo. Slots are allocated on
 * demand in row-major order; when the sheet is full it doubles its rows and
 * copies the old sheet across. An atlas is keyed by font, device pixel ratio
 * and colour scheme (`atlasKey`): a theme or DPR change gets a fresh atlas
 * (`glyphAtlasFor`), so stale colours never pile up in one sheet.
 *
 * The canvas is injected (`createCanvas`), so the slot logic is unit-tested
 * in node (`glyphAtlas.test.ts`) with a recording fake.
 */

/** The 2D context calls the atlas makes (a subset of CanvasRenderingContext2D). */
export interface AtlasContext {
  font: string;
  fillStyle: string | CanvasGradient | CanvasPattern;
  textAlign: CanvasTextAlign;
  textBaseline: CanvasTextBaseline;
  fillText(text: string, x: number, y: number): void;
  measureText(text: string): Partial<TextMetrics> & { width: number };
  drawImage(image: CanvasImageSource, dx: number, dy: number): void;
}

export interface AtlasCanvas {
  width: number;
  height: number;
  getContext(contextId: '2d'): AtlasContext | null;
}

export type AtlasCanvasFactory = (width: number, height: number) => AtlasCanvas | null;

/** Where a glyph's ink sits in the sheet, in sheet pixels. */
export interface GlyphSlot {
  sx: number;
  sy: number;
  sw: number;
  sh: number;
}

export interface InkBox {
  /** Ink extent left of the drawing point, right of it, above and below the baseline. */
  left: number;
  right: number;
  ascent: number;
  descent: number;
}

/** Slots per sheet row. */
export const ATLAS_COLUMNS = 16;
/** Glyph cell side at a device pixel ratio of 1. */
export const ATLAS_CELL_PX = 128;
/** Font size inside a cell: the rest is padding against sampling bleed. */
const FONT_SHARE = 0.75;

/** Top-left corner of slot `index` in a sheet `columns` slots wide. */
export function slotOrigin(index: number, columns: number, cell: number): { x: number; y: number } {
  return { x: (index % columns) * cell, y: Math.floor(index / columns) * cell };
}

/** Sheet rows needed for `count` slots (at least one). */
export function sheetRows(count: number, columns: number): number {
  return Math.max(1, Math.ceil(count / columns));
}

const isFiniteNumber = (v: number | undefined): v is number => v !== undefined && Number.isFinite(v);

/**
 * The ink box of a glyph from its text metrics. Browsers without the
 * `actualBoundingBox*` fields fall back to the advance width and a cap
 * height of 0.72 em (no descent), which is right for the capital letters a
 * logo draws.
 */
export function inkBox(metrics: Partial<TextMetrics> & { width: number }, fontPx: number): InkBox {
  const left = isFiniteNumber(metrics.actualBoundingBoxLeft) ? metrics.actualBoundingBoxLeft : 0;
  const right = isFiniteNumber(metrics.actualBoundingBoxRight)
    ? metrics.actualBoundingBoxRight
    : metrics.width;
  const ascent = isFiniteNumber(metrics.actualBoundingBoxAscent)
    ? metrics.actualBoundingBoxAscent
    : 0.72 * fontPx;
  const descent = isFiniteNumber(metrics.actualBoundingBoxDescent) ? metrics.actualBoundingBoxDescent : 0;
  if (!(left + right > 0) || !(ascent + descent > 0)) {
    return { left: 0, right: Math.max(1, metrics.width || 0.6 * fontPx), ascent: 0.72 * fontPx, descent: 0 };
  }
  return { left, right, ascent, descent };
}

/** A canvas from the browser (OffscreenCanvas when there is one), null in node. */
export const browserCanvasFactory: AtlasCanvasFactory = (width, height) => {
  if (typeof OffscreenCanvas !== 'undefined') {
    return new OffscreenCanvas(width, height) as unknown as AtlasCanvas;
  }
  if (typeof document === 'undefined') return null;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas as unknown as AtlasCanvas;
};

export interface GlyphAtlasOptions {
  fontFamily: string;
  /** Cell side in sheet pixels (the glyphs' resolution). */
  cellPx?: number;
  columns?: number;
  weight?: number | string;
  createCanvas?: AtlasCanvasFactory;
}

export class GlyphAtlas {
  readonly cell: number;
  readonly columns: number;
  readonly fontPx: number;
  readonly font: string;
  private readonly createCanvas: AtlasCanvasFactory;
  private canvas: AtlasCanvas | null = null;
  private ctx: AtlasContext | null = null;
  private readonly slots = new Map<string, GlyphSlot | null>();
  private count = 0;
  private failed = false;

  constructor(opts: GlyphAtlasOptions) {
    this.cell = Math.max(8, Math.round(opts.cellPx ?? ATLAS_CELL_PX));
    this.columns = Math.max(1, Math.round(opts.columns ?? ATLAS_COLUMNS));
    this.fontPx = Math.round(this.cell * FONT_SHARE);
    this.font = `${opts.weight ?? 700} ${this.fontPx}px ${opts.fontFamily}`;
    this.createCanvas = opts.createCanvas ?? browserCanvasFactory;
  }

  /** Glyphs rasterised so far. */
  get size(): number {
    return this.count;
  }

  /** The sheet (for drawing); null before the first glyph or without a canvas. */
  get sheet(): AtlasCanvas | null {
    return this.canvas;
  }

  /** Make room for `needed` slots: the first sheet, or one with twice the rows. */
  private ensureCapacity(needed: number): boolean {
    const rowsNow = this.canvas ? Math.round(this.canvas.height / this.cell) : 0;
    if (this.canvas && needed <= rowsNow * this.columns) return true;
    const rows = Math.max(sheetRows(needed, this.columns), rowsNow * 2);
    const next = this.createCanvas(this.columns * this.cell, rows * this.cell);
    const ctx = next?.getContext('2d') ?? null;
    if (!next || !ctx) return false;
    if (this.canvas) ctx.drawImage(this.canvas as unknown as CanvasImageSource, 0, 0);
    this.canvas = next;
    this.ctx = ctx;
    return true;
  }

  /** The slot of `letter` in `colour`, rasterised on first use. Null without a canvas. */
  slot(letter: string, colour: string): GlyphSlot | null {
    const key = `${letter}\u0000${colour}`;
    const known = this.slots.get(key);
    if (known !== undefined) return known;
    if (this.failed || !this.ensureCapacity(this.count + 1) || !this.ctx) {
      this.failed = true;
      return null;
    }
    const ctx = this.ctx;
    const origin = slotOrigin(this.count, this.columns, this.cell);
    ctx.font = this.font;
    ctx.fillStyle = colour;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    const box = inkBox(ctx.measureText(letter), this.fontPx);
    const pad = (this.cell - this.fontPx) / 2;
    const room = this.cell - 2 * pad;
    const sw = Math.min(room, box.left + box.right);
    const sh = Math.min(room, box.ascent + box.descent);
    const x = origin.x + pad;
    const y = origin.y + pad;
    // The ink's top-left corner lands on the slot's corner.
    ctx.fillText(letter, x + box.left, y + box.ascent);
    const slot = { sx: x, sy: y, sw, sh };
    this.slots.set(key, slot);
    this.count += 1;
    return slot;
  }

  /**
   * Draw `letter` stretched to the box (x, y, w, h) on `target`. False when
   * the atlas has no canvas (the caller then falls back to `fillText`).
   */
  draw(
    target: Pick<CanvasRenderingContext2D, 'drawImage'>,
    letter: string,
    colour: string,
    x: number,
    y: number,
    w: number,
    h: number,
  ): boolean {
    const s = this.slot(letter, colour);
    if (!s || !this.canvas) return false;
    target.drawImage(this.canvas as unknown as CanvasImageSource, s.sx, s.sy, s.sw, s.sh, x, y, w, h);
    return true;
  }
}

/** What an atlas depends on besides its glyphs: rebuild when any changes. */
export function atlasKey(fontFamily: string, dpr: number, scheme: string): string {
  const ratio = Math.max(1, Math.min(3, Number.isFinite(dpr) ? dpr : 1));
  return `${fontFamily}|${ratio.toFixed(2)}|${scheme}`;
}

/** Sheet cell side for a device pixel ratio: high enough for tall stacks. */
export function atlasCellPx(dpr: number): number {
  const ratio = Math.max(1, Math.min(2, Number.isFinite(dpr) ? dpr : 1));
  return Math.round(ATLAS_CELL_PX * ratio);
}

const ATLASES = new Map<string, GlyphAtlas>();
/** Atlases kept across tiles (keys: light and dark, a DPR or two). */
const MAX_ATLASES = 4;

/**
 * The shared atlas for `key`, built with `make` on first use. Tiles of one
 * dashboard share it; the oldest atlas is dropped past `MAX_ATLASES`.
 */
export function glyphAtlasFor(key: string, make: () => GlyphAtlas): GlyphAtlas {
  const hit = ATLASES.get(key);
  if (hit) return hit;
  const atlas = make();
  ATLASES.set(key, atlas);
  while (ATLASES.size > MAX_ATLASES) {
    const oldest = ATLASES.keys().next().value;
    if (oldest === undefined) break;
    ATLASES.delete(oldest);
  }
  return atlas;
}

/** Forget every shared atlas (tests). */
export function clearGlyphAtlases(): void {
  ATLASES.clear();
}
