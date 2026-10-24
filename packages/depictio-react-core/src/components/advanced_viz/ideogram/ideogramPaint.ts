/**
 * Canvas painter for the ideogram: turns the overview and detail scenes into
 * pixels. Every decision (what is drawn, where, which bin, which colour index)
 * is made in `ideogramLayout.ts` / `ideogramView.ts`; this module only strokes
 * and fills, so it holds no state and no maths worth a test of its own.
 *
 * One canvas draws tens of thousands of features in a few milliseconds where
 * one SVG element per feature took seconds to mount and re-rendered on every
 * hover. Colours arrive resolved from the Mantine theme (a canvas cannot read
 * a CSS variable), so nothing here names a colour of its own.
 */

import { sampleColorscale } from '../../../utils/colorScale';
import type { ColourScale } from '../colourScales';
import {
  barForChrom,
  scaleT,
  spanRect,
  type ChromBar,
  type IdeogramFeature,
  type PanelGeom,
} from './ideogramLayout';
import {
  binAlpha,
  binValue,
  bpToX,
  dominantCategory,
  overlapping,
  windowTicks,
  type BinSet,
  type ChromIndex,
  type DetailGeom,
  type DrawnAs,
  type Window,
} from './ideogramView';

export interface PaintColours {
  barFill: string;
  barStroke: string;
  text: string;
  dimText: string;
  grid: string;
  highlight: string;
  fontFamily: string;
}

/** How a density bin takes its colour. */
export interface DensityStyle {
  /** `category`: dominant category, alpha by count. `value`: the bin mean on
   *  the scale. `count`: the bin count on the scale. */
  kind: 'category' | 'value' | 'count';
  catColours: readonly string[];
  /** 256 colours sampled from the sequential scale. */
  lut: readonly string[];
  /** Domain of the scale (`value` and `count`). */
  extent: [number, number];
  /** Highest count, for the category alpha. */
  maxCount: number;
}

export interface Region {
  chrom: string;
  start: number;
  end: number;
}

/** 256 CSS colours along a named scale, so a bin is a table lookup. */
export function scaleLut(name: ColourScale): string[] {
  return Array.from({ length: 256 }, (_, i) => {
    const [r, g, b] = sampleColorscale(name, i / 255);
    return `rgb(${r}, ${g}, ${b})`;
  });
}

export function lutColour(lut: readonly string[], t: number): string {
  return lut[Math.max(0, Math.min(255, Math.round(t * 255)))];
}

function font(colours: PaintColours, px: number, weight = 400): string {
  return `${weight} ${px}px ${colours.fontFamily}`;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

/** `text` cut with an ellipsis to fit `maxW` px. */
function fitText(ctx: CanvasRenderingContext2D, text: string, maxW: number): string {
  if (ctx.measureText(text).width <= maxW) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(`${text.slice(0, mid)}…`).width <= maxW) lo = mid;
    else hi = mid - 1;
  }
  return lo > 0 ? `${text.slice(0, lo)}…` : '';
}

/** Fill colour and alpha of bin `b`, or null for an empty one. */
function binFill(
  bins: BinSet,
  b: number,
  style: DensityStyle,
  opacity: number,
): { colour: string; alpha: number } | null {
  const count = bins.count[b];
  if (count === 0) return null;
  if (style.kind === 'category') {
    const c = dominantCategory(bins, b);
    const colour = c >= 0 ? style.catColours[c] : style.lut[200];
    return { colour, alpha: binAlpha(count, style.maxCount, opacity) };
  }
  const v = binValue(bins, b, style.kind === 'value');
  if (!Number.isFinite(v)) return null;
  return { colour: lutColour(style.lut, scaleT(v, style.extent[0], style.extent[1])), alpha: opacity };
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export interface PanelLayer {
  drawn: DrawnAs;
  index: Map<string, ChromIndex>;
  /** Bins per bar key, in density. */
  bins: Map<string, BinSet> | null;
}

export interface OverviewScene {
  panels: PanelGeom[];
  layers: PanelLayer[];
  features: readonly IdeogramFeature[];
  markColour: (f: IdeogramFeature) => string;
  density: DensityStyle;
  opacity: number;
  own: Region | null;
  followed: Region | null;
  colours: PaintColours;
}

function shadeRegion(
  ctx: CanvasRenderingContext2D,
  panel: PanelGeom,
  region: Region | null,
  colour: string,
  dashed: boolean,
) {
  if (!region) return;
  const geom = barForChrom(panel, region.chrom);
  if (!geom) return;
  const start = Number.isFinite(region.start) ? region.start : 0;
  const end = Number.isFinite(region.end) ? region.end : geom.bar.length;
  const r = spanRect(panel, geom, start, end, { minPx: 2, overhang: 4 });
  ctx.save();
  ctx.fillStyle = colour;
  ctx.globalAlpha = 0.16;
  ctx.fillRect(r.x, r.y, r.w, r.h);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = colour;
  ctx.lineWidth = 1.5;
  if (dashed) ctx.setLineDash([4, 3]);
  ctx.strokeRect(r.x - 1, r.y - 1, r.w + 2, r.h + 2);
  ctx.restore();
}

export function paintOverview(ctx: CanvasRenderingContext2D, scene: OverviewScene) {
  const { colours } = scene;
  scene.panels.forEach((panel, pi) => {
    const layer = scene.layers[pi];
    const horizontal = panel.orientation === 'horizontal';

    if (panel.title !== null) {
      ctx.fillStyle = colours.text;
      ctx.font = font(colours, 12, 600);
      ctx.textAlign = horizontal ? 'left' : 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText(
        fitText(ctx, panel.title, panel.w - 8),
        panel.x + (horizontal ? 4 : panel.w / 2),
        panel.y + 13,
      );
    }

    // A position axis: tick marks and labels in the panel's own furniture,
    // with the faintest of guides so the bars stay the figure.
    ctx.font = font(colours, 10);
    ctx.fillStyle = colours.dimText;
    ctx.strokeStyle = colours.grid;
    ctx.lineWidth = 1;
    for (const t of panel.ticks) {
      ctx.beginPath();
      if (horizontal) {
        ctx.moveTo(Math.round(t.px) + 0.5, panel.y + 16);
        ctx.lineTo(Math.round(t.px) + 0.5, panel.y + panel.h - 18);
      } else {
        ctx.moveTo(panel.x + 44, Math.round(t.px) + 0.5);
        ctx.lineTo(panel.x + panel.w - 4, Math.round(t.px) + 0.5);
      }
      ctx.stroke();
      if (horizontal) {
        ctx.textAlign = 'center';
        ctx.textBaseline = 'alphabetic';
        ctx.fillText(t.label, t.px, panel.y + panel.h - 6);
      } else {
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(t.label, panel.x + 40, t.px);
      }
    }

    // Bars and names.
    ctx.lineWidth = 0.75;
    const labelMax = horizontal && panel.bars.length ? panel.bars[0].x - panel.x - 10 : 80;
    for (const g of panel.bars) {
      roundRect(ctx, g.x, g.y, g.w, g.h, Math.min(g.w, g.h) / 2);
      ctx.fillStyle = colours.barFill;
      ctx.fill();
      ctx.strokeStyle = colours.barStroke;
      ctx.stroke();
      if (g.showLabel && (horizontal ? g.h >= 3 : true)) {
        ctx.fillStyle = colours.text;
        ctx.font = font(colours, horizontal ? Math.min(11, Math.max(8, g.h + 2)) : 10);
        ctx.textAlign = horizontal ? 'right' : 'center';
        ctx.textBaseline = horizontal ? 'middle' : 'alphabetic';
        ctx.fillText(fitText(ctx, g.bar.name, labelMax), g.labelX, g.labelY);
      }
    }

    // Features.
    if (layer.drawn === 'marks') {
      ctx.globalAlpha = scene.opacity;
      let last = '';
      for (const g of panel.bars) {
        const idx = layer.index.get(g.bar.key);
        if (!idx) continue;
        for (let k = 0; k < idx.order.length; k += 1) {
          const f = scene.features[idx.order[k]];
          const r = spanRect(panel, g, f.start, f.end, { minPx: 2, overhang: 3 });
          const colour = scene.markColour(f);
          if (colour !== last) {
            ctx.fillStyle = colour;
            last = colour;
          }
          ctx.fillRect(r.x, r.y, r.w, r.h);
        }
      }
      ctx.globalAlpha = 1;
    } else if (layer.bins) {
      for (const g of panel.bars) {
        const bins = layer.bins.get(g.bar.key);
        if (!bins) continue;
        paintPanelBins(ctx, panel, g, bins, scene);
      }
      ctx.globalAlpha = 1;
    }

    shadeRegion(ctx, panel, scene.followed, colours.highlight, true);
    shadeRegion(ctx, panel, scene.own, colours.highlight, false);
  });
}

function paintPanelBins(
  ctx: CanvasRenderingContext2D,
  panel: PanelGeom,
  g: PanelGeom['bars'][number],
  bins: BinSet,
  scene: OverviewScene,
) {
  for (const fi of bins.wide) {
    const f = scene.features[fi];
    if (f.value === null && scene.density.kind === 'value') continue;
    const r = spanRect(panel, g, f.start, f.end, { minPx: 1 });
    ctx.globalAlpha = scene.opacity;
    ctx.fillStyle =
      scene.density.kind === 'category'
        ? scene.markColour(f)
        : lutColour(scene.density.lut, scaleT(f.value ?? 1, scene.density.extent[0], scene.density.extent[1]));
    ctx.fillRect(r.x, r.y, r.w, r.h);
  }
  for (let b = 0; b < bins.count.length; b += 1) {
    const fill = binFill(bins, b, scene.density, scene.opacity);
    if (!fill) continue;
    const start = bins.origin + b * bins.binSize;
    const r = spanRect(panel, g, start, Math.min(g.bar.length, start + bins.binSize), { minPx: 1 });
    ctx.globalAlpha = fill.alpha;
    ctx.fillStyle = fill.colour;
    ctx.fillRect(r.x, r.y, r.w, r.h);
  }
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

export interface DetailScene {
  geom: DetailGeom;
  bar: ChromBar;
  title: string;
  window: Window;
  drawn: DrawnAs;
  index: ChromIndex | undefined;
  features: readonly IdeogramFeature[];
  /** Bins at the detail resolution (density), over the whole chromosome. */
  bins: BinSet | null;
  /** Coarse bins over the whole chromosome, for the locator strip. */
  locatorBins: BinSet | null;
  markColour: (f: IdeogramFeature) => string;
  density: DensityStyle;
  locatorDensity: DensityStyle;
  opacity: number;
  own: Region | null;
  followed: Region | null;
  /** Shift-drag zoom brush, in bp. */
  brush: [number, number] | null;
  colours: PaintColours;
}

function sameChrom(region: Region | null, bar: ChromBar, normalise: (c: string) => string): Region | null {
  if (!region) return null;
  return normalise(region.chrom) === bar.key ? region : null;
}

export function paintDetail(
  ctx: CanvasRenderingContext2D,
  scene: DetailScene,
  normalise: (c: string) => string,
) {
  const { geom, colours, window: w, bar } = scene;
  const body = geom.body;
  const L = bar.length;

  // Locator: the whole chromosome, thin, with the window outlined.
  const loc = geom.locator;
  roundRect(ctx, loc.x, loc.y, loc.w, loc.h, loc.h / 2);
  ctx.fillStyle = colours.barFill;
  ctx.fill();
  if (scene.locatorBins) {
    ctx.save();
    roundRect(ctx, loc.x, loc.y, loc.w, loc.h, loc.h / 2);
    ctx.clip();
    const lb = scene.locatorBins;
    const full = { start: 0, end: L };
    for (let b = 0; b < lb.count.length; b += 1) {
      const fill = binFill(lb, b, scene.locatorDensity, 1);
      if (!fill) continue;
      const s = lb.origin + b * lb.binSize;
      const x0 = bpToX(s, full, loc.x, loc.w);
      const x1 = bpToX(Math.min(L, s + lb.binSize), full, loc.x, loc.w);
      ctx.globalAlpha = Math.max(0.35, fill.alpha);
      ctx.fillStyle = fill.colour;
      ctx.fillRect(x0, loc.y, Math.max(1, x1 - x0), loc.h);
    }
    for (const fi of lb.wide) {
      const f = scene.features[fi];
      ctx.globalAlpha = 0.85;
      ctx.fillStyle =
        scene.locatorDensity.kind === 'category'
          ? scene.markColour(f)
          : lutColour(
              scene.locatorDensity.lut,
              scaleT(f.value ?? 1, scene.locatorDensity.extent[0], scene.locatorDensity.extent[1]),
            );
      const x0 = bpToX(f.start, full, loc.x, loc.w);
      ctx.fillRect(x0, loc.y, Math.max(1, bpToX(f.end, full, loc.x, loc.w) - x0), loc.h);
    }
    ctx.restore();
    ctx.globalAlpha = 1;
  }
  roundRect(ctx, loc.x, loc.y, loc.w, loc.h, loc.h / 2);
  ctx.strokeStyle = colours.barStroke;
  ctx.lineWidth = 0.75;
  ctx.stroke();
  const full = { start: 0, end: L };
  const vx0 = bpToX(w.start, full, loc.x, loc.w);
  const vx1 = bpToX(w.end, full, loc.x, loc.w);
  ctx.strokeStyle = colours.highlight;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(vx0, loc.y - 2, Math.max(2, vx1 - vx0), loc.h + 4);
  // Lines from the outlined window down to the body: the zoom reads as a lens
  // (none at full extent, where they would only box the title in).
  if (w.start > 0 || w.end < L) {
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(vx0, loc.y + loc.h + 2);
    ctx.lineTo(body.x, body.y - 1);
    ctx.moveTo(vx0 + Math.max(2, vx1 - vx0), loc.y + loc.h + 2);
    ctx.lineTo(body.x + body.w, body.y - 1);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Body.
  const radius = Math.min(body.h / 2, 10);
  const atStart = w.start <= 0;
  const atEnd = w.end >= L;
  // Rounded ends only where the window reaches a telomere: a body cut by the
  // window runs on past the canvas edge, clipped square.
  ctx.save();
  ctx.beginPath();
  ctx.rect(body.x, body.y - 6, body.w, body.h + 12);
  ctx.clip();
  roundRect(
    ctx,
    body.x - (atStart ? 0 : radius + 2),
    body.y,
    body.w + (atStart ? 0 : radius + 2) + (atEnd ? 0 : radius + 2),
    body.h,
    radius,
  );
  ctx.fillStyle = colours.barFill;
  ctx.fill();
  ctx.strokeStyle = colours.barStroke;
  ctx.lineWidth = 1;
  ctx.stroke();

  // Features in the window.
  const x = (bp: number) => bpToX(bp, w, body.x, body.w);
  if (scene.drawn === 'marks' && scene.index) {
    ctx.globalAlpha = scene.opacity;
    let last = '';
    for (const k of overlapping(scene.index, w.start, w.end)) {
      const f = scene.features[scene.index.order[k]];
      let x0 = x(f.start);
      let wd = x(f.end) - x0;
      let y0 = body.y + 1;
      let h = body.h - 2;
      if (wd < 2) {
        x0 = (x0 + x0 + wd) / 2 - 1;
        wd = 2;
        y0 = body.y - 4;
        h = body.h + 8;
      }
      const colour = scene.markColour(f);
      if (colour !== last) {
        ctx.fillStyle = colour;
        last = colour;
      }
      ctx.fillRect(x0, y0, wd, h);
    }
    ctx.globalAlpha = 1;
  } else if (scene.bins) {
    const bins = scene.bins;
    for (const fi of bins.wide) {
      const f = scene.features[fi];
      if (f.end < w.start || f.start > w.end) continue;
      const x0 = Math.max(body.x, x(f.start));
      const x1 = Math.min(body.x + body.w, x(f.end));
      ctx.globalAlpha = scene.opacity;
      ctx.fillStyle =
        scene.density.kind === 'category'
          ? scene.markColour(f)
          : lutColour(scene.density.lut, scaleT(f.value ?? 1, scene.density.extent[0], scene.density.extent[1]));
      ctx.fillRect(x0, body.y + 1, Math.max(1, x1 - x0), body.h - 2);
    }
    const first = Math.max(0, Math.floor((w.start - bins.origin) / bins.binSize));
    const lastBin = Math.min(bins.count.length - 1, Math.floor((w.end - bins.origin) / bins.binSize));
    for (let b = first; b <= lastBin; b += 1) {
      const fill = binFill(bins, b, scene.density, scene.opacity);
      if (!fill) continue;
      const s = bins.origin + b * bins.binSize;
      const x0 = x(s);
      const x1 = x(Math.min(L, s + bins.binSize));
      ctx.globalAlpha = fill.alpha;
      ctx.fillStyle = fill.colour;
      ctx.fillRect(x0, body.y + 1, Math.max(1, x1 - x0), body.h - 2);
    }
    ctx.globalAlpha = 1;
  }

  // Regions: this tile's own filter solid, another tile's dashed.
  for (const [region, dashed] of [
    [sameChrom(scene.followed, bar, normalise), true],
    [sameChrom(scene.own, bar, normalise), false],
  ] as const) {
    if (!region) continue;
    const s = Number.isFinite(region.start) ? region.start : 0;
    const e = Number.isFinite(region.end) ? region.end : L;
    const x0 = Math.max(body.x, x(s));
    const x1 = Math.min(body.x + body.w, x(e));
    if (x1 <= x0) continue;
    ctx.fillStyle = colours.highlight;
    ctx.globalAlpha = 0.14;
    ctx.fillRect(x0, body.y - 5, x1 - x0, body.h + 10);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = colours.highlight;
    ctx.lineWidth = 1.5;
    ctx.setLineDash(dashed ? [4, 3] : []);
    ctx.strokeRect(x0, body.y - 5, x1 - x0, body.h + 10);
    ctx.setLineDash([]);
  }
  ctx.restore();

  // Axis.
  ctx.strokeStyle = colours.barStroke;
  ctx.fillStyle = colours.dimText;
  ctx.font = font(colours, 10);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(body.x, geom.axisY + 0.5);
  ctx.lineTo(body.x + body.w, geom.axisY + 0.5);
  ctx.stroke();
  for (const t of windowTicks(w, body.x, body.w)) {
    ctx.beginPath();
    ctx.moveTo(Math.round(t.x) + 0.5, geom.axisY);
    ctx.lineTo(Math.round(t.x) + 0.5, geom.axisY + 5);
    ctx.stroke();
    ctx.fillText(t.label, Math.min(body.x + body.w - 18, Math.max(body.x + 18, t.x)), geom.axisY + 17);
  }

  // Title over the body.
  ctx.fillStyle = colours.text;
  ctx.font = font(colours, 12, 600);
  ctx.textAlign = 'left';
  ctx.fillText(fitText(ctx, scene.title, body.w * 0.7), body.x, body.y - 8);

  if (scene.brush) {
    const x0 = x(Math.min(scene.brush[0], scene.brush[1]));
    const x1 = x(Math.max(scene.brush[0], scene.brush[1]));
    ctx.fillStyle = colours.highlight;
    ctx.globalAlpha = 0.22;
    ctx.fillRect(x0, body.y - 8, x1 - x0, body.h + 16);
    ctx.globalAlpha = 1;
  }
}

// ---------------------------------------------------------------------------
// Hover overlay
// ---------------------------------------------------------------------------

export interface HoverMark {
  /** Outline drawn around the hovered thing. */
  rect: { x: number; y: number; w: number; h: number } | null;
  /** Vertical guide at this x (detail view). */
  guideX: number | null;
  guideTop: number;
  guideBottom: number;
}

export function paintHover(ctx: CanvasRenderingContext2D, hover: HoverMark | null, colours: PaintColours) {
  if (!hover) return;
  if (hover.guideX !== null) {
    ctx.strokeStyle = colours.text;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(Math.round(hover.guideX) + 0.5, hover.guideTop);
    ctx.lineTo(Math.round(hover.guideX) + 0.5, hover.guideBottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }
  if (hover.rect) {
    const r = hover.rect;
    ctx.strokeStyle = colours.highlight;
    ctx.lineWidth = 2;
    ctx.strokeRect(r.x - 1, r.y - 1, Math.max(2, r.w) + 2, r.h + 2);
  }
}

/** Size `canvas` to `w` x `h` CSS px at the device pixel ratio; returns its context, scaled. */
export function prepareCanvas(
  canvas: HTMLCanvasElement,
  w: number,
  h: number,
): CanvasRenderingContext2D | null {
  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
  const pw = Math.max(1, Math.round(w * dpr));
  const ph = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== pw) canvas.width = pw;
  if (canvas.height !== ph) canvas.height = ph;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return ctx;
}
