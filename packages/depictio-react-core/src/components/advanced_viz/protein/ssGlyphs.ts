/**
 * Secondary-structure glyphs on a 2D canvas: a helix is a rounded bar, a strand
 * an arrow, a turn a short thick bar, a coil a thin line.
 *
 * Shared by the sequence strip (its structure lane) and any panel that draws
 * secondary structure along a residue axis. Every glyph spans `[x0, x1]` on the
 * horizontal axis and is centred on `yMid`; `h` is the lane height a helix or
 * strand fills. The functions only issue path and fill calls and set
 * `fillStyle` / `strokeStyle` themselves: no `save` / `restore`, no clipping,
 * no font, so a caller keeps full control of the canvas state around them.
 */

import { rgbCss, SECONDARY_STRUCTURE_COLOURS, type SecondaryStructure } from './residueColours';
import { roundRectPath } from './canvas';
import type { Run } from './sequence';

/** Fill of each filled glyph, derived from RasMol's `structure` palette. */
export type SsFills = Readonly<Record<'helix' | 'strand' | 'turn', string>>;

export const SS_GLYPH_FILLS: SsFills = {
  helix: rgbCss(SECONDARY_STRUCTURE_COLOURS.helix),
  strand: rgbCss(SECONDARY_STRUCTURE_COLOURS.strand),
  turn: rgbCss(SECONDARY_STRUCTURE_COLOURS.turn),
};

/** Thickness, in CSS pixels, of the bar a turn is drawn as. */
export const TURN_THICKNESS = 3;

/** Inset above and below a helix, so neighbouring lanes keep a gap. */
const HELIX_INSET = 1;

/** A helix: a rounded bar filling the lane height less a 1 px inset. */
export function drawHelix(
  ctx: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  yMid: number,
  h: number,
  colour: string,
): void {
  const w = x1 - x0;
  ctx.fillStyle = colour;
  roundRectPath(
    ctx,
    x0,
    yMid - h / 2 + HELIX_INSET,
    w,
    h - 2 * HELIX_INSET,
    Math.min(h / 2, w / 2),
  );
  ctx.fill();
}

/**
 * A strand: a shaft, 40% of the lane high at most, ending in an arrow head that
 * spans the whole lane height. The head is 40% of the glyph width, capped at
 * 70% of the lane height, so a short strand is still an arrow.
 */
export function drawStrand(
  ctx: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  yMid: number,
  h: number,
  colour: string,
): void {
  const w = x1 - x0;
  const head = Math.min(w * 0.4, h * 0.7);
  const top = yMid - h / 2;
  ctx.fillStyle = colour;
  ctx.beginPath();
  ctx.moveTo(x0, yMid - h * 0.25);
  ctx.lineTo(x0 + w - head, yMid - h * 0.25);
  ctx.lineTo(x0 + w - head, top);
  ctx.lineTo(x0 + w, yMid);
  ctx.lineTo(x0 + w - head, top + h);
  ctx.lineTo(x0 + w - head, yMid + h * 0.25);
  ctx.lineTo(x0, yMid + h * 0.25);
  ctx.closePath();
  ctx.fill();
}

/** A turn: a short thick bar on the centre line. */
export function drawTurn(
  ctx: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  yMid: number,
  colour: string,
): void {
  ctx.fillStyle = colour;
  ctx.fillRect(x0, yMid - TURN_THICKNESS / 2, x1 - x0, TURN_THICKNESS);
}

/**
 * A coil: a 1 px line on the centre line, half a pixel below it so it lands on
 * a pixel row. Drawn once across a lane as its baseline, or per coil run.
 */
export function drawCoil(
  ctx: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  yMid: number,
  colour: string,
): void {
  ctx.strokeStyle = colour;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x0, yMid + 0.5);
  ctx.lineTo(x1, yMid + 0.5);
  ctx.stroke();
}

/** Where residues sit on the canvas and how tall a glyph is. */
export interface SsGeometry {
  /** Left edge, in CSS pixels, of the cell of residue `position`. */
  xOf: (position: number) => number;
  /** Width of one residue cell. */
  cellWidth: number;
  /** Vertical centre of the lane. */
  yMid: number;
  /** Lane height, which helices and strands fill. */
  height: number;
  /** Inclusive position window on screen: runs wholly outside it are skipped. */
  visible?: readonly [number, number];
}

export interface SsDrawColours {
  /** Fill of the helix, strand and turn glyphs (default: `SS_GLYPH_FILLS`). */
  fills?: SsFills;
  /** Stroke of a coil run. Left out, coil runs are not drawn: the caller
   *  draws one baseline under the lane instead. */
  coil?: string | null;
}

/**
 * Draw runs of secondary structure, each as its glyph, spanning its first to
 * its last residue cell. Runs outside `geometry.visible` are skipped.
 */
export function drawSecondaryStructureRuns(
  ctx: CanvasRenderingContext2D,
  runs: readonly Run<SecondaryStructure>[],
  geometry: SsGeometry,
  colours: SsDrawColours = {},
): void {
  const { xOf, cellWidth, yMid, height, visible } = geometry;
  const fills = colours.fills ?? SS_GLYPH_FILLS;
  for (const run of runs) {
    if (visible && (run.end < visible[0] || run.start > visible[1])) continue;
    const x0 = xOf(run.start);
    const x1 = x0 + (run.end - run.start + 1) * cellWidth;
    switch (run.value) {
      case 'helix':
        drawHelix(ctx, x0, x1, yMid, height, fills.helix);
        break;
      case 'strand':
        drawStrand(ctx, x0, x1, yMid, height, fills.strand);
        break;
      case 'turn':
        drawTurn(ctx, x0, x1, yMid, fills.turn);
        break;
      case 'coil':
        if (colours.coil) drawCoil(ctx, x0, x1, yMid, colours.coil);
        break;
    }
  }
}
