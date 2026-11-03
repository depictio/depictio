/**
 * The DOM half of the truncated-axis marker: measures a Plotly graph div,
 * runs the pure geometry (axisBreak.ts) and draws the primitives in an svg
 * layer on top of the figure.
 *
 * The layer lives inside Plotly's own top svg, so it shares the figure's pixel
 * space and its size; it is `pointer-events: none` (hover and zoom keep
 * working) and nothing is written into `layout`. It is redrawn on
 * plotly_afterplot / relayout / relayouting, which covers zoom, pan, resize,
 * autosize and theme changes, and it hides itself when the range reaches the
 * zero value again.
 *
 * Not part of Plotly's own image export (the modebar camera re-renders the
 * figure from data + layout into a hidden div): the overlay is a DOM layer.
 */
import {
  computeAxisBreak,
  effectiveBackground,
  slashColour,
  type AxisBreakOptions,
  type Box,
  type Prim,
  type TickLabel,
} from './axisBreak';

const SVG_NS = 'http://www.w3.org/2000/svg';
const EVENTS = ['plotly_afterplot', 'plotly_relayout', 'plotly_relayouting'] as const;
const LAYER_CLASS = 'depictio-axis-break';

export interface AxisBreakSpec {
  /** Layout axis that carries the values. */
  axis: 'x' | 'y';
  /** The range floor as the caption prints it ("85%"); `span` is the visible range, for the decimals. */
  formatFloor: (floor: number, span: number) => string;
  /** Value the uncropped axis would start at (default 0). */
  zero?: number;
  /** Page colour behind the plot, used when the figure and its ancestors are all transparent. */
  fallbackBg: string;
  options?: AxisBreakOptions;
}

interface State {
  spec: AxisBreakSpec;
  handler: () => void;
  raf: number | null;
}

type GraphDiv = HTMLElement & {
  _fullLayout?: any;
  on?: (event: string, fn: () => void) => void;
  removeListener?: (event: string, fn: () => void) => void;
  __depictioAxisBreak?: State;
};

/**
 * Attach, update or (spec null) remove the marker on a graph div. Idempotent:
 * one set of listeners per graph div however often it is called, so a renderer
 * can call it from every render / onUpdate.
 */
export function syncAxisBreak(gdLike: unknown, spec: AxisBreakSpec | null): void {
  const gd = gdLike as GraphDiv | null;
  if (!gd || typeof gd.on !== 'function') return;
  const held = gd.__depictioAxisBreak;
  if (!spec) {
    if (held) detach(gd, held);
    removeLayer(gd);
    return;
  }
  if (held) {
    held.spec = spec;
  } else {
    const state: State = { spec, handler: () => draw(gd), raf: null };
    gd.__depictioAxisBreak = state;
    EVENTS.forEach((e) => gd.on!(e, state.handler));
  }
  const state = gd.__depictioAxisBreak!;
  draw(gd);
  // One more pass a frame later: a theme switch updates the page colours
  // after the figure's own update has already fired.
  if (state.raf != null) cancelAnimationFrame(state.raf);
  state.raf = requestAnimationFrame(() => {
    state.raf = null;
    if (gd.__depictioAxisBreak === state) draw(gd);
  });
}

function detach(gd: GraphDiv, state: State): void {
  EVENTS.forEach((e) => gd.removeListener?.(e, state.handler));
  if (state.raf != null) cancelAnimationFrame(state.raf);
  delete gd.__depictioAxisBreak;
}

function removeLayer(gd: GraphDiv): void {
  gd.querySelectorAll(`.${LAYER_CLASS}`).forEach((n) => n.remove());
}

function draw(gd: GraphDiv): void {
  const state = gd.__depictioAxisBreak;
  const fl = gd._fullLayout;
  if (!state || !fl?._size || !fl._toppaper) return;
  const svg = fl._toppaper.node() as SVGSVGElement | null;
  if (!svg) return;
  let layer = svg.querySelector(`:scope > .${LAYER_CLASS}`);
  if (!layer) {
    layer = document.createElementNS(SVG_NS, 'g');
    layer.setAttribute('class', LAYER_CLASS);
    layer.setAttribute('pointer-events', 'none');
    // Above traces and axes, below the hover labels.
    svg.insertBefore(layer, svg.querySelector(':scope > .hoverlayer'));
  }
  const prims = measure(gd, state.spec, svg);
  layer.replaceChildren();
  if (prims) renderPrims(layer, prims);
}

/** Ancestors' background colours, innermost first. */
function backgroundLayers(gd: HTMLElement): string[] {
  const out: string[] = [];
  for (let el: HTMLElement | null = gd; el; el = el.parentElement) {
    out.push(getComputedStyle(el).backgroundColor);
  }
  return out;
}

function measure(gd: GraphDiv, spec: AxisBreakSpec, svg: SVGSVGElement): Prim[] | null {
  const fl = gd._fullLayout;
  const isY = spec.axis === 'y';
  const ax = fl[isY ? 'yaxis' : 'xaxis'];
  if (!ax || !Array.isArray(ax.range)) return null;
  const [r0, r1] = ax.range as [number, number];
  if (ax.type === 'log') return null; // a log axis is a crop of its own

  // Plotly's own numbers; the fallbacks rebuild them from _size + domain.
  const { l, t, w, h } = fl._size as { l: number; t: number; w: number; h: number };
  const [d0, d1] = ax.domain as [number, number];
  const cross = fl[String(ax.anchor || '').replace(/^([xy])/, '$1axis')];
  const [c0, c1] = cross ? (cross.domain as [number, number]) : [0, 1];
  const far = ax.side === 'right' || ax.side === 'top';
  const length: number = ax._length ?? (d1 - d0) * (isY ? h : w);
  const start: number = ax._offset ?? (isY ? t + (1 - d1) * h : l + d0 * w);
  const line: number = ax._mainLinePosition ?? (isY ? l + (far ? c1 : c0) * w : t + (1 - (far ? c1 : c0)) * h);

  const box = svg.getBoundingClientRect();
  const rel = (r: DOMRect): Box => ({ l: r.left - box.left, r: r.right - box.left, t: r.top - box.top, b: r.bottom - box.top });
  const ticks: TickLabel[] = [...gd.querySelectorAll<SVGTextElement>(`.${ax._id}tick text`)].map((e) => ({
    ...rel(e.getBoundingClientRect()),
    text: e.textContent ?? '',
  }));
  const bars: Box[] =
    spec.options?.band === false
      ? []
      : [...gd.querySelectorAll<SVGPathElement>('.barlayer .point path')].map((p) => rel(p.getBoundingClientRect()));

  const textColour: string = ax.color || fl.font?.color || 'currentColor';
  const lineColour = slashColour(ax.linecolor, textColour);
  const fontFamily = String((ax.tickfont && ax.tickfont.family) || fl.font?.family || 'sans-serif').replace(/"/g, "'");
  const result = computeAxisBreak({
    geometry: { vertical: isY, start, length, line, lowFirst: r0 < r1, far, plot: { l, t, w, h } },
    range: [r0, r1],
    zero: spec.zero,
    ticks,
    bars,
    tickLen: ax.ticks === 'outside' ? (ax.ticklen ?? 5) : 0,
    tickWidth: ax.tickwidth,
    lineWidth: ax.linewidth,
    showLine: ax.showline !== false,
    style: {
      line: lineColour,
      tick: ax.tickcolor || lineColour,
      bg: effectiveBackground(backgroundLayers(gd), spec.fallbackBg),
      label: (ax.tickfont && ax.tickfont.color) || textColour,
      caption: fl.font?.color || textColour,
      fontSize: (ax.tickfont && ax.tickfont.size) || fl.font?.size || 12,
      fontFamily,
    },
    axisName: spec.axis,
    floorText: spec.formatFloor(Math.min(r0, r1), Math.abs(r1 - r0)),
    options: spec.options,
  });
  return result ? result.prims : null;
}

function renderPrims(layer: Element, prims: readonly Prim[]): void {
  for (const p of prims) {
    const e = document.createElementNS(SVG_NS, p.t === 'rect' ? 'rect' : p.t === 'line' ? 'line' : 'text');
    const attrs: Record<string, string | number> = { class: p.cls };
    if (p.t === 'rect') {
      Object.assign(attrs, { x: p.x, y: p.y, width: Math.max(p.w, 0), height: Math.max(p.h, 0), fill: p.fill });
    } else if (p.t === 'line') {
      Object.assign(attrs, {
        x1: p.x1,
        y1: p.y1,
        x2: p.x2,
        y2: p.y2,
        stroke: p.stroke,
        'stroke-width': p.width,
        'stroke-linecap': p.cap,
      });
    } else {
      Object.assign(attrs, {
        x: p.x,
        y: p.y,
        fill: p.fill,
        'font-size': p.size,
        'font-family': p.family.replace(/"/g, "'"),
        'text-anchor': p.anchor,
      });
      if (p.baseline !== 'auto') attrs['dominant-baseline'] = 'central';
      if (p.italic) attrs['font-style'] = 'italic';
      if (p.opacity != null) attrs.opacity = p.opacity;
      e.textContent = p.text;
    }
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, String(v)));
    layer.appendChild(e);
  }
}
