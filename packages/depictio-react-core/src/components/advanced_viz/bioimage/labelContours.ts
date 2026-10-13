/** Outline of a label image, as RGBA pixels: one coloured line per label, on
 *  the label's own side of each boundary, transparent everywhere else.
 *
 *  A pixel is on an outline when its label is non-zero and a 4-neighbour holds
 *  another label (0 counts). Colours come from the label id: the golden angle
 *  spreads neighbouring ids apart, so adjacent nuclei read as distinct. */
export function labelContourRgba(
  labels: ArrayLike<number>,
  width: number,
  height: number,
): Uint8ClampedArray {
  const out = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = y * width + x;
      const v = labels[i];
      if (v === 0) continue;
      const edge =
        (x + 1 < width && labels[i + 1] !== v) ||
        (x > 0 && labels[i - 1] !== v) ||
        (y + 1 < height && labels[i + width] !== v) ||
        (y > 0 && labels[i - width] !== v);
      if (!edge) continue;
      const [r, g, b] = labelColour(v);
      out[i * 4] = r;
      out[i * 4 + 1] = g;
      out[i * 4 + 2] = b;
      out[i * 4 + 3] = 255;
    }
  }
  return out;
}

const GOLDEN_ANGLE_DEG = 137.508;

/** HSL to RGB at full saturation and mid lightness, for a hue in degrees. */
export function labelColour(label: number): [number, number, number] {
  const hue = (((Math.abs(Math.trunc(label)) * GOLDEN_ANGLE_DEG) % 360) + 360) % 360;
  const c = 0.8;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = 0.9 - c / 2;
  const sector = Math.floor(hue / 60);
  const [r1, g1, b1] =
    sector === 0
      ? [c, x, 0]
      : sector === 1
        ? [x, c, 0]
        : sector === 2
          ? [0, c, x]
          : sector === 3
            ? [0, x, c]
            : sector === 4
              ? [x, 0, c]
              : [c, 0, x];
  return [Math.round((r1 + m) * 255), Math.round((g1 + m) * 255), Math.round((b1 + m) * 255)];
}
