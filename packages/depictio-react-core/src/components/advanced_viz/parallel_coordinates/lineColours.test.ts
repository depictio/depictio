import { describe, expect, it } from 'vitest';

import {
  BLANK_CATEGORY,
  categoryIndices,
  distinctCategories,
  steppedColourScale,
  withAlpha,
} from './lineColours';

describe('distinctCategories', () => {
  it('sorts case-insensitively and names the blanks', () => {
    expect(distinctCategories(['treated', 'Control', null, '', 'treated'])).toEqual([
      BLANK_CATEGORY,
      'Control',
      'treated',
    ]);
  });
});

describe('categoryIndices', () => {
  it('maps every row onto a category position', () => {
    const values = ['b', 'a', null];
    const categories = distinctCategories(values);
    expect(categories).toEqual([BLANK_CATEGORY, 'a', 'b']);
    expect(categoryIndices(values, categories)).toEqual([2, 1, 0]);
  });

  it('falls back to the first category for a value outside the universe', () => {
    expect(categoryIndices(['z'], ['a', 'b'])).toEqual([0]);
  });
});

describe('steppedColourScale', () => {
  it('gives every category one flat step, centred on its index', () => {
    const scale = steppedColourScale(['#111111', '#222222']);
    expect(scale.colorscale).toEqual([
      [0, '#111111'],
      [0.5, '#111111'],
      [0.5, '#222222'],
      [1, '#222222'],
    ]);
    expect(scale.cmin).toBe(-0.5);
    expect(scale.cmax).toBe(1.5);
    // Category 1 normalises into the second step rather than onto its edge.
    const position = (1 - scale.cmin) / (scale.cmax - scale.cmin);
    expect(position).toBeGreaterThan(0.5);
    expect(position).toBeLessThan(1);
  });

  it('handles a single category and an empty palette', () => {
    expect(steppedColourScale(['#abcdef']).colorscale).toEqual([
      [0, '#abcdef'],
      [1, '#abcdef'],
    ]);
    expect(steppedColourScale([]).colorscale).toEqual([]);
  });
});

describe('withAlpha', () => {
  it('converts hex, short hex and rgb', () => {
    expect(withAlpha('#1f77b4', 0.5)).toBe('rgba(31, 119, 180, 0.5)');
    expect(withAlpha('#abc', 0.25)).toBe('rgba(170, 187, 204, 0.25)');
    expect(withAlpha('rgb(1, 2, 3)', 0.4)).toBe('rgba(1, 2, 3, 0.4)');
    expect(withAlpha('rgba(1, 2, 3, 0.9)', 0.4)).toBe('rgba(1, 2, 3, 0.4)');
  });

  it('leaves a colour it cannot parse, and an opaque request, untouched', () => {
    expect(withAlpha('var(--mantine-color-gray-6)', 0.5)).toBe('var(--mantine-color-gray-6)');
    expect(withAlpha('#1f77b4', 1)).toBe('#1f77b4');
    expect(withAlpha('', 0.5)).toBe('');
  });
});
