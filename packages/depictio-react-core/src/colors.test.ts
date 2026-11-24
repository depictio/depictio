import { describe, expect, it } from 'vitest';

import {
  TAB10_PALETTE,
  brandColorway,
  defaultCategorical,
  mantineCategoricalPalette,
  resolveCategoricalPalette,
  stableColorMap,
} from './colors';
import { categoricalPalette, semanticColor } from './palettes';

const BRAND = ['#111111', '#222222'];
const brandTheme = (dark?: string[]) => ({
  other: { brand: { plots: { colorway: BRAND, colorway_dark: dark ?? null } } },
});

describe('default categorical palette', () => {
  it('is the shared palette, per scheme', () => {
    expect(defaultCategorical(false)).toEqual(categoricalPalette(null, 'light'));
    expect(defaultCategorical(true)).toEqual(categoricalPalette(null, 'dark'));
    expect(mantineCategoricalPalette(undefined, true)).toEqual(categoricalPalette(null, 'dark'));
    expect(TAB10_PALETTE).toEqual(categoricalPalette(null, 'light'));
  });
});

describe('resolveCategoricalPalette', () => {
  it('prefers the brand colorway, the dark one in dark mode', () => {
    expect(resolveCategoricalPalette(brandTheme(), TAB10_PALETTE, false)).toEqual(BRAND);
    expect(brandColorway(brandTheme(['#333333']), true)).toEqual(['#333333']);
    expect(resolveCategoricalPalette(brandTheme(['#333333']), TAB10_PALETTE, true)).toEqual(['#333333']);
  });

  it('falls back to the shared palette of the scheme, not a fixed one', () => {
    expect(resolveCategoricalPalette(null, TAB10_PALETTE, true)).toEqual(categoricalPalette(null, 'dark'));
    expect(resolveCategoricalPalette(null, undefined, false)).toEqual(categoricalPalette(null, 'light'));
  });

  it('keeps a renderer palette that is genuinely its own', () => {
    const own = ['#abcdef', '#fedcba'];
    expect(resolveCategoricalPalette(null, own, true)).toBe(own);
  });
});

describe('stableColorMap', () => {
  it('ranks values over the shared palette, case-insensitively, whatever is filtered', () => {
    const palette = categoricalPalette(null, 'light');
    const map = stableColorMap(['beta', 'Alpha', 'gamma']);
    expect(map.universe).toEqual(['Alpha', 'beta', 'gamma']);
    expect(['Alpha', 'beta', 'gamma'].map((v) => map.get(v))).toEqual([palette[0], palette[1], palette[2]]);
  });

  it('gives reserved remainder values their semantic grey, not a palette slot', () => {
    const palette = categoricalPalette(null, 'dark');
    const map = stableColorMap(['Other', 'b', 'a', 'Unclassified', 'NA'], null, null, 'dark');
    expect(map.get('Other')).toBe(semanticColor('other', 'dark'));
    expect(map.get('Unclassified')).toBe(semanticColor('unclassified', 'dark'));
    expect(map.get('NA')).toBe(semanticColor('na', 'dark'));
    expect([map.get('a'), map.get('b')]).toEqual([palette[0], palette[1]]);
  });

  it('lets a pin win and skips its slot', () => {
    const palette = categoricalPalette(null, 'light');
    const map = stableColorMap(['a', 'b', 'c'], null, { a: palette[0] });
    expect(map.get('a')).toBe(palette[0]);
    expect(map.get('b')).toBe(palette[1]);
    expect(map.get('c')).toBe(palette[2]);
  });

  it('honours an explicit palette, and hashes unknown values onto it', () => {
    const own = ['#aa0000', '#00aa00', '#0000aa'];
    const map = stableColorMap(['x', 'y'], own);
    expect(own).toContain(map.get('never-seen'));
    expect(map.get('never-seen')).toBe(map.get('never-seen'));
    expect(map.get('other')).toBe(semanticColor('other', 'light'));
  });
});
