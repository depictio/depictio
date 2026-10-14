import { describe, expect, it } from 'vitest';

import {
  blockMean,
  buildLut,
  colourMax,
  colourScaleSampler,
  DEFAULT_MAX_PAE,
  downsampleBlockMean,
  imageSide,
  LUT_SIZE,
  lutColour,
  lutIndex,
  paePixels,
  renderPaeImage,
  stopsSampler,
  themeRampStops,
  type RGB,
} from './paeImage';
import { COLOUR_SCALES } from '../colourScales';
import { sampleColorscale } from '../../../utils/colorScale';

const BLACK: RGB = [0, 0, 0];
const WHITE: RGB = [255, 255, 255];
const greyLut = buildLut(stopsSampler([
  [0, BLACK],
  [1, WHITE],
]));

describe('downsampleBlockMean', () => {
  it('returns the matrix itself when it fits', () => {
    const v = new Float32Array([1, 2, 3, 4]);
    expect(downsampleBlockMean(v, 2, 2)).toBe(v);
    expect(downsampleBlockMean(v, 2, 5)).toBe(v);
  });

  it('averages exact blocks', () => {
    // 4 x 4 into 2 x 2: each output cell is the mean of a 2 x 2 block.
    const v = new Float32Array([
      1, 3, 10, 10,
      5, 7, 10, 30,
      0, 0, 2, 2,
      0, 4, 2, 2,
    ]);
    expect(Array.from(downsampleBlockMean(v, 4, 2))).toEqual([4, 15, 1, 2]);
  });

  it('covers every source cell once with uneven blocks', () => {
    const n = 5;
    const v = new Float32Array(n * n).fill(2);
    const out = downsampleBlockMean(v, n, 2);
    expect(Array.from(out)).toEqual([2, 2, 2, 2]);
    // Rows [0, 2) and [2, 5): the second block holds three rows.
    const ramp = new Float32Array(n * n);
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) ramp[i * n + j] = i;
    const r = downsampleBlockMean(ramp, n, 2);
    expect(r[0]).toBeCloseTo(0.5);
    expect(r[2]).toBeCloseTo(3);
  });

  it('skips non-finite values and leaves an all-missing block NaN', () => {
    const v = new Float32Array([NaN, 4, NaN, NaN]);
    const out = downsampleBlockMean(v, 2, 1);
    expect(out[0]).toBe(4);
    const empty = downsampleBlockMean(new Float32Array([NaN, NaN, NaN, NaN]), 2, 1);
    expect(Number.isNaN(empty[0])).toBe(true);
  });
});

describe('colour mapping', () => {
  it('maps 0 Å to the first entry and max (or above) to the last', () => {
    expect(lutIndex(0, 30)).toBe(0);
    expect(lutIndex(-1, 30)).toBe(0);
    expect(lutIndex(30, 30)).toBe(LUT_SIZE - 1);
    expect(lutIndex(45, 30)).toBe(LUT_SIZE - 1);
    expect(lutIndex(15, 30)).toBe(Math.round(0.5 * (LUT_SIZE - 1)));
    expect(lutColour(greyLut, 0, 30)).toEqual(BLACK);
    expect(lutColour(greyLut, 30, 30)).toEqual(WHITE);
  });

  it('writes opaque RGBA, missing values in the missing colour', () => {
    const missing: RGB = [1, 2, 3];
    const px = paePixels(new Float32Array([0, 31.75, NaN, 100]), 2, greyLut, 31.75, missing);
    expect(Array.from(px.slice(0, 4))).toEqual([0, 0, 0, 255]);
    expect(Array.from(px.slice(4, 8))).toEqual([255, 255, 255, 255]);
    expect(Array.from(px.slice(8, 12))).toEqual([1, 2, 3, 255]);
    expect(Array.from(px.slice(12, 16))).toEqual([255, 255, 255, 255]);
  });

  it('renders a downsampled image when the plot has fewer pixels than residues', () => {
    const n = 200;
    const values = new Float32Array(n * n).fill(10);
    const { side, pixels } = renderPaeImage({ values, n }, 100, greyLut, 20, BLACK);
    expect(side).toBe(128);
    expect(pixels.length).toBe(side * side * 4);
    const mid = Math.round(0.5 * (LUT_SIZE - 1));
    expect(pixels[0]).toBe(greyLut[mid * 3]);
    // A small matrix keeps one pixel per residue.
    expect(renderPaeImage({ values: new Float32Array(9), n: 3 }, 300, greyLut, 20, BLACK).side).toBe(3);
  });

  it('chooses image sides in steps, never above the matrix', () => {
    expect(imageSide(100, 400)).toBe(100);
    expect(imageSide(1000, 300)).toBe(320);
    expect(imageSide(1000, 330)).toBe(384);
    expect(imageSide(350, 330)).toBe(350);
  });

  it('runs the theme ramp from the dark green to the background in light mode', () => {
    const greens = ['#000000', '#111111', '#222222', '#333333', '#444444', '#555555', '#666666', '#777777', '#888888', '#0a5f1e'];
    const light = buildLut(stopsSampler(themeRampStops(greens, '#ffffff', false)));
    expect(lutColour(light, 0, 30)).toEqual([10, 95, 30]);
    expect(lutColour(light, 30, 30)).toEqual(WHITE);
    // Dark mode reverses the lightness: a light shade fades into the dark panel.
    const dark = buildLut(stopsSampler(themeRampStops(greens, '#1a1b1e', true)));
    expect(lutColour(dark, 0, 30)).toEqual([0x22, 0x22, 0x22]);
    expect(lutColour(dark, 30, 30)).toEqual([0x1a, 0x1b, 0x1e]);
  });

  it('samples every ColourScale name, none falling back to Blues', () => {
    const blues = sampleColorscale('Blues', 0);
    for (const name of COLOUR_SCALES) {
      const lut = buildLut(colourScaleSampler(name));
      expect(lut.length).toBe(LUT_SIZE * 3);
      expect(lutColour(lut, 0, 1)).not.toEqual(blues);
    }
    // Shared scales come from the shared helper.
    expect(colourScaleSampler('Viridis')(0)).toEqual(sampleColorscale('Viridis', 0));
    expect(colourScaleSampler('Plasma')(0)).toEqual([13, 8, 135]);
    expect(colourScaleSampler('Plasma')(1)).toEqual([240, 249, 33]);
    expect(colourScaleSampler('RdBu')(0)).toEqual([5, 10, 172]);
  });
});

describe('colourMax', () => {
  const m = (max: number, declaredMax: number | null) => ({ max, declaredMax });
  it('prefers the config, then the declared maximum, then the matrix, then 31.75', () => {
    expect(colourMax(20, m(12, 31.75))).toBe(20);
    expect(colourMax(null, m(12, 31.75))).toBe(31.75);
    expect(colourMax(undefined, m(12, null))).toBe(12);
    expect(colourMax(null, m(0, null))).toBe(DEFAULT_MAX_PAE);
    expect(colourMax(null, null)).toBe(DEFAULT_MAX_PAE);
    expect(colourMax(0, m(12, null))).toBe(12);
  });
});

describe('blockMean', () => {
  const n = 3;
  const v = new Float32Array([0, 1.5, 4.25, 2, 0, 10.5, 3.75, 12, NaN]);
  it('averages rows x columns, inclusive, skipping missing values', () => {
    expect(blockMean(v, n, [0, 0], [0, 2])).toBeCloseTo((0 + 1.5 + 4.25) / 3);
    expect(blockMean(v, n, [1, 2], [1, 2])).toBeCloseTo((0 + 10.5 + 12) / 3);
    expect(blockMean(v, n, [2, 1], [0, 0])).toBeCloseTo((2 + 3.75) / 2);
  });
  it('is null for a block of missing values only', () => {
    expect(blockMean(v, n, [2, 2], [2, 2])).toBeNull();
  });
});
