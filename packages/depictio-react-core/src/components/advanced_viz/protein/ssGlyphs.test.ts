import { describe, expect, it } from 'vitest';

import { roundRectPath } from './canvas';
import { rgbCss, SECONDARY_STRUCTURE_COLOURS, type SecondaryStructure } from './residueColours';
import type { Run } from './sequence';
import {
  drawCoil,
  drawHelix,
  drawSecondaryStructureRuns,
  drawStrand,
  drawTurn,
  SS_GLYPH_FILLS,
  TURN_THICKNESS,
} from './ssGlyphs';

type Call = [string, ...unknown[]];

/** A 2D context that records every path call and every style assignment. */
function recorder(opts: { roundRect?: boolean } = {}) {
  const calls: Call[] = [];
  const log =
    (name: string) =>
    (...args: unknown[]) => {
      calls.push([name, ...args]);
    };
  const ctx: Record<string, unknown> = {
    beginPath: log('beginPath'),
    closePath: log('closePath'),
    moveTo: log('moveTo'),
    lineTo: log('lineTo'),
    rect: log('rect'),
    fill: log('fill'),
    stroke: log('stroke'),
    fillRect: log('fillRect'),
  };
  if (opts.roundRect !== false) ctx.roundRect = log('roundRect');
  for (const prop of ['fillStyle', 'strokeStyle', 'lineWidth']) {
    Object.defineProperty(ctx, prop, {
      set: (v: unknown) => {
        calls.push([prop, v]);
      },
      get: () => undefined,
    });
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

const names = (calls: Call[]) => calls.map((c) => c[0]);

describe('drawHelix', () => {
  it('fills a rounded bar inset by 1 px, with a full-height radius', () => {
    const { ctx, calls } = recorder();
    drawHelix(ctx, 10, 60, 20, 12, 'red');
    expect(calls).toEqual([
      ['fillStyle', 'red'],
      ['beginPath'],
      ['roundRect', 10, 15, 50, 10, 6],
      ['fill'],
    ]);
  });

  it('caps the radius at half the width of a short helix', () => {
    const { ctx, calls } = recorder();
    drawHelix(ctx, 0, 6, 20, 12, 'red');
    expect(calls.find((c) => c[0] === 'roundRect')).toEqual(['roundRect', 0, 15, 6, 10, 3]);
  });

  it('falls back to a plain rectangle where the canvas has no roundRect', () => {
    const { ctx, calls } = recorder({ roundRect: false });
    drawHelix(ctx, 10, 60, 20, 12, 'red');
    expect(calls).toEqual([
      ['fillStyle', 'red'],
      ['beginPath'],
      ['rect', 10, 15, 50, 10],
      ['fill'],
    ]);
  });
});

describe('drawStrand', () => {
  it('traces a shaft and an arrow head the height of the lane', () => {
    const { ctx, calls } = recorder();
    drawStrand(ctx, 10, 60, 20, 10, 'gold');
    // w = 50, head = min(0.4 * 50, 0.7 * 10) = 7: the shaft ends at x = 53.
    expect(calls).toEqual([
      ['fillStyle', 'gold'],
      ['beginPath'],
      ['moveTo', 10, 17.5],
      ['lineTo', 53, 17.5],
      ['lineTo', 53, 15],
      ['lineTo', 60, 20],
      ['lineTo', 53, 25],
      ['lineTo', 53, 22.5],
      ['lineTo', 10, 22.5],
      ['closePath'],
      ['fill'],
    ]);
  });

  it('shrinks the head to 40% of the width on a short strand', () => {
    const { ctx, calls } = recorder();
    drawStrand(ctx, 0, 10, 20, 10, 'gold');
    const lineTos = calls.filter((c) => c[0] === 'lineTo');
    expect(lineTos[0]).toEqual(['lineTo', 6, 17.5]);
    expect(lineTos[2]).toEqual(['lineTo', 10, 20]);
  });
});

describe('drawTurn', () => {
  it('fills a thick bar centred on the line', () => {
    const { ctx, calls } = recorder();
    drawTurn(ctx, 10, 34, 20, 'blue');
    expect(TURN_THICKNESS).toBe(3);
    expect(calls).toEqual([
      ['fillStyle', 'blue'],
      ['fillRect', 10, 18.5, 24, 3],
    ]);
  });
});

describe('drawCoil', () => {
  it('strokes a 1 px line half a pixel under the centre', () => {
    const { ctx, calls } = recorder();
    drawCoil(ctx, 10, 90, 20, 'grey');
    expect(calls).toEqual([
      ['strokeStyle', 'grey'],
      ['lineWidth', 1],
      ['beginPath'],
      ['moveTo', 10, 20.5],
      ['lineTo', 90, 20.5],
      ['stroke'],
    ]);
  });
});

describe('drawSecondaryStructureRuns', () => {
  const runs: Run<SecondaryStructure>[] = [
    { start: 1, end: 3, value: 'helix' },
    { start: 4, end: 5, value: 'coil' },
    { start: 6, end: 8, value: 'strand' },
    { start: 9, end: 9, value: 'turn' },
    { start: 20, end: 22, value: 'helix' },
  ];
  // Residue p's cell starts at 10 + 8 (p - 1).
  const geometry = { xOf: (p: number) => 10 + 8 * (p - 1), cellWidth: 8, yMid: 20, height: 12 };

  it('draws each run as its glyph over its first to last cell', () => {
    const { ctx, calls } = recorder();
    drawSecondaryStructureRuns(ctx, runs.slice(0, 4), geometry);
    expect(calls.filter((c) => c[0] === 'roundRect')).toEqual([['roundRect', 10, 15, 24, 10, 6]]);
    const strand = calls.filter((c) => c[0] === 'moveTo');
    // The strand starts at residue 6: x = 50, 3 cells wide.
    expect(strand).toEqual([['moveTo', 50, 17]]);
    expect(calls.filter((c) => c[0] === 'fillRect')).toEqual([['fillRect', 74, 18.5, 8, 3]]);
    expect(calls.filter((c) => c[0] === 'fillStyle').map((c) => c[1])).toEqual([
      SS_GLYPH_FILLS.helix,
      SS_GLYPH_FILLS.strand,
      SS_GLYPH_FILLS.turn,
    ]);
  });

  it('leaves coil runs to the caller unless it gives a coil colour', () => {
    const plain = recorder();
    drawSecondaryStructureRuns(plain.ctx, runs.slice(0, 4), geometry);
    expect(names(plain.calls)).not.toContain('stroke');

    const coiled = recorder();
    drawSecondaryStructureRuns(coiled.ctx, runs.slice(0, 4), geometry, { coil: 'grey' });
    const strokes = coiled.calls.filter((c) => c[0] === 'moveTo' || c[0] === 'stroke');
    expect(coiled.calls.filter((c) => c[0] === 'strokeStyle')).toEqual([['strokeStyle', 'grey']]);
    // The coil run 4-5 spans x = 34 to 50 on the centre line.
    expect(coiled.calls).toContainEqual(['moveTo', 34, 20.5]);
    expect(coiled.calls).toContainEqual(['lineTo', 50, 20.5]);
    expect(strokes.length).toBeGreaterThan(0);
  });

  it('skips runs wholly outside the visible window', () => {
    const { ctx, calls } = recorder();
    drawSecondaryStructureRuns(ctx, runs, { ...geometry, visible: [5, 10] });
    // Helix 1-3 and helix 20-22 are out of view; the strand and the turn remain.
    expect(names(calls)).not.toContain('roundRect');
    expect(calls.filter((c) => c[0] === 'fill')).toHaveLength(1);
    expect(calls.filter((c) => c[0] === 'fillRect')).toHaveLength(1);
    // A run that only touches the window is drawn whole.
    const touching = recorder();
    drawSecondaryStructureRuns(touching.ctx, runs, { ...geometry, visible: [3, 3] });
    expect(touching.calls.filter((c) => c[0] === 'roundRect')).toHaveLength(1);
  });

  it('takes its own fills', () => {
    const { ctx, calls } = recorder();
    drawSecondaryStructureRuns(ctx, runs.slice(0, 1), geometry, {
      fills: { helix: 'a', strand: 'b', turn: 'c' },
    });
    expect(calls[0]).toEqual(['fillStyle', 'a']);
  });

  it('defaults to the RasMol structure palette', () => {
    expect(SS_GLYPH_FILLS).toEqual({
      helix: rgbCss(SECONDARY_STRUCTURE_COLOURS.helix),
      strand: rgbCss(SECONDARY_STRUCTURE_COLOURS.strand),
      turn: rgbCss(SECONDARY_STRUCTURE_COLOURS.turn),
    });
  });
});

/**
 * The drawing `SequenceStrip` carried inline before the glyphs were shared,
 * written out as it was. The extraction must not move a single pixel, so the
 * shared helpers are compared with it call for call.
 */
function legacyStructureLane(
  ctx: CanvasRenderingContext2D,
  runs: readonly Run<SecondaryStructure>[],
  xOf: (p: number) => number,
  cw: number,
  cat: { y: number; h: number },
  window: [number, number],
  dimmed: string,
  baseline: [number, number],
): void {
  const [p0, p1] = window;
  const mid = cat.y + cat.h / 2;
  ctx.strokeStyle = dimmed;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(baseline[0], mid + 0.5);
  ctx.lineTo(baseline[1], mid + 0.5);
  ctx.stroke();
  for (const run of runs) {
    if (run.end < p0 || run.start > p1) continue;
    const x = xOf(run.start);
    const w = (run.end - run.start + 1) * cw;
    const ss = run.value;
    if (ss === 'coil') continue;
    const rgb = SECONDARY_STRUCTURE_COLOURS[ss];
    ctx.fillStyle = rgbCss(rgb);
    if (ss === 'helix') {
      roundRectPath(ctx, x, cat.y + 1, w, cat.h - 2, Math.min(cat.h / 2, w / 2));
      ctx.fill();
    } else if (ss === 'strand') {
      const head = Math.min(w * 0.4, cat.h * 0.7);
      ctx.beginPath();
      ctx.moveTo(x, mid - cat.h * 0.25);
      ctx.lineTo(x + w - head, mid - cat.h * 0.25);
      ctx.lineTo(x + w - head, cat.y);
      ctx.lineTo(x + w, mid);
      ctx.lineTo(x + w - head, cat.y + cat.h);
      ctx.lineTo(x + w - head, mid + cat.h * 0.25);
      ctx.lineTo(x, mid + cat.h * 0.25);
      ctx.closePath();
      ctx.fill();
    } else {
      ctx.fillRect(x, mid - 1.5, w, 3);
    }
  }
}

describe("equivalence with the strip's former inline drawing", () => {
  const runs: Run<SecondaryStructure>[] = [
    { start: 1, end: 1, value: 'helix' },
    { start: 2, end: 9, value: 'helix' },
    { start: 10, end: 12, value: 'coil' },
    { start: 13, end: 14, value: 'strand' },
    { start: 15, end: 31, value: 'strand' },
    { start: 32, end: 33, value: 'turn' },
    { start: 34, end: 60, value: 'helix' },
    { start: 61, end: 61, value: 'turn' },
    { start: 80, end: 85, value: 'strand' },
  ];

  const lanes = [
    { y: 0, h: 12 },
    { y: 21, h: 12 },
    { y: 40.35, h: 12.7 },
    { y: 3.3, h: 9.1 },
  ];
  const cellWidths = [0.05, 1, 3.7, 8, 24];
  const scrolls = [0, 13.3, 250.75];
  const windows: Array<[number, number]> = [
    [1, 90],
    [8, 40],
    [60, 62],
  ];

  function close(a: Call[], b: Call[]): void {
    expect(names(a)).toEqual(names(b));
    a.forEach((call, i) => {
      call.slice(1).forEach((arg, j) => {
        const other = b[i][j + 1];
        if (typeof arg === 'number') expect(other as number).toBeCloseTo(arg, 9);
        else expect(other).toBe(arg);
      });
    });
  }

  it('issues the same calls, in the same order, for every geometry', () => {
    for (const cat of lanes) {
      for (const cw of cellWidths) {
        for (const sx of scrolls) {
          for (const win of windows) {
            const xOf = (p: number) => 72 + (p - 1) * cw - sx;
            const baseline: [number, number] = [xOf(Math.max(1, win[0])), xOf(win[1] + 1)];
            const before = recorder();
            legacyStructureLane(before.ctx, runs, xOf, cw, cat, win, 'dim', baseline);

            const after = recorder();
            const mid = cat.y + cat.h / 2;
            drawCoil(after.ctx, baseline[0], baseline[1], mid, 'dim');
            drawSecondaryStructureRuns(after.ctx, runs, {
              xOf,
              cellWidth: cw,
              yMid: mid,
              height: cat.h,
              visible: win,
            });
            close(before.calls, after.calls);
          }
        }
      }
    }
  });
});
