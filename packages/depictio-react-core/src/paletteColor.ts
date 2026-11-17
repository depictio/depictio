/**
 * Palette colours as metadata writes them.
 *
 * A dashboard names a colour in several places (`icon_color`, a section's
 * `color`, `tab_icon_color`, a filter's `custom_color`). Every one accepts the
 * same spellings, resolved here once:
 *
 *   `blue`        a Mantine palette name, at the caller's default shade
 *   `blue.4`      the palette's shade 4 (Mantine's own syntax)
 *   `blue-4`      the same, with a dash (the CSS variable's spelling)
 *   `brandPrimary` the instance brand's palettes (registered as theme colours)
 *   `#12b886`, `rgb(...)`, `hsl(...)`, `var(...)`, `light-dark(...)`  literal CSS, passed through
 *
 * Shades run 0 to 9. A name with no valid shade keeps the default.
 */
import type { MantineTheme } from '@mantine/core';

/** Default shade for a palette name that gives none. */
export const DEFAULT_PALETTE_SHADE = 6;

const LITERAL_RE = /^(#|rgba?\(|hsla?\(|var\(|light-dark\(|color-mix\(|oklch\(|currentcolor$|transparent$)/i;
const SHADED_RE = /^([A-Za-z][A-Za-z0-9]*)[.-]([0-9])$/;
const NAME_RE = /^[A-Za-z][A-Za-z0-9]*$/;

export type ParsedPalette =
  | { kind: 'literal'; value: string }
  | { kind: 'palette'; name: string; shade: number | null };

/** Split a colour as authored: a literal CSS colour, or a palette name with an
 *  optional shade. Null for empty or unparseable input. */
export function parsePaletteColor(color: string | null | undefined): ParsedPalette | null {
  if (typeof color !== 'string') return null;
  const text = color.trim();
  if (!text) return null;
  if (LITERAL_RE.test(text)) return { kind: 'literal', value: text };
  const shaded = SHADED_RE.exec(text);
  if (shaded) return { kind: 'palette', name: shaded[1], shade: Number(shaded[2]) };
  if (NAME_RE.test(text)) return { kind: 'palette', name: text, shade: null };
  return null;
}

/** The palette name of a colour, shade dropped (`orange.4` gives `orange`).
 *  Null for a literal CSS colour. For code that keys on the hue, e.g. the
 *  theme's tuple or a name shared across a tab. */
export function paletteName(color: string | null | undefined): string | null {
  const parsed = parsePaletteColor(color);
  return parsed?.kind === 'palette' ? parsed.name : null;
}

/** The shade a colour names, or null when it names none. */
export function paletteShade(color: string | null | undefined): number | null {
  const parsed = parsePaletteColor(color);
  return parsed?.kind === 'palette' ? parsed.shade : null;
}

/**
 * A colour as a CSS value. `defaultShade` applies to a bare name; `'filled'`
 * asks for Mantine's filled token (which follows the colour scheme).
 *
 * "dark" and "black" are ink, not hues (a MultiQC tab is forced to dark): they
 * resolve to the text colour, whose shade 6 is near-black in both schemes.
 */
export function paletteVar(
  color: string | null | undefined,
  defaultShade: number | 'filled' = DEFAULT_PALETTE_SHADE,
): string | undefined {
  const parsed = parsePaletteColor(color);
  if (!parsed) return undefined;
  if (parsed.kind === 'literal') return parsed.value;
  const { name, shade } = parsed;
  if (shade === null && (name === 'dark' || name === 'black')) return 'var(--mantine-color-text)';
  if (name === 'white') return 'var(--mantine-color-white)';
  return `var(--mantine-color-${name}-${shade ?? defaultShade})`;
}

/**
 * A colour as a concrete value (the theme's hex for a palette name), for code
 * that needs the channels, e.g. to mix a tint or paint a canvas. A literal
 * passes through; an unknown palette name returns the input unchanged.
 */
export function paletteHex(
  theme: Pick<MantineTheme, 'colors'>,
  color: string | null | undefined,
  defaultShade: number = DEFAULT_PALETTE_SHADE,
): string | undefined {
  const parsed = parsePaletteColor(color);
  if (!parsed) return undefined;
  if (parsed.kind === 'literal') return parsed.value;
  const tuple = theme.colors[parsed.name];
  return tuple?.[parsed.shade ?? defaultShade] ?? parsed.name;
}
