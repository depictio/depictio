/**
 * The domain glyph of the `domain_architecture` tile, as Pfam graphics draws
 * it: a rounded rectangle whose left and / or right edge is a zigzag where
 * the HMM match is partial (the model's start or end is missing from the
 * hit). Pure path building on the subset of the 2D context it needs, so it is
 * unit-tested with a recording context (`shapes.test.ts`).
 */

/** The path calls the builders below make. */
export type PathContext = Pick<
  CanvasRenderingContext2D,
  'beginPath' | 'moveTo' | 'lineTo' | 'arcTo' | 'closePath'
>;

export interface DomainShape {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Corner radius of the rounded (whole) edges; clamped to fit. */
  radius: number;
  /** Jagged left edge: the hit starts after the first HMM state. */
  left: boolean;
  /** Jagged right edge: the hit ends before the last HMM state. */
  right: boolean;
  /** How far the teeth cut into the shape, CSS px (default 3). */
  depth?: number;
  /** Height of one tooth, CSS px (default 4): the count follows the height. */
  toothPx?: number;
}

/** Teeth on an edge of height `h`: one per `toothPx`, at least 2. */
export function toothCount(h: number, toothPx = 4): number {
  if (!(h > 0) || !(toothPx > 0)) return 2;
  return Math.max(2, Math.round(h / toothPx));
}

/**
 * The vertices of a zigzag edge at `x`, from `(x, y0)` to `(x, y1)` (either
 * direction), the teeth pointing `inward` px into the shape (a positive
 * value goes right, a negative one left). Ends on the edge line, so the edge
 * meets the horizontal sides flush. The start vertex is not included.
 */
export function zigzagPoints(
  x: number,
  y0: number,
  y1: number,
  inward: number,
  teeth: number,
): Array<[number, number]> {
  const n = Math.max(1, Math.floor(teeth));
  const steps = 2 * n;
  const out: Array<[number, number]> = [];
  for (let k = 1; k <= steps; k++) {
    const y = y0 + ((y1 - y0) * k) / steps;
    out.push([k % 2 === 1 ? x + inward : x, y]);
  }
  return out;
}

/** The cut depth that still leaves a body between two jagged edges. */
export function fitDepth(w: number, depth: number, jaggedEdges: number): number {
  if (jaggedEdges <= 0 || !(w > 0)) return 0;
  return Math.max(0, Math.min(depth, w / (2 * jaggedEdges)));
}

/**
 * Begin and close the path of one domain: rounded corners on a whole edge, a
 * zigzag on a partial one. Clockwise from the top-left corner. Fill and
 * stroke are the caller's.
 */
export function domainShapePath(ctx: PathContext, s: DomainShape): void {
  const { x, y, h } = s;
  const w = Math.max(0, s.w);
  const jagged = (s.left ? 1 : 0) + (s.right ? 1 : 0);
  const depth = fitDepth(w, s.depth ?? 3, jagged);
  const teeth = toothCount(h, s.toothPx ?? 4);
  // A corner never takes more than half the height or half the width.
  const r = Math.max(0, Math.min(s.radius, h / 2, w / 2));
  const rl = s.left ? 0 : r;
  const rr = s.right ? 0 : r;
  const x1 = x + w;
  const y1 = y + h;

  ctx.beginPath();
  ctx.moveTo(x + rl, y);
  // Top edge, then the right side.
  if (s.right) {
    ctx.lineTo(x1, y);
    for (const [px, py] of zigzagPoints(x1, y, y1, -depth, teeth)) ctx.lineTo(px, py);
  } else {
    ctx.lineTo(x1 - rr, y);
    if (rr > 0) ctx.arcTo(x1, y, x1, y + rr, rr);
    ctx.lineTo(x1, y1 - rr);
    if (rr > 0) ctx.arcTo(x1, y1, x1 - rr, y1, rr);
  }
  // Bottom edge, then the left side back up.
  if (s.left) {
    ctx.lineTo(x, y1);
    for (const [px, py] of zigzagPoints(x, y1, y, depth, teeth)) ctx.lineTo(px, py);
  } else {
    ctx.lineTo(x + rl, y1);
    if (rl > 0) ctx.arcTo(x, y1, x, y1 - rl, rl);
    ctx.lineTo(x, y + rl);
    if (rl > 0) ctx.arcTo(x, y, x + rl, y, rl);
  }
  ctx.closePath();
}

/** The dash pattern of a domain outline: dashed when partial on an unknown
 *  side (coverage only), solid otherwise. */
export function outlineDash(unknownPartial: boolean): number[] {
  return unknownPartial ? [3, 2] : [];
}
