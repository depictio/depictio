import { describe, expect, it } from 'vitest';

import { pinnedPalette } from './palette';

describe('pinnedPalette', () => {
  const source = {
    inherited_category_colors: { locality: { Athens: '#111111', Naples: '#222222' } },
    category_colors: { locality: { Athens: '#333333' } },
  };

  it('layers main tab, dashboard, then the component, most specific last', () => {
    expect(pinnedPalette(source, { locality: { Naples: '#444444' } }, 'locality')).toEqual({
      Athens: '#333333',
      Naples: '#444444',
    });
  });

  it('takes the dashboard colours when the component pins none', () => {
    expect(pinnedPalette(source, null, 'locality')).toEqual({
      Athens: '#333333',
      Naples: '#222222',
    });
  });

  it('is null for a column nobody pins, or no column', () => {
    expect(pinnedPalette(source, { Kingdom: { Bacteria: '#555555' } }, 'Phylum')).toBeNull();
    expect(pinnedPalette(source, null, null)).toBeNull();
  });
});
