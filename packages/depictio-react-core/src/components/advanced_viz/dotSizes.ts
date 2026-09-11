/**
 * Marker diameters for a dot plot's size channel.
 *
 * Kept out of the renderer because the two corrections it makes are the kind
 * that flatten a chart rather than break it, so they need a test that states
 * the numbers rather than a reviewer noticing a missing square root.
 */

/**
 * Diameters in pixels for `values`, mapped onto the marker's AREA.
 *
 * Two things the obvious `min + v * (max - min)` gets wrong:
 *
 * The domain is the data's own maximum, not `[0, 1]`. A unit domain only fits
 * the single-cell reading of `frac_expressing`, where 1.0 means every cell. Any
 * other share lives in a sliver of it: on the atacseq read-distribution matrix
 * `fraction_of_reads` runs 0.010 to 0.097, so a tile configured for 3-26 px drew
 * everything between 3.2 and 5.2 px and never came near the maximum it asked
 * for. Normalising costs nothing where the unit domain was already right,
 * because data that does reach 1.0 normalises to itself.
 *
 * And the value goes on the area, hence the square root: Plotly's `marker.size`
 * is a diameter, while quantity in a bubble is read as area, so a linear map
 * shows a doubled value as four times the ink. Same reasoning as
 * ScatterXyRenderer's `sizeref` and EnrichmentRenderer's count scaling.
 *
 * Zero stays meaningful: it maps to `minSize`, so an absent cell is a dot at the
 * floor rather than a hole, and negatives (which the size channel cannot show)
 * are clamped to it.
 */
export function dotSizes(values: unknown[], minSize: number, maxSize: number): number[] {
  const peak = dotSizePeak(values);
  const span = Math.max(0, maxSize - minSize);
  if (peak <= 0) return values.map(() => minSize);
  return values.map((v) => {
    const n = Math.max(0, Number(v) || 0);
    return minSize + Math.sqrt(n / peak) * span;
  });
}

/** The largest usable value in `values`, the number the scale is anchored to. */
export function dotSizePeak(values: unknown[]): number {
  let peak = 0;
  for (const v of values) {
    const n = Number(v) || 0;
    if (n > peak) peak = n;
  }
  return peak;
}

export interface DotSizeKeyEntry {
  /** Data value this circle stands for. */
  value: number;
  /** Diameter in pixels, from `dotSizes`, so the key cannot drift from the plot. */
  diameter: number;
}

/**
 * Reference circles for a size key, largest first.
 *
 * The scale is anchored to the data's own peak, which is what makes it readable
 * at all (see `dotSizes`) but also what makes a key necessary: without one, a
 * big dot only says "the largest here", and two tiles side by side invite a
 * comparison their sizes do not support. So the key states the numbers.
 *
 * Steps go down by quarters from the peak rather than by halves, because the
 * scale is on the area: quartering the value halves the diameter, which is the
 * spacing that actually looks even in a row of circles.
 */
export function dotSizeKey(
  values: unknown[],
  minSize: number,
  maxSize: number,
  steps = 3,
): DotSizeKeyEntry[] {
  const peak = dotSizePeak(values);
  if (peak <= 0 || steps < 1) return [];
  const refs: number[] = [];
  for (let i = 0; i < steps; i += 1) refs.push(peak / 4 ** i);
  const diameters = dotSizes(refs, minSize, maxSize);
  return refs.map((value, i) => ({ value, diameter: diameters[i] }));
}
