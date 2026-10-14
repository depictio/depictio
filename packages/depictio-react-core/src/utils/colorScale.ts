/**
 * Colour-scale sampling + WCAG-contrast text colour.
 *
 * Plotly does not export a way to sample a named colourscale at a value, so we
 * keep light→dark RGB stops for the scales we use and interpolate linearly.
 * `contrastingText` then picks black/white by the cell's *actual* luminance —
 * the standard accessible technique, not a normalised-value threshold guess.
 */

export type RGB = [number, number, number];

// Light (t=0) → dark (t=1) stops. Approximate stops are fine: they only feed
// the luminance estimate that chooses black vs white label text.
const SCALES: Record<string, Array<[number, RGB]>> = {
  Blues: [
    [0.0, [247, 251, 255]],
    [0.25, [198, 219, 239]],
    [0.5, [107, 174, 214]],
    [0.75, [33, 113, 181]],
    [1.0, [8, 48, 107]],
  ],
  Greens: [
    [0.0, [247, 252, 245]],
    [0.5, [116, 196, 118]],
    [1.0, [0, 68, 27]],
  ],
  YlOrRd: [
    [0.0, [255, 255, 204]],
    [0.25, [255, 237, 160]],
    [0.5, [254, 178, 76]],
    [0.75, [240, 59, 32]],
    [1.0, [189, 0, 38]],
  ],
  Viridis: [
    [0.0, [68, 1, 84]],
    [0.25, [59, 82, 139]],
    [0.5, [33, 145, 140]],
    [0.75, [94, 201, 98]],
    [1.0, [253, 231, 37]],
  ],
  Tealgrn: [
    [0.0, [176, 242, 188]],
    [0.5, [56, 177, 148]],
    [1.0, [11, 84, 99]],
  ],
  Sunsetdark: [
    [0.0, [252, 222, 156]],
    [0.5, [227, 109, 99]],
    [1.0, [122, 4, 102]],
  ],
  // Diverging, used by the embedding renderer for continuous colour. Not a
  // plotly.js builtin despite the familiar name, so it must be emitted as
  // stops or the trace renders with no colour mapping at all.
  Spectral: [
    [0.0, [158, 1, 66]],
    [0.25, [244, 109, 67]],
    [0.5, [255, 255, 191]],
    [0.75, [102, 194, 165]],
    [1.0, [94, 79, 162]],
  ],
  // The rest of the advanced-viz `ColourScale` names (colourScales.ts): without
  // them `sampleColorscale` fell back to Blues for every one of these, so a
  // canvas tile set to Plasma or RdBu drew Blues. matplotlib's ten even stops.
  Plasma: [
    [0.0, [13, 8, 135]],
    [0.1111, [70, 3, 159]],
    [0.2222, [114, 1, 168]],
    [0.3333, [156, 23, 158]],
    [0.4444, [189, 55, 134]],
    [0.5556, [216, 87, 107]],
    [0.6667, [237, 121, 83]],
    [0.7778, [251, 159, 58]],
    [0.8889, [253, 202, 38]],
    [1.0, [240, 249, 33]],
  ],
  Inferno: [
    [0.0, [0, 0, 4]],
    [0.1111, [27, 12, 65]],
    [0.2222, [74, 12, 107]],
    [0.3333, [120, 28, 109]],
    [0.4444, [165, 44, 96]],
    [0.5556, [207, 68, 70]],
    [0.6667, [237, 105, 37]],
    [0.7778, [251, 155, 6]],
    [0.8889, [247, 209, 61]],
    [1.0, [252, 255, 164]],
  ],
  Magma: [
    [0.0, [0, 0, 4]],
    [0.1111, [24, 15, 61]],
    [0.2222, [68, 15, 118]],
    [0.3333, [114, 31, 129]],
    [0.4444, [158, 47, 127]],
    [0.5556, [205, 64, 113]],
    [0.6667, [241, 96, 93]],
    [0.7778, [253, 150, 104]],
    [0.8889, [254, 202, 141]],
    [1.0, [252, 253, 191]],
  ],
  Cividis: [
    [0.0, [0, 34, 78]],
    [0.1111, [18, 53, 112]],
    [0.2222, [59, 73, 108]],
    [0.3333, [87, 93, 109]],
    [0.4444, [112, 113, 115]],
    [0.5556, [138, 134, 120]],
    [0.6667, [165, 156, 116]],
    [0.7778, [195, 179, 105]],
    [0.8889, [225, 204, 85]],
    [1.0, [254, 232, 56]],
  ],
  // Plotly's RdBu orientation: blue at the low end, red at the high end.
  RdBu: [
    [0.0, [5, 10, 172]],
    [0.35, [106, 137, 247]],
    [0.5, [190, 190, 190]],
    [0.6, [220, 170, 132]],
    [0.7, [230, 145, 90]],
    [1.0, [178, 10, 28]],
  ],
};

/** Named scales available to viz colour-scale selectors. */
export const COLORSCALE_NAMES = Object.keys(SCALES);

/** Plotly.js `colorscale` value for a name — explicit [[t,'rgb(...)'],…] stops
 *  for the scales we define (some, e.g. Tealgrn/Sunsetdark, are Plotly-Express
 *  names that plotly.js doesn't know by string), else the bare name for
 *  plotly.js builtins. Guarantees the trace renders the intended ramp. */
export function plotlyColorscale(name: string): string | Array<[number, string]> {
  const stops = SCALES[name];
  if (!stops) return name;
  return stops.map(([t, [r, g, b]]) => [t, `rgb(${r},${g},${b})`]);
}

/** Sample a named colourscale at t∈[0,1] → RGB. Falls back to Blues. */
export function sampleColorscale(name: string, t: number): RGB {
  const stops = SCALES[name] ?? SCALES.Blues;
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  for (let i = 1; i < stops.length; i++) {
    const [t1, c1] = stops[i];
    if (x <= t1) {
      const [t0, c0] = stops[i - 1];
      const f = t1 === t0 ? 0 : (x - t0) / (t1 - t0);
      return [
        Math.round(c0[0] + f * (c1[0] - c0[0])),
        Math.round(c0[1] + f * (c1[1] - c0[1])),
        Math.round(c0[2] + f * (c1[2] - c0[2])),
      ];
    }
  }
  return stops[stops.length - 1][1];
}

function srgbToLinear(c: number): number {
  const cs = c / 255;
  return cs <= 0.03928 ? cs / 12.92 : Math.pow((cs + 0.055) / 1.055, 2.4);
}

/** WCAG relative luminance (0 = black, 1 = white). */
export function relativeLuminance([r, g, b]: RGB): number {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

/** Black or white text — whichever has the higher WCAG contrast with `rgb`.
 *  Crossover luminance ≈ 0.179, so brighter cells get dark text. */
export function contrastingText(rgb: RGB): '#1a1a1a' | '#ffffff' {
  return relativeLuminance(rgb) > 0.179 ? '#1a1a1a' : '#ffffff';
}

/** Convenience: contrasting text for a value t on a named scale. */
export function contrastingTextForValue(name: string, t: number): '#1a1a1a' | '#ffffff' {
  return contrastingText(sampleColorscale(name, t));
}
