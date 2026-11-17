/**
 * Truncated value axis, drawn as a broken one: the pure geometry.
 *
 * A bar chart whose value axis starts above zero (stacked_bar's Zoom)
 * would otherwise read as an axis that starts at its first tick. This turns
 * the crop into a visible break. Along the axis, from the cropped end inwards:
 *
 *     [cut label, 0%]  stub of axis line  ~gap~  //  ~gap~  axis line  [first real tick]
 *
 *  - the axis line is interrupted: an empty gap on both sides of the `//`;
 *  - the tick labels in the stub are covered and replaced by one label for the
 *    cut value at the very end, so the reader sees "0 // 90%" rather than a
 *    lone "85%" glued to the marker;
 *  - every bar / stacked segment that reaches past the break gets a hole in the
 *    background colour, level with the `//`, as tall as the gap between the
 *    two slashes and as wide as the bar (a vertical rectangle for horizontal
 *    bars);
 *  - a caption names where the axis really starts.
 *
 * Everything here is arithmetic on measured pixels: no DOM, no Plotly. The
 * overlay (axisBreakOverlay.ts) measures Plotly's own axis geometry, calls
 * {@link computeAxisBreak} and draws the primitives it returns.
 */

/** Pixel box relative to the plot's svg. */
export interface Box {
  l: number;
  r: number;
  t: number;
  b: number;
}

export interface TickLabel extends Box {
  text: string;
}

/** Where the value axis sits, in the pixels of Plotly's svg. */
export interface AxisGeometry {
  /** The value axis runs top to bottom (a vertical bar chart). */
  vertical: boolean;
  /** Pixel where the axis starts: its top (vertical) or its left (horizontal). */
  start: number;
  /** Length of the axis, px. */
  length: number;
  /** Pixel of the axis LINE across the axis: x of a vertical axis, y of a horizontal one. */
  line: number;
  /** The lowest value sits at the bottom (vertical) / left (horizontal). */
  lowFirst: boolean;
  /** The axis hangs on the right (vertical) / top (horizontal). */
  far: boolean;
  /** The plot area, px: where bars may be clamped to. */
  plot: { l: number; t: number; w: number; h: number };
}

export interface AxisBreakStyle {
  /** Axis line and slash colour. */
  line: string;
  tick: string;
  /** What the page looks like behind the plot: the colour of the gap and the holes. */
  bg: string;
  /** Tick label colour. */
  label: string;
  /** Caption colour. */
  caption: string;
  fontSize: number;
  fontFamily: string;
}

export interface AxisBreakOptions {
  /** px from the cropped end to the centre of the `//`. */
  offset?: number;
  /** Half length of one slash across the axis, px. */
  size?: number;
  /** px between the two slashes. */
  gap?: number;
  /** More px of empty axis on each side of the slashes. */
  clear?: number;
  /** false: no holes through the bars. */
  band?: boolean;
  /** false: no caption. */
  caption?: boolean;
}

export interface AxisBreakInput {
  geometry: AxisGeometry;
  /** The axis' visible range, as Plotly holds it (either order). */
  range: readonly [number, number];
  /** Value the uncropped axis would start at. The break hides when the range reaches it. */
  zero?: number;
  /** Rendered tick labels of this axis, measured. */
  ticks: readonly TickLabel[];
  /** Rendered bars / stacked segments, measured. */
  bars: readonly Box[];
  /** Length of the tick marks (0: none). */
  tickLen: number;
  tickWidth?: number;
  lineWidth?: number;
  /** false: the axis draws no line, so there is nothing to interrupt. */
  showLine?: boolean;
  style: AxisBreakStyle;
  /** Axis letter, for the caption ("y axis starts at 85%"). */
  axisName: string;
  /** The range floor as the axis would print it. */
  floorText: string;
  /** Text of the label at the cut; default the nearest tick's text with its number replaced by `zero`. */
  cutLabel?: string;
  options?: AxisBreakOptions;
}

export interface RectPrim {
  t: 'rect';
  cls: string;
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
}
export interface LinePrim {
  t: 'line';
  cls: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  stroke: string;
  width: number;
  cap: 'butt' | 'round';
}
export interface TextPrim {
  t: 'text';
  cls: string;
  x: number;
  y: number;
  text: string;
  fill: string;
  size: number;
  family: string;
  anchor: 'start' | 'middle' | 'end';
  /** Vertically centred on y unless 'auto' (the caption). */
  baseline?: 'central' | 'auto';
  italic?: boolean;
  opacity?: number;
}
export type Prim = RectPrim | LinePrim | TextPrim;

export interface AxisBreak {
  prims: Prim[];
  /** The marker's own numbers, for assertions and for callers that align things to it. */
  marker: {
    /** px from the cropped end to the centre of the `//`. */
    offset: number;
    /** px between the two slashes: the height (width, if horizontal) of a hole. */
    gap: number;
    /** px of the empty axis piece, along the axis, on either side of the centre. */
    halfGap: number;
  };
}

export const AXIS_BREAK_CAPTION_Y = 14;

/** Smallest axis the marker is drawn on: beyond `zoneTop`, room for real ticks. */
const MIN_AXIS_BEYOND_PX = 24;

/**
 * Primitives of one axis break, or null when the axis is not cropped (the
 * range reaches `zero`) or too short to hold the marker.
 */
export function computeAxisBreak(input: AxisBreakInput): AxisBreak | null {
  const { geometry: g, style } = input;
  const isY = g.vertical;
  const [r0, r1] = input.range;
  const lo = Math.min(r0, r1);
  const zero = input.zero ?? 0;
  if (!(lo > zero)) return null;

  const o = input.options ?? {};
  const S = o.size ?? 6;
  const gap = o.gap ?? 7;
  const d = S * 0.45; // a slash is 2S across the axis and 2d along it
  const halfGap = gap / 2 + (o.clear ?? 4); // the empty piece of axis
  const off = o.offset ?? 20;
  const zoneTop = off + halfGap + 2; // ticks beyond it are real
  if (zoneTop + MIN_AXIS_BEYOND_PX > g.length) return null;

  const start = g.start;
  const end = g.lowFirst === isY ? start + g.length : start; // px of the cropped end
  const s = end === start ? 1 : -1; // direction into the plot
  const out = isY === g.far ? 1 : -1; // where tick labels sit, away from the axis
  const k = isY ? 1 : -1; // both orientations get "/" slashes
  const uOf = (a: number) => (a - end) * s; // px along the axis -> px from the cropped end
  const perp = g.line;

  const lw = Math.max(input.lineWidth ?? 1, 1.5);
  const prims: Prim[] = [];
  // u along the axis (from the cropped end inwards), v across it -> px
  const P = (u: number, v: number): [number, number] => {
    const a = end + s * u;
    return isY ? [perp + v, a] : [a, perp + v];
  };
  const line = (p: [number, number], q: [number, number], stroke: string, width: number, cap: LinePrim['cap'], cls: string) =>
    prims.push({ t: 'line', cls, x1: p[0], y1: p[1], x2: q[0], y2: q[1], stroke, width, cap });

  // --- tick labels near the cropped end: cover them, label the cut instead ---
  const along = (x: Box) => (isY ? (x.t + x.b) / 2 : (x.l + x.r) / 2);
  const half = (x: Box) => (isY ? (x.b - x.t) / 2 : (x.r - x.l) / 2);
  const ticks = input.ticks.filter((x) => x.r > x.l);
  const inZone = ticks.filter((x) => uOf(along(x)) < zoneTop);
  const above = ticks.filter((x) => uOf(along(x)) >= zoneTop).sort((a, b) => uOf(along(a)) - uOf(along(b)));
  const ref = above[0] ?? inZone[0];
  const tickLen = input.tickLen;
  const acrossReach = (x: Box) => out * ((isY ? (out < 0 ? x.l : x.r) : out < 0 ? x.t : x.b) - perp);
  const reach = Math.max(tickLen + 3, ...inZone.map(acrossReach));
  const u0 = -Math.max(8, ...inZone.map(half)) - 0.5;
  const u1 = Math.max(zoneTop, ...inZone.map((x) => uOf(along(x)) + half(x)));
  const pa = [P(u0, 0), P(u1, 0)].map((p) => (isY ? p[1] : p[0])).sort((a, b) => a - b); // along-axis extent of the cover
  const pp = [perp + out * 1.1, perp + out * (reach + 1)].sort((a, b) => a - b); // across: labels and tick marks only
  prims.push({
    t: 'rect',
    cls: 'ab-cover',
    fill: style.bg,
    x: isY ? pp[0] : pa[0],
    y: isY ? pa[0] : pp[0],
    w: isY ? pp[1] - pp[0] : pa[1] - pa[0],
    h: isY ? pa[1] - pa[0] : pp[1] - pp[0],
  });
  if (tickLen) {
    line(
      isY ? [perp, end] : [end, perp],
      isY ? [perp + out * tickLen, end] : [end, perp + out * tickLen],
      style.tick,
      input.tickWidth || 1,
      'butt',
      'ab-tick',
    );
  }

  // The cut label sits where the real ones do: the first real tick's text with
  // its number swapped for the cut value, so "85%" gives "0%" and "1,200" "0".
  const sample = ref ? ref.text : '';
  const cutText = input.cutLabel ?? (/\d/.test(sample) ? sample.replace(/\d[\d.,]*/, String(zero)) : String(zero));
  const tx = isY ? (ref ? (out < 0 ? ref.r : ref.l) : perp + out * (tickLen + 3)) : end;
  const ty = isY ? end : ref ? (ref.t + ref.b) / 2 : perp + out * (tickLen + 3 + style.fontSize * 0.6);
  prims.push({
    t: 'text',
    cls: 'ab-cutlabel',
    x: tx,
    y: ty,
    text: cutText,
    fill: style.label,
    size: style.fontSize,
    family: style.fontFamily,
    anchor: isY ? (out < 0 ? 'end' : 'start') : 'middle',
  });

  // --- bars: a rectangular background-coloured hole, level with the `//` ---
  // As tall as the gap between the slashes, exactly the bar's width.
  if (o.band !== false) {
    const [cs, ce] = isY ? [g.plot.l, g.plot.l + g.plot.w] : [g.plot.t, g.plot.t + g.plot.h];
    const [h0, h1] = [end + s * (off - gap / 2), end + s * (off + gap / 2)].sort((m, n) => m - n);
    for (const b of input.bars) {
      const x0 = Math.max(isY ? b.l : b.t, cs);
      const x1 = Math.min(isY ? b.r : b.b, ce);
      if (x1 - x0 < 2) continue;
      const ua = uOf(isY ? b.t : b.l);
      const ub = uOf(isY ? b.b : b.r);
      const uMin = Math.min(ua, ub);
      const uMax = Math.max(ua, ub);
      if (uMin > off + gap / 2 || uMax < off + gap / 2 + 1) continue; // the bar must reach beyond the break
      prims.push({
        t: 'rect',
        cls: 'ab-hole',
        fill: style.bg,
        x: isY ? x0 : h0,
        y: isY ? h0 : x0,
        w: isY ? x1 - x0 : h1 - h0,
        h: isY ? h1 - h0 : x1 - x0,
      });
    }
  }

  // --- the break itself: an empty piece of axis, then the two slashes ---
  if (input.showLine !== false) {
    line(P(off - halfGap, 0), P(off + halfGap, 0), style.bg, lw + 3, 'butt', 'ab-gap');
  }
  for (const c of [off - gap / 2, off + gap / 2]) {
    line(P(c - d, -k * S), P(c + d, k * S), style.line, lw, 'round', 'ab-slash');
  }

  if (o.caption !== false) {
    prims.push({
      t: 'text',
      cls: 'ab-caption',
      x: g.plot.l,
      y: AXIS_BREAK_CAPTION_Y,
      text: `${input.axisName} axis starts at ${input.floorText}`,
      fill: style.caption,
      size: 11,
      family: style.fontFamily,
      anchor: 'start',
      baseline: 'auto',
      italic: true,
      opacity: 0.85,
    });
  }
  return { prims, marker: { offset: off, gap, halfGap } };
}

// ---------------------------------------------------------------------------
// Colours
// ---------------------------------------------------------------------------

export type Rgba = [number, number, number, number];

/** `#rgb`, `#rrggbb`, `rgb()` and `rgba()` (comma or space syntax); null for anything else. */
export function parseCssColor(value: string | null | undefined): Rgba | null {
  if (!value) return null;
  const v = value.trim().toLowerCase();
  if (v === 'transparent') return [0, 0, 0, 0];
  let m = /^#([0-9a-f]{3,8})$/.exec(v);
  if (m) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join('');
    if (h.length !== 6 && h.length !== 8) return null;
    const n = (i: number) => parseInt(h.slice(i, i + 2), 16);
    return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
  }
  m = /^rgba?\(([^)]*)\)$/.exec(v);
  if (!m) return null;
  const parts = m[1].split(/[\s,/]+/).filter(Boolean);
  if (parts.length < 3) return null;
  const ch = (p: string) => (p.endsWith('%') ? (parseFloat(p) / 100) * 255 : parseFloat(p));
  const rgb = parts.slice(0, 3).map(ch);
  let a = 1;
  if (parts[3] != null) a = parts[3].endsWith('%') ? parseFloat(parts[3]) / 100 : parseFloat(parts[3]);
  if (rgb.some((x) => !Number.isFinite(x)) || !Number.isFinite(a)) return null;
  return [rgb[0], rgb[1], rgb[2], Math.min(1, Math.max(0, a))];
}

export function cssColor([r, g, b, a]: Rgba): string {
  const c = (x: number) => Math.round(Math.min(255, Math.max(0, x)));
  return a >= 1 ? `rgb(${c(r)}, ${c(g)}, ${c(b)})` : `rgba(${c(r)}, ${c(g)}, ${c(b)}, ${+a.toFixed(3)})`;
}

/**
 * What a figure with a transparent background looks like: the backgrounds of
 * its ancestors, innermost first, composited down to the first opaque one.
 * Layers that do not parse are skipped; with no opaque layer the result sits
 * on `fallback`.
 */
export function effectiveBackground(layers: readonly (string | null | undefined)[], fallback: string): string {
  const base = parseCssColor(fallback) ?? [255, 255, 255, 1];
  const stack: Rgba[] = [];
  for (const layer of layers) {
    const c = parseCssColor(layer);
    if (!c || c[3] <= 0) continue;
    stack.push(c);
    if (c[3] >= 1) break;
  }
  let acc: Rgba = stack.length && stack[stack.length - 1][3] >= 1 ? stack.pop()! : base;
  while (stack.length) {
    const top = stack.pop()!;
    const a = top[3];
    acc = [top[0] * a + acc[0] * (1 - a), top[1] * a + acc[1] * (1 - a), top[2] * a + acc[2] * (1 - a), 1];
  }
  return cssColor(acc);
}

/** Alpha above which a colour reads as a drawn line rather than a hairline hint. */
const SOLID_ALPHA = 0.5;

/** The axis line's own colour when it is solid enough to carry the slashes, else `fallback`. */
export function slashColour(lineColour: string | null | undefined, fallback: string): string {
  const c = parseCssColor(lineColour);
  return c && c[3] >= SOLID_ALPHA ? (lineColour as string) : fallback;
}
