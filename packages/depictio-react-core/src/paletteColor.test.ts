import { describe, expect, it } from 'vitest';

import { hexWithAlpha } from './components/card/metrics/format';
import { glyphColorVar } from './components/Glyph';
import { resolveColor } from './components/interactive/frame';
import { sourceColorVar } from './components/jbrowse/navigatorSteps';
import {
  paletteHex,
  paletteName,
  paletteShade,
  paletteVar,
  parsePaletteColor,
} from './paletteColor';

const theme = {
  colors: {
    orange: ['#0', '#1', '#2', '#3', '#4', '#5', '#6', '#7', '#8', '#9'],
  },
} as never;

describe('paletteVar', () => {
  it('keeps a bare name on the default shade', () => {
    expect(paletteVar('blue')).toBe('var(--mantine-color-blue-6)');
    expect(paletteVar('blue', 4)).toBe('var(--mantine-color-blue-4)');
    expect(paletteVar('blue', 'filled')).toBe('var(--mantine-color-blue-filled)');
  });

  it('reads a shade in the dotted and the dashed spelling', () => {
    expect(paletteVar('orange.4')).toBe('var(--mantine-color-orange-4)');
    expect(paletteVar('orange-8')).toBe('var(--mantine-color-orange-8)');
    // A shade named in the metadata beats the caller's default
    expect(paletteVar('orange.9', 'filled')).toBe('var(--mantine-color-orange-9)');
  });

  it('resolves the brand palettes like any other name', () => {
    expect(paletteVar('brandPrimary')).toBe('var(--mantine-color-brandPrimary-6)');
    expect(paletteVar('brandSecondary.4')).toBe('var(--mantine-color-brandSecondary-4)');
  });

  it('passes literal CSS colours through', () => {
    expect(paletteVar('#12b886')).toBe('#12b886');
    expect(paletteVar('rgb(1, 2, 3)')).toBe('rgb(1, 2, 3)');
    expect(paletteVar('var(--x)')).toBe('var(--x)');
  });

  it('treats dark and black as ink', () => {
    expect(paletteVar('dark')).toBe('var(--mantine-color-text)');
    expect(paletteVar('black')).toBe('var(--mantine-color-text)');
  });

  it('returns undefined for nothing or nonsense', () => {
    expect(paletteVar(undefined)).toBeUndefined();
    expect(paletteVar('')).toBeUndefined();
    expect(paletteVar('not a colour')).toBeUndefined();
  });
});

describe('parsePaletteColor', () => {
  it('splits name and shade', () => {
    expect(parsePaletteColor('teal.5')).toEqual({ kind: 'palette', name: 'teal', shade: 5 });
    expect(paletteName('teal-5')).toBe('teal');
    expect(paletteShade('teal-5')).toBe(5);
    expect(paletteShade('teal')).toBeNull();
    expect(paletteName('#fff')).toBeNull();
  });
});

describe('paletteHex', () => {
  it('reads the theme tuple at the named shade', () => {
    expect(paletteHex(theme, 'orange')).toBe('#6');
    expect(paletteHex(theme, 'orange.4')).toBe('#4');
    expect(paletteHex(theme, 'orange-9')).toBe('#9');
    expect(paletteHex(theme, '#abc')).toBe('#abc');
    expect(paletteHex(theme, undefined)).toBeUndefined();
  });
});

describe('every site that resolves a metadata colour takes shades', () => {
  it('glyphColorVar', () => {
    expect(glyphColorVar('orange.4')).toBe('var(--mantine-color-orange-4)');
    expect(glyphColorVar('violet')).toBe('var(--mantine-color-violet-6)');
    expect(glyphColorVar(null)).toBe('var(--mantine-color-dimmed)');
    expect(glyphColorVar('dark')).toBe('var(--mantine-color-text)');
  });
  it('resolveColor (filters)', () => {
    expect(resolveColor('teal.8')).toBe('var(--mantine-color-teal-8)');
    expect(resolveColor('#fff')).toBe('#fff');
  });
  it('sourceColorVar (jbrowse)', () => {
    expect(sourceColorVar('grape-4')).toBe('var(--mantine-color-grape-4)');
    expect(sourceColorVar(' ')).toBeNull();
  });
  it('hexWithAlpha mixes the shade the card named', () => {
    expect(hexWithAlpha('orange', 0.2)).toBe(
      'color-mix(in srgb, var(--mantine-color-orange-filled) 20%, transparent)',
    );
    expect(hexWithAlpha('orange.8', 0.2)).toBe(
      'color-mix(in srgb, var(--mantine-color-orange-8) 20%, transparent)',
    );
    expect(hexWithAlpha('#FF7F00', 0.5)).toBe('rgba(255,127,0,0.5)');
  });
});
