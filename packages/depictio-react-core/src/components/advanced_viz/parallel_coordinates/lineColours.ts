/**
 * Colouring a bundle of polylines.
 *
 * Plotly's `parcoords` colours its lines through one numeric array and one
 * colour scale, which is the right shape for a measurement and the wrong one
 * for a category. A categorical column therefore becomes an index per row
 * plus a stepped scale, one flat step per category, so the shared palette
 * still decides the hues and a legend built elsewhere still agrees with them.
 *
 * The alpha lives here too: `parcoords` has no line opacity of its own, so an
 * overplotted bundle can only be thinned by putting the alpha in the colour.
 */

/** The label a blank category reads as, so a row with no group is still a row
 *  with a colour rather than a line that vanishes. */
export const BLANK_CATEGORY = '(blank)';

const categoryLabel = (value: unknown): string =>
  value === null || value === undefined || value === '' ? BLANK_CATEGORY : String(value);

/** Distinct category labels, in the stable order the palette is keyed by. */
export function distinctCategories(values: readonly unknown[]): string[] {
  const seen = new Set<string>();
  for (const value of values) seen.add(categoryLabel(value));
  return Array.from(seen).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}

/** Each row's position in `categories`, which is what plotly colours by. */
export function categoryIndices(
  values: readonly unknown[],
  categories: readonly string[],
): number[] {
  const position = new Map(categories.map((category, i) => [category, i]));
  return values.map((value) => position.get(categoryLabel(value)) ?? 0);
}

export interface SteppedColourScale {
  /** `[position, colour]` stops, two per category, so each step is flat. */
  colorscale: [number, string][];
  cmin: number;
  cmax: number;
}

/**
 * A stepped scale over `colours`, one flat step each.
 *
 * `cmin`/`cmax` are offset by half a step so category `i` lands in the middle
 * of step `i` rather than on the boundary between two of them, which is where
 * a rounding difference would flip a line's colour.
 */
export function steppedColourScale(colours: readonly string[]): SteppedColourScale {
  const count = colours.length;
  if (count === 0) return { colorscale: [], cmin: 0, cmax: 1 };
  const colorscale: [number, string][] = [];
  colours.forEach((colour, i) => {
    colorscale.push([i / count, colour]);
    colorscale.push([(i + 1) / count, colour]);
  });
  return { colorscale, cmin: -0.5, cmax: count - 0.5 };
}

/**
 * A colour with an alpha applied, for the formats a theme hands out.
 *
 * Mantine's scales and the brand colorway are hex; a caller that has already
 * been through here (or through a plotly theme helper) passes rgb/rgba. A
 * named or `var()` colour cannot be given an alpha without a DOM to resolve it
 * through, so it comes back opaque rather than dropped.
 */
export function withAlpha(colour: string, alpha: number): string {
  const bounded = Math.max(0, Math.min(1, alpha));
  if (!colour) return colour;
  if (bounded >= 1) return colour;
  const trimmed = colour.trim();

  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(trimmed);
  if (hex) {
    const digits =
      hex[1].length === 3
        ? hex[1]
            .split('')
            .map((d) => d + d)
            .join('')
        : hex[1];
    const r = parseInt(digits.slice(0, 2), 16);
    const g = parseInt(digits.slice(2, 4), 16);
    const b = parseInt(digits.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${bounded})`;
  }

  const rgb = /^rgba?\(([^)]+)\)$/i.exec(trimmed);
  if (rgb) {
    const parts = rgb[1].split(',').map((part) => part.trim());
    if (parts.length >= 3) return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${bounded})`;
  }

  return colour;
}
