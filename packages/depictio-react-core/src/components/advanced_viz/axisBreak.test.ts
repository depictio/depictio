import { describe, expect, it } from 'vitest';

import {
  computeAxisBreak,
  effectiveBackground,
  parseCssColor,
  slashColour,
  type AxisBreakInput,
  type Box,
  type LinePrim,
  type Prim,
  type RectPrim,
  type TextPrim,
  type TickLabel,
} from './axisBreak';

const STYLE = {
  line: 'rgb(30, 30, 30)',
  tick: 'rgb(30, 30, 30)',
  bg: 'rgb(255, 255, 255)',
  label: 'rgb(30, 30, 30)',
  caption: 'rgb(30, 30, 30)',
  fontSize: 12,
  fontFamily: 'sans-serif',
};

// A vertical chart: plot area 400 x 200 at (60, 30), axis line at x = 60,
// ticks every 40 px (85% .. 100%), bars 30 px wide.
const PLOT = { l: 60, t: 30, w: 400, h: 200 };
const V_TICKS: TickLabel[] = [
  { text: '85%', l: 30, r: 54, t: 224, b: 236 }, // the cropped end, y = 230
  { text: '90%', l: 30, r: 54, t: 144, b: 156 }, // 80 px up
  { text: '95%', l: 30, r: 54, t: 64, b: 76 },
  { text: '100%', l: 24, r: 54, t: 24, b: 36 },
];
const V_BARS: Box[] = [
  { l: 100, r: 130, t: 60, b: 230 }, // reaches the top
  { l: 200, r: 230, t: 150, b: 230 },
  { l: 300, r: 330, t: 215, b: 230 }, // 15 px tall: ends below the break
];

function vertical(over: Partial<AxisBreakInput> = {}): AxisBreakInput {
  return {
    geometry: { vertical: true, start: 30, length: 200, line: 60, lowFirst: true, far: false, plot: PLOT },
    range: [85, 100],
    ticks: V_TICKS,
    bars: V_BARS,
    tickLen: 5,
    style: STYLE,
    axisName: 'y',
    floorText: '85%',
    ...over,
  };
}

// The same chart on its side: value axis along the bottom, 0 at the left.
const H_PLOT = { l: 60, t: 30, w: 400, h: 200 };
const H_TICKS: TickLabel[] = [
  { text: '85%', l: 48, r: 72, t: 236, b: 248 }, // x = 60 is the cropped end
  { text: '90%', l: 128, r: 152, t: 236, b: 248 },
  { text: '95%', l: 228, r: 252, t: 236, b: 248 },
  { text: '100%', l: 428, r: 452, t: 236, b: 248 },
];
const H_BARS: Box[] = [
  { l: 60, r: 400, t: 50, b: 80 },
  { l: 60, r: 200, t: 110, b: 140 },
  { l: 60, r: 75, t: 170, b: 200 }, // 15 px long
];

function horizontal(over: Partial<AxisBreakInput> = {}): AxisBreakInput {
  return {
    geometry: { vertical: false, start: 60, length: 400, line: 230, lowFirst: true, far: false, plot: H_PLOT },
    range: [85, 100],
    ticks: H_TICKS,
    bars: H_BARS,
    tickLen: 5,
    style: STYLE,
    axisName: 'x',
    floorText: '85%',
    ...over,
  };
}

const byCls = <T extends Prim>(prims: Prim[], cls: string) => prims.filter((p) => p.cls === cls) as T[];
const mid = (a: number, b: number) => (a + b) / 2;

describe('computeAxisBreak: vertical value axis', () => {
  const r = computeAxisBreak(vertical())!;
  const gap = byCls<LinePrim>(r.prims, 'ab-gap')[0];
  const slashes = byCls<LinePrim>(r.prims, 'ab-slash');
  const holes = byCls<RectPrim>(r.prims, 'ab-hole');
  const cut = byCls<TextPrim>(r.prims, 'ab-cutlabel')[0];

  it('leaves a gap in the axis line, centred on the axis line and on the slashes', () => {
    expect(gap.x1).toBe(60);
    expect(gap.x2).toBe(60);
    // The cropped end is the bottom, y = 230; the marker is 20 px up.
    expect(mid(gap.y1, gap.y2)).toBeCloseTo(230 - r.marker.offset, 6);
    expect(Math.abs(gap.y1 - gap.y2)).toBeCloseTo(2 * r.marker.halfGap, 6);
    // The gap is empty axis: wider than the space between the slashes.
    expect(2 * r.marker.halfGap).toBeGreaterThan(r.marker.gap);
    expect(gap.stroke).toBe(STYLE.bg);
  });

  it('draws two slashes either side of the gap, crossing the axis line', () => {
    expect(slashes).toHaveLength(2);
    const centres = slashes.map((s) => mid(s.y1, s.y2)).sort((a, b) => a - b);
    expect(centres[1] - centres[0]).toBeCloseTo(r.marker.gap, 6);
    expect(mid(centres[0], centres[1])).toBeCloseTo(mid(gap.y1, gap.y2), 6);
    for (const s of slashes) {
      expect(mid(s.x1, s.x2)).toBeCloseTo(60, 6); // centred on the axis line
      expect(s.x2).toBeGreaterThan(s.x1);
      expect(s.y2).not.toBe(s.y1);
      expect(s.stroke).toBe(STYLE.line);
    }
    // "/": the right end is higher up the page (smaller y).
    expect(slashes[0].y2).toBeLessThan(slashes[0].y1);
  });

  it('cuts the bars that reach past the break, level with the gap and no taller than the marker', () => {
    expect(holes).toHaveLength(2); // the 15 px bar ends below it
    const centre = 230 - r.marker.offset;
    for (const h of holes) {
      expect(mid(h.y, h.y + h.h)).toBeCloseTo(centre, 6);
      expect(h.h).toBeLessThanOrEqual(r.marker.gap + 1e-9);
      expect(h.h).toBeCloseTo(r.marker.gap, 6);
      expect(h.fill).toBe(STYLE.bg);
    }
    // Exactly the bar's width.
    expect(holes.map((h) => [h.x, h.w])).toEqual([
      [100, 30],
      [200, 30],
    ]);
  });

  it('puts the cut label at the very end of the axis, aligned with the real tick labels', () => {
    expect(cut.text).toBe('0%');
    expect(cut.y).toBe(230);
    expect(cut.anchor).toBe('end');
    expect(cut.x).toBe(54); // the right edge of the 90% label
  });

  it('keeps the cut label clear of the first real tick', () => {
    const real = V_TICKS.filter((t) => 230 - mid(t.t, t.b) >= r.marker.offset + r.marker.halfGap + 2);
    expect(real.map((t) => t.text)).toEqual(['90%', '95%', '100%']);
    const first = real[0];
    const labelTop = cut.y - STYLE.fontSize / 2;
    expect(labelTop).toBeGreaterThan(first.b); // the cut label starts below the 90% label's box
    // And the stub label (85%) is covered, not left next to the marker.
    const cover = byCls<RectPrim>(r.prims, 'ab-cover')[0];
    const stub = V_TICKS[0];
    expect(cover.y).toBeLessThanOrEqual(stub.t);
    expect(cover.y + cover.h).toBeGreaterThanOrEqual(stub.b);
    expect(cover.x).toBeLessThanOrEqual(stub.l);
    // The cover stops short of the first real label.
    expect(cover.y).toBeGreaterThanOrEqual(first.b);
  });

  it('captions where the axis starts, top-left of the plot', () => {
    const cap = byCls<TextPrim>(r.prims, 'ab-caption')[0];
    expect(cap.text).toBe('y axis starts at 85%');
    expect(cap.x).toBe(PLOT.l);
  });
});

describe('computeAxisBreak: horizontal value axis', () => {
  const r = computeAxisBreak(horizontal())!;
  const gap = byCls<LinePrim>(r.prims, 'ab-gap')[0];
  const slashes = byCls<LinePrim>(r.prims, 'ab-slash');
  const holes = byCls<RectPrim>(r.prims, 'ab-hole');
  const cut = byCls<TextPrim>(r.prims, 'ab-cutlabel')[0];

  it('runs the gap along the axis line, 20 px in from the cropped end', () => {
    expect(gap.y1).toBe(230);
    expect(gap.y2).toBe(230);
    expect(mid(gap.x1, gap.x2)).toBeCloseTo(60 + r.marker.offset, 6);
  });

  it('draws "/" slashes (right end higher) centred on the axis line', () => {
    expect(slashes).toHaveLength(2);
    for (const s of slashes) {
      expect(mid(s.y1, s.y2)).toBeCloseTo(230, 6);
      expect(s.x2).toBeGreaterThan(s.x1);
      expect(s.y2).toBeLessThan(s.y1);
    }
    const centres = slashes.map((s) => mid(s.x1, s.x2)).sort((a, b) => a - b);
    expect(centres[1] - centres[0]).toBeCloseTo(r.marker.gap, 6);
    expect(mid(centres[0], centres[1])).toBeCloseTo(mid(gap.x1, gap.x2), 6);
  });

  it('cuts the bars with vertical rectangles level with the gap', () => {
    expect(holes).toHaveLength(2); // the 15 px bar does not reach the break
    for (const h of holes) {
      expect(mid(h.x, h.x + h.w)).toBeCloseTo(60 + r.marker.offset, 6);
      expect(h.w).toBeCloseTo(r.marker.gap, 6);
      expect(h.w).toBeLessThanOrEqual(r.marker.gap + 1e-9);
    }
    expect(holes.map((h) => [h.y, h.h])).toEqual([
      [50, 30],
      [110, 30],
    ]);
  });

  it('puts the cut label under the very end of the axis, level with the real labels', () => {
    expect(cut.text).toBe('0%');
    expect(cut.x).toBe(60);
    expect(cut.anchor).toBe('middle');
    expect(cut.y).toBe(mid(236, 248));
    // The 90% label (x 128..152) starts well clear of the 0% label.
    const halfWidth = 12;
    expect(cut.x + halfWidth).toBeLessThan(128);
  });
});

describe('computeAxisBreak: other cases', () => {
  it('draws nothing when the range reaches the zero value', () => {
    expect(computeAxisBreak(vertical({ range: [0, 100] }))).toBeNull();
    expect(computeAxisBreak(vertical({ range: [-5, 100] }))).toBeNull();
    expect(computeAxisBreak(vertical({ range: [0.5, 1], zero: 0.5 }))).toBeNull();
  });

  it('reads a reversed range the same way', () => {
    const r = computeAxisBreak(vertical({ range: [100, 85] }))!;
    expect(r).not.toBeNull();
  });

  it('draws nothing on an axis too short to hold the marker', () => {
    const geometry = { ...vertical().geometry, length: 40 };
    expect(computeAxisBreak(vertical({ geometry }))).toBeNull();
  });

  it('keeps the marker at the cropped end of a reversed axis', () => {
    // A value axis with its low end at the top: the marker follows it.
    const geometry = { ...vertical().geometry, lowFirst: false };
    const r = computeAxisBreak(vertical({ geometry, range: [100, 85] }))!;
    const gap = byCls<LinePrim>(r.prims, 'ab-gap')[0];
    expect(mid(gap.y1, gap.y2)).toBeCloseTo(30 + r.marker.offset, 6);
  });

  it('skips the holes and the caption when asked', () => {
    const r = computeAxisBreak(vertical({ options: { band: false, caption: false } }))!;
    expect(byCls(r.prims, 'ab-hole')).toHaveLength(0);
    expect(byCls(r.prims, 'ab-caption')).toHaveLength(0);
  });

  it('labels the cut with a count, not a percentage, when the ticks are counts', () => {
    const ticks = V_TICKS.map((t, i) => ({ ...t, text: ['1,200', '1,400', '1,600', '1,800'][i] }));
    const r = computeAxisBreak(vertical({ ticks, range: [1200, 1800], floorText: '1,200' }))!;
    expect(byCls<TextPrim>(r.prims, 'ab-cutlabel')[0].text).toBe('0');
  });

  it('draws no gap when the axis line is hidden', () => {
    const r = computeAxisBreak(vertical({ showLine: false }))!;
    expect(byCls(r.prims, 'ab-gap')).toHaveLength(0);
    expect(byCls(r.prims, 'ab-slash')).toHaveLength(2);
  });
});

describe('colours', () => {
  it('parses hex, rgb and rgba', () => {
    expect(parseCssColor('#fff')).toEqual([255, 255, 255, 1]);
    expect(parseCssColor('#1a1b1e')).toEqual([26, 27, 30, 1]);
    expect(parseCssColor('rgb(10, 20, 30)')).toEqual([10, 20, 30, 1]);
    expect(parseCssColor('rgba(0, 0, 0, 0)')).toEqual([0, 0, 0, 0]);
    expect(parseCssColor('rgba(255 255 255 / 50%)')).toEqual([255, 255, 255, 0.5]);
    expect(parseCssColor('oklch(0.5 0.1 200)')).toBeNull();
  });

  it('takes the first opaque background, skipping transparent layers', () => {
    expect(effectiveBackground(['rgba(0, 0, 0, 0)', 'rgb(20, 21, 23)', 'rgb(1, 2, 3)'], '#ffffff')).toBe('rgb(20, 21, 23)');
  });

  it('composites translucent layers over the one beneath', () => {
    expect(effectiveBackground(['rgba(255, 255, 255, 0.5)', 'rgb(0, 0, 0)'], '#ffffff')).toBe('rgb(128, 128, 128)');
  });

  it('falls back when nothing is drawn behind the plot', () => {
    expect(effectiveBackground(['rgba(0, 0, 0, 0)', 'transparent'], '#1a1b1e')).toBe('rgb(26, 27, 30)');
  });

  it('keeps a hairline axis colour out of the slashes', () => {
    expect(slashColour('rgba(0,0,0,0.08)', 'rgb(33, 37, 41)')).toBe('rgb(33, 37, 41)');
    expect(slashColour('rgb(55, 65, 81)', 'rgb(33, 37, 41)')).toBe('rgb(55, 65, 81)');
  });
});
