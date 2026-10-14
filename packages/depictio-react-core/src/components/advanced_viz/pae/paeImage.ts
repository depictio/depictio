/**
 * The PAE matrix as pixels: colour ramps, a 256-entry lookup table, block-mean
 * downsampling when the matrix has more residues than the plot has device
 * pixels, and the RGBA buffer the panel puts into an `ImageData` once per
 * (matrix, colour scale, maximum, theme, size) and then only blits.
 *
 * Pure (no DOM): unit-tested in `paeImage.test.ts`.
 */

import { COLORSCALE_NAMES, sampleColorscale } from '../../../utils/colorScale';
import type { ColourScale } from '../colourScales';
import { cssToRgb } from '../protein/panelTheme';
import type { RGB } from '../protein/residueColours';

export type { RGB };

/** The upper bound AlphaFold reports for its PAE head (Å), used when neither
 *  the config nor the file gives one. */
export const DEFAULT_MAX_PAE = 31.75;

/** Entries of a colour lookup table. */
export const LUT_SIZE = 256;

/** A colour as a function of t in [0, 1] (0 = no error). */
export type RampSampler = (t: number) => RGB;

/** `[t, colour]` stops, t ascending from 0 to 1. */
export type RampStops = ReadonlyArray<readonly [number, RGB]>;

/** Linear interpolation between stops (clamped to the ends). */
export function stopsSampler(stops: RampStops): RampSampler {
  return (t: number) => {
    const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
    if (stops.length === 0) return [128, 128, 128];
    if (x <= stops[0][0]) return [...stops[0][1]] as RGB;
    for (let k = 1; k < stops.length; k++) {
      const [t1, c1] = stops[k];
      if (x <= t1) {
        const [t0, c0] = stops[k - 1];
        const f = t1 === t0 ? 0 : (x - t0) / (t1 - t0);
        return [
          Math.round(c0[0] + f * (c1[0] - c0[0])),
          Math.round(c0[1] + f * (c1[1] - c0[1])),
          Math.round(c0[2] + f * (c1[2] - c0[2])),
        ];
      }
    }
    return [...stops[stops.length - 1][1]] as RGB;
  };
}

function evenStops(colours: readonly string[]): RampStops {
  const last = colours.length - 1;
  return colours.map((c, k) => [last > 0 ? k / last : 0, cssToRgb(c)] as const);
}

/**
 * Stops for the `ColourScale` names `utils/colorScale.ts` does not hold (it
 * keeps Viridis and Spectral; any other name falls back to Blues there). The
 * Plotly Express sequences for the matplotlib maps, and plotly.js's own RdBu
 * (blue to red), the one the Plotly-drawn tiles get for the same name.
 * Promote to `utils/colorScale.ts` `SCALES` so every canvas tile shares them.
 */
export const EXTRA_SCALE_STOPS: Readonly<Record<string, RampStops>> = {
  Plasma: evenStops([
    '#0d0887', '#46039f', '#7201a8', '#9c179e', '#bd3786',
    '#d8576b', '#ed7953', '#fb9f3a', '#fdca26', '#f0f921',
  ]),
  Inferno: evenStops([
    '#000004', '#1b0c41', '#4a0c6b', '#781c6d', '#a52c60',
    '#cf4446', '#ed6925', '#fb9b06', '#f7d13d', '#fcffa4',
  ]),
  Magma: evenStops([
    '#000004', '#180f3d', '#440f76', '#721f81', '#9e2f7f',
    '#cd4071', '#f1605d', '#fd9668', '#feca8d', '#fcfdbf',
  ]),
  Cividis: evenStops([
    '#00224e', '#123570', '#3b496c', '#575d6d', '#707173',
    '#8a8678', '#a59c74', '#c3b369', '#e1cc55', '#fee838',
  ]),
  RdBu: [
    [0, [5, 10, 172]],
    [0.35, [106, 137, 247]],
    [0.5, [190, 190, 190]],
    [0.6, [220, 170, 132]],
    [0.7, [230, 145, 90]],
    [1, [178, 10, 28]],
  ],
};

/** The sampler of a named colour scale: the shared `sampleColorscale` for the
 *  names it holds, the stops above for the others. Low error = scale start. */
export function colourScaleSampler(name: ColourScale): RampSampler {
  if (COLORSCALE_NAMES.includes(name)) return (t) => sampleColorscale(name, t);
  const stops = EXTRA_SCALE_STOPS[name];
  return stops ? stopsSampler(stops) : (t) => sampleColorscale('Viridis', t);
}

/**
 * The default ramp, AlphaFold DB's look taken from the theme: the theme's
 * green for a confident (low error) pair fading into the panel background for
 * an unknown placement. Light mode runs dark green to the (white) background;
 * dark mode reverses the lightness, light green to the (dark) background, so
 * the confident blocks are the ones that stand out in both.
 *
 * `greens` is a Mantine 10-shade colour tuple (light to dark).
 */
export function themeRampStops(
  greens: readonly string[],
  background: string,
  isDark: boolean,
): RampStops {
  const shade = (k: number) => cssToRgb(greens[Math.max(0, Math.min(greens.length - 1, k))]);
  const bg = cssToRgb(background);
  // Half way from the darkest shade to the background: the dark ramp's last
  // stretch stays as close to the panel as the light ramp's (shade 2 to white).
  const mix = (a: RGB, b: RGB, f: number): RGB => [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
  return isDark
    ? [
        [0, shade(2)],
        [0.2, shade(4)],
        [0.45, shade(7)],
        [0.7, mix(shade(9), bg, 0.5)],
        [1, bg],
      ]
    : [
        [0, shade(9)],
        [0.2, shade(7)],
        [0.45, shade(5)],
        [0.7, shade(2)],
        [1, bg],
      ];
}

/** `LUT_SIZE` RGB triplets sampled from a ramp, t = k / (LUT_SIZE - 1). */
export function buildLut(sample: RampSampler, size = LUT_SIZE): Uint8Array {
  const lut = new Uint8Array(size * 3);
  for (let k = 0; k < size; k++) {
    const [r, g, b] = sample(size > 1 ? k / (size - 1) : 0);
    lut[k * 3] = r;
    lut[k * 3 + 1] = g;
    lut[k * 3 + 2] = b;
  }
  return lut;
}

/** The lookup-table entry of an error: 0 Å is the first, `max` and above the last. */
export function lutIndex(value: number, max: number, size = LUT_SIZE): number {
  if (!(max > 0) || !(value > 0)) return 0;
  if (value >= max) return size - 1;
  return Math.round((value / max) * (size - 1));
}

/** The colour of one error on a lookup table. */
export function lutColour(lut: Uint8Array, value: number, max: number): RGB {
  const k = lutIndex(value, max, lut.length / 3) * 3;
  return [lut[k], lut[k + 1], lut[k + 2]];
}

/**
 * The colour scale's upper bound: the config's `max_pae` when set, else the
 * maximum the file declares, else the matrix's largest value, else 31.75.
 */
export function colourMax(
  configured: number | null | undefined,
  matrix: { max: number; declaredMax: number | null } | null,
): number {
  if (configured != null && Number.isFinite(configured) && configured > 0) return configured;
  if (matrix?.declaredMax != null && matrix.declaredMax > 0) return matrix.declaredMax;
  if (matrix && Number.isFinite(matrix.max) && matrix.max > 0) return matrix.max;
  return DEFAULT_MAX_PAE;
}

/**
 * An `n * n` matrix averaged down to `m * m` blocks (`m < n`): output cell
 * (r, c) is the mean of the finite source values in rows
 * [floor(r n / m), floor((r + 1) n / m)) and the same columns; NaN when the
 * block holds none. `m >= n` returns the matrix itself.
 */
export function downsampleBlockMean(values: Float32Array, n: number, m: number): Float32Array {
  if (m >= n) return values;
  const size = Math.max(1, Math.floor(m));
  const out = new Float32Array(size * size);
  const colOf = new Int32Array(n);
  for (let c = 0; c < size; c++) {
    const lo = Math.floor((c * n) / size);
    const hi = Math.floor(((c + 1) * n) / size);
    for (let s = lo; s < hi; s++) colOf[s] = c;
  }
  const sum = new Float64Array(size);
  const count = new Int32Array(size);
  for (let r = 0; r < size; r++) {
    sum.fill(0);
    count.fill(0);
    const lo = Math.floor((r * n) / size);
    const hi = Math.floor(((r + 1) * n) / size);
    for (let s = lo; s < hi; s++) {
      const base = s * n;
      for (let j = 0; j < n; j++) {
        const v = values[base + j];
        // Finite check without a call: NaN fails the first, Infinity the second.
        if (v === v && v - v === 0) {
          const c = colOf[j];
          sum[c] += v;
          count[c] += 1;
        }
      }
    }
    const row = r * size;
    for (let c = 0; c < size; c++) out[row + c] = count[c] ? sum[c] / count[c] : Number.NaN;
  }
  return out;
}

/** RGBA pixels of a `size * size` matrix: each error through the lookup
 *  table, a non-finite one in `missing`. Row 0 (aligned residue 1) on top. */
export function paePixels(
  values: Float32Array,
  size: number,
  lut: Uint8Array,
  max: number,
  missing: RGB,
): Uint8ClampedArray {
  const px = new Uint8ClampedArray(size * size * 4);
  const top = lut.length / 3 - 1;
  const scale = max > 0 ? top / max : 0;
  for (let k = 0; k < size * size; k++) {
    const v = values[k];
    const o = k * 4;
    if (!(v === v && v - v === 0)) {
      px[o] = missing[0];
      px[o + 1] = missing[1];
      px[o + 2] = missing[2];
    } else {
      const e = (v <= 0 ? 0 : v >= max ? top : Math.round(v * scale)) * 3;
      px[o] = lut[e];
      px[o + 1] = lut[e + 1];
      px[o + 2] = lut[e + 2];
    }
    px[o + 3] = 255;
  }
  return px;
}

/**
 * The image side for a plot of `targetPx` device pixels: the matrix itself
 * when it fits, else the target rounded up to a multiple of `quantum` (so a
 * resize does not re-render the image on every pixel), never above `n`.
 */
export function imageSide(n: number, targetPx: number, quantum = 64): number {
  if (!(targetPx > 0) || n <= targetPx) return n;
  return Math.min(n, Math.max(quantum, Math.ceil(targetPx / quantum) * quantum));
}

/** The matrix rendered for a plot of `targetPx` device pixels: pixels and side. */
export function renderPaeImage(
  matrix: { values: Float32Array; n: number },
  targetPx: number,
  lut: Uint8Array,
  max: number,
  missing: RGB,
): { pixels: Uint8ClampedArray; side: number } {
  const side = imageSide(matrix.n, targetPx);
  const values = downsampleBlockMean(matrix.values, matrix.n, side);
  return { pixels: paePixels(values, side, lut, max, missing), side };
}

/**
 * Mean of the finite errors over aligned rows `rows` and scored columns
 * `cols` (inclusive index ranges), or null when the block holds none: the
 * figure the tile echoes for a brushed block.
 */
export function blockMean(
  values: Float32Array,
  n: number,
  rows: readonly [number, number],
  cols: readonly [number, number],
): number | null {
  const r0 = Math.max(0, Math.min(rows[0], rows[1]));
  const r1 = Math.min(n - 1, Math.max(rows[0], rows[1]));
  const c0 = Math.max(0, Math.min(cols[0], cols[1]));
  const c1 = Math.min(n - 1, Math.max(cols[0], cols[1]));
  let sum = 0;
  let count = 0;
  for (let i = r0; i <= r1; i++) {
    const base = i * n;
    for (let j = c0; j <= c1; j++) {
      const v = values[base + j];
      if (v === v && v - v === 0) {
        sum += v;
        count += 1;
      }
    }
  }
  return count ? sum / count : null;
}
