import { afterEach, describe, expect, it } from 'vitest';

import {
  atlasCellPx,
  atlasKey,
  clearGlyphAtlases,
  GlyphAtlas,
  glyphAtlasFor,
  inkBox,
  sheetRows,
  slotOrigin,
  type AtlasCanvas,
  type AtlasContext,
} from './glyphAtlas';

type Call = [string, ...unknown[]];

/** A canvas factory whose contexts record their calls; metrics are fixed. */
function fakeCanvases(metrics: Partial<TextMetrics> & { width: number }) {
  const canvases: { canvas: AtlasCanvas; calls: Call[] }[] = [];
  const factory = (width: number, height: number): AtlasCanvas => {
    const calls: Call[] = [];
    const ctx: AtlasContext = {
      font: '',
      fillStyle: '',
      textAlign: 'start',
      textBaseline: 'alphabetic',
      fillText: (text, x, y) => {
        calls.push(['fillText', text, x, y, ctx.fillStyle, ctx.font]);
      },
      measureText: () => metrics,
      drawImage: (image, dx, dy) => {
        calls.push(['drawImage', image, dx, dy]);
      },
    };
    const canvas: AtlasCanvas = { width, height, getContext: () => ctx };
    canvases.push({ canvas, calls });
    return canvas;
  };
  return { factory, canvases };
}

const METRICS = {
  width: 70,
  actualBoundingBoxLeft: -2,
  actualBoundingBoxRight: 66,
  actualBoundingBoxAscent: 69,
  actualBoundingBoxDescent: 1,
};

afterEach(() => clearGlyphAtlases());

describe('slot arithmetic', () => {
  it('lays slots out row-major', () => {
    expect(slotOrigin(0, 4, 10)).toEqual({ x: 0, y: 0 });
    expect(slotOrigin(5, 4, 10)).toEqual({ x: 10, y: 10 });
    expect(sheetRows(0, 4)).toBe(1);
    expect(sheetRows(9, 4)).toBe(3);
  });

  it('reads the ink box, with a cap-height fallback', () => {
    expect(inkBox(METRICS, 96)).toEqual({ left: -2, right: 66, ascent: 69, descent: 1 });
    expect(inkBox({ width: 50 }, 100)).toEqual({ left: 0, right: 50, ascent: 72, descent: 0 });
    expect(inkBox({ width: 0, actualBoundingBoxLeft: 0, actualBoundingBoxRight: 0 }, 100).right).toBe(60);
  });

  it('keys an atlas by font, ratio and scheme', () => {
    expect(atlasKey('Inter', 2, 'dark')).toBe('Inter|2.00|dark');
    expect(atlasKey('Inter', Number.NaN, 'light')).toBe('Inter|1.00|light');
    expect(atlasCellPx(1)).toBe(128);
    expect(atlasCellPx(3)).toBe(256);
  });
});

describe('GlyphAtlas', () => {
  it('rasterises each (letter, colour) once, ink box on the slot corner', () => {
    const { factory, canvases } = fakeCanvases(METRICS);
    const atlas = new GlyphAtlas({ fontFamily: 'Inter', cellPx: 96, columns: 4, createCanvas: factory });
    const a = atlas.slot('A', 'red');
    const again = atlas.slot('A', 'red');
    const other = atlas.slot('A', 'blue');
    expect(again).toBe(a);
    expect(atlas.size).toBe(2);
    expect(canvases).toHaveLength(1);
    const pad = (96 - 72) / 2;
    expect(a).toEqual({ sx: pad, sy: pad, sw: 64, sh: 70 });
    expect(other).toMatchObject({ sx: 96 + pad, sy: pad });
    const texts = canvases[0].calls.filter((c) => c[0] === 'fillText');
    expect(texts).toEqual([
      ['fillText', 'A', pad - 2, pad + 69, 'red', '700 72px Inter'],
      ['fillText', 'A', 96 + pad - 2, pad + 69, 'blue', '700 72px Inter'],
    ]);
  });

  it('doubles its rows when full and copies the old sheet across', () => {
    const { factory, canvases } = fakeCanvases(METRICS);
    const atlas = new GlyphAtlas({ fontFamily: 'Inter', cellPx: 10, columns: 2, createCanvas: factory });
    atlas.slot('A', 'c1');
    atlas.slot('B', 'c1');
    expect(canvases).toHaveLength(1);
    expect(canvases[0].canvas.height).toBe(10);
    const third = atlas.slot('C', 'c1');
    expect(canvases).toHaveLength(2);
    expect(canvases[1].canvas.height).toBe(20);
    expect(canvases[1].calls[0]).toEqual(['drawImage', canvases[0].canvas, 0, 0]);
    expect(third).toMatchObject({ sx: 0 + 1, sy: 10 + 1 });
    expect(atlas.sheet).toBe(canvases[1].canvas);
  });

  it('draws a slot stretched to the target box', () => {
    const { factory } = fakeCanvases(METRICS);
    const atlas = new GlyphAtlas({ fontFamily: 'Inter', cellPx: 96, createCanvas: factory });
    const calls: unknown[][] = [];
    const target = { drawImage: (...args: unknown[]) => calls.push(args) } as unknown as Pick<
      CanvasRenderingContext2D,
      'drawImage'
    >;
    expect(atlas.draw(target, 'W', 'green', 5, 6, 7, 8)).toBe(true);
    expect(calls[0].slice(1)).toEqual([12, 12, 64, 70, 5, 6, 7, 8]);
  });

  it('reports no slot without a canvas, once', () => {
    let made = 0;
    const atlas = new GlyphAtlas({
      fontFamily: 'Inter',
      createCanvas: () => {
        made += 1;
        return null;
      },
    });
    expect(atlas.slot('A', 'red')).toBeNull();
    expect(atlas.slot('B', 'red')).toBeNull();
    expect(atlas.draw({ drawImage: () => undefined } as never, 'A', 'red', 0, 0, 1, 1)).toBe(false);
    expect(made).toBe(1);
  });
});

describe('glyphAtlasFor', () => {
  it('shares one atlas per key and drops the oldest past four', () => {
    const make = () => new GlyphAtlas({ fontFamily: 'x', createCanvas: () => null });
    const first = glyphAtlasFor('k1', make);
    expect(glyphAtlasFor('k1', make)).toBe(first);
    for (const k of ['k2', 'k3', 'k4', 'k5']) glyphAtlasFor(k, make);
    expect(glyphAtlasFor('k1', make)).not.toBe(first);
  });
});
