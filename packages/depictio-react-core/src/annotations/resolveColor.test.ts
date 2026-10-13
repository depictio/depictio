import { createTheme, DEFAULT_THEME, mergeMantineTheme } from '@mantine/core';
import { describe, expect, it } from 'vitest';

import {
  annotationColorTint,
  annotationColorValue,
  annotationPaletteVars,
  makeColorResolver,
} from './resolveColor';
import { withAlpha } from './toPlotly';
import { ANNOTATION_COLORS } from './types';

describe('annotation colours', () => {
  it('uses shade 6 in light mode and 4 in dark mode, clamping explicit shades', () => {
    expect(annotationColorValue('teal', 'light')).toBe(DEFAULT_THEME.colors.teal[6]);
    expect(annotationColorValue('teal', 'dark')).toBe(DEFAULT_THEME.colors.teal[4]);
    expect(annotationColorValue('gray', 'light', 8)).toBe(DEFAULT_THEME.colors.gray[8]);
    expect(annotationColorValue('gray', 'light', 42)).toBe(DEFAULT_THEME.colors.gray[9]);
  });

  it('ignores a brand theme that remaps the palette', () => {
    // A dashboard brand theme can point teal at a data series colour.
    const brandTeal = Array(10).fill('#a034f0') as unknown as (typeof DEFAULT_THEME.colors)['teal'];
    const brand = mergeMantineTheme(DEFAULT_THEME, createTheme({ colors: { teal: brandTeal } }));
    expect(brand.colors.teal[6]).toBe('#a034f0');
    const resolve = makeColorResolver('light');
    expect(resolve('teal')).toBe(DEFAULT_THEME.colors.teal[6]);
    expect(resolve('teal')).not.toBe(brand.colors.teal[6]);
  });

  it('tints backgrounds with an alpha matching the scheme', () => {
    expect(annotationColorTint('blue', 'light')).toBe(withAlpha(DEFAULT_THEME.colors.blue[6], 0.1));
    expect(annotationColorTint('blue', 'dark', true)).toBe(withAlpha(DEFAULT_THEME.colors.blue[4], 0.2));
  });

  it('exposes three custom properties per palette name for the table CSS', () => {
    const vars = annotationPaletteVars('light');
    expect(Object.keys(vars)).toHaveLength(ANNOTATION_COLORS.length * 3);
    expect(vars['--depictio-annot-orange-stripe']).toBe(DEFAULT_THEME.colors.orange[6]);
    expect(vars['--depictio-annot-orange-bg']).toBe(annotationColorTint('orange', 'light'));
    expect(vars['--depictio-annot-orange-bg-strong']).toBe(annotationColorTint('orange', 'light', true));
  });
});
