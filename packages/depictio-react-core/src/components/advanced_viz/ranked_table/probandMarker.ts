/**
 * Geometry of the proband marker (an arrow from the lower left and a "P") of
 * the ranked table's family drawing. Pure, so the rules are unit-tested.
 *
 * The arrow's tip rests just outside the symbol's outline (the affected ring
 * included), whatever the sex: a square meets the diagonal at its corner, a
 * circle at its radius, a diamond at its edge, so one fixed offset would float
 * off a circle. The arrow, its "P" and the label under the symbol (see
 * `LABEL_OFFSET`) are placed so none of them overlaps another, and everything
 * stays within `MARKER_REACH` of the symbol's centre, which is the margin the
 * drawing keeps on its left and bottom.
 */
import type { Sex } from '../pedigree/pedigreeLayout';

export interface Point {
  x: number;
  y: number;
}

export interface ProbandMarker {
  /** Where the arrow touches the symbol. */
  tip: Point;
  /** The far end of the shaft. */
  tail: Point;
  /** The two strokes of the head, each from the tip. */
  head: [Point, Point];
  /** Centre of the "P", clear of the label under the symbol. */
  letter: Point;
}

export interface MarkerOptions {
  /** Width of the ring drawn around the symbol (affected status); 0 without. */
  ring?: number;
  /** Everything scales with this (1 at the popover's symbol size). */
  scale?: number;
}

/** The diamond's radius over its half edge, as `FamilyPedigree` draws it. */
export const DIAMOND_RATIO = 1.2;

const GAP = 1.5;
const SHAFT = 11;
const HEAD = 5.5;
const HEAD_SPREAD = 0.5;
const LETTER_ALONG = 5;
const LETTER_LEFT = 4.5;
/** Direction of the arrow's tail from its tip: toward the lower left. */
const DOWN_LEFT: Point = { x: -Math.SQRT1_2, y: Math.SQRT1_2 };

/**
 * Distance from a symbol's centre to its outline along the lower-left
 * diagonal. `half` is the half edge of the symbol, `pad` what is drawn around
 * it (the ring).
 */
export function outlineDistance(sex: Sex, half: number, pad = 0): number {
  const h = half + pad;
  if (sex === 'female') return h;
  if (sex === 'male') return h * Math.SQRT2;
  return (DIAMOND_RATIO * h) / Math.SQRT2;
}

const along = (from: Point, dir: Point, d: number): Point => ({
  x: from.x + dir.x * d,
  y: from.y + dir.y * d,
});

/** The marker for a symbol centred on (0, 0), `half` its half edge. */
export function probandMarker(sex: Sex, half: number, opts: MarkerOptions = {}): ProbandMarker {
  const k = opts.scale ?? 1;
  const reach = outlineDistance(sex, half, opts.ring ?? 0) + GAP * k;
  const origin = { x: 0, y: 0 };
  const tip = along(origin, DOWN_LEFT, reach);
  const tail = along(tip, DOWN_LEFT, SHAFT * k);
  // The head's strokes lie along the shaft, spread either side of it.
  const back = Math.atan2(DOWN_LEFT.y, DOWN_LEFT.x);
  const stroke = (da: number): Point => ({
    x: tip.x + HEAD * k * Math.cos(back + da),
    y: tip.y + HEAD * k * Math.sin(back + da),
  });
  const beyond = along(tail, DOWN_LEFT, LETTER_ALONG * k);
  return {
    tip,
    tail,
    head: [stroke(HEAD_SPREAD), stroke(-HEAD_SPREAD)],
    letter: { x: beyond.x - LETTER_LEFT * k, y: beyond.y },
  };
}

/** Vertical distance from a symbol's centre to the baseline of its label. */
export function labelBaseline(half: number): number {
  return half + LABEL_OFFSET;
}

/** The label sits this far below the symbol's edge; the marker leaves it room. */
export const LABEL_OFFSET = 20;

/** The farthest the marker reaches from the symbol's centre, left and down,
 *  for any sex and a ring of `ring`: what the drawing must leave free. */
export function markerReach(half: number, ring = 0, scale = 1): { left: number; down: number } {
  let left = 0;
  let down = 0;
  for (const sex of ['male', 'female', 'unknown'] as const) {
    const m = probandMarker(sex, half, { ring, scale });
    // The letter is about 7 units wide and 7 tall at scale 1.
    left = Math.max(left, -m.letter.x + 3.5 * scale);
    down = Math.max(down, m.letter.y + 3.5 * scale);
  }
  return { left, down };
}
