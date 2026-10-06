import { describe, expect, it } from 'vitest';

import {
  NEUTRAL_CATEGORY_COLOR,
  categoryColor,
  categoryColorMap,
  dashboardColorway,
  pinnedCategoryColor,
  sortCategoryValues,
  type CategoryColorSource,
} from './categoryColors';

const PALETTE = ['#111111', '#222222', '#333333'];

const dashboard: CategoryColorSource = {
  category_colors: { habitat: { Soil: '#f0a04b' } },
  inherited_category_colors: {
    habitat: { Soil: '#000000', Sediment: '#d6336c' },
    city: { Athens: '#1c7ed6' },
  },
};

describe('sortCategoryValues', () => {
  it('sorts naturally, case-insensitively, without duplicates or blanks', () => {
    expect(sortCategoryValues(['Sample_10', 'sample_2', 'Sample_1', '', null, 'Sample_1'])).toEqual([
      'Sample_1',
      'sample_2',
      'Sample_10',
    ]);
  });

  it('stringifies non-string values', () => {
    expect(sortCategoryValues([3, 1, true])).toEqual(['1', '3', 'true']);
  });
});

describe('pinnedCategoryColor', () => {
  it('prefers the tab’s own colour over the inherited one', () => {
    expect(pinnedCategoryColor(dashboard, 'habitat', 'Soil')).toBe('#f0a04b');
  });

  it('falls back to the main tab’s colour, per value', () => {
    expect(pinnedCategoryColor(dashboard, 'habitat', 'Sediment')).toBe('#d6336c');
    expect(pinnedCategoryColor(dashboard, 'city', 'Athens')).toBe('#1c7ed6');
  });

  it('is null for an unknown column, value or source', () => {
    expect(pinnedCategoryColor(dashboard, 'habitat', 'Groundwater')).toBeNull();
    expect(pinnedCategoryColor(dashboard, 'depth', 'Soil')).toBeNull();
    expect(pinnedCategoryColor(null, 'habitat', 'Soil')).toBeNull();
    expect(pinnedCategoryColor(dashboard, undefined, 'Soil')).toBeNull();
  });
});

describe('categoryColor', () => {
  it('uses a pinned colour whatever the index', () => {
    expect(categoryColor(dashboard, 'habitat', 'Soil', 7, PALETTE)).toBe('#f0a04b');
  });

  it('falls back to the palette by index, wrapping around', () => {
    expect(categoryColor(dashboard, 'habitat', 'Groundwater', 0, PALETTE)).toBe('#111111');
    expect(categoryColor(dashboard, 'habitat', 'Groundwater', 4, PALETTE)).toBe('#222222');
  });

  it('defaults the palette to the dashboard’s own colorway, own before inherited', () => {
    const branded: CategoryColorSource = {
      brand_theme: { plots: { colorway: ['#aa0000'] } },
      inherited_brand_theme: { plots: { colorway: ['#00aa00'] } },
    };
    expect(categoryColor(branded, 'x', 'v', 0)).toBe('#aa0000');
    expect(categoryColor({ inherited_brand_theme: branded.inherited_brand_theme }, 'x', 'v', 0)).toBe(
      '#00aa00',
    );
  });

  it('ends on the neutral grey without a palette', () => {
    expect(categoryColor({}, 'habitat', 'Groundwater', 0)).toBe(NEUTRAL_CATEGORY_COLOR);
    expect(categoryColor(dashboard, 'habitat', 'Groundwater', 0, null)).toBe(NEUTRAL_CATEGORY_COLOR);
    expect(categoryColor(dashboard, 'habitat', 'Groundwater', 0, [])).toBe(NEUTRAL_CATEGORY_COLOR);
    expect(categoryColor(dashboard, 'habitat', 'Groundwater', -1, PALETTE)).toBe(
      NEUTRAL_CATEGORY_COLOR,
    );
  });
});

describe('dashboardColorway', () => {
  it('is null when neither the tab nor its main tab states one', () => {
    expect(dashboardColorway({ brand_theme: { plots: { colorway: [] } } })).toBeNull();
    expect(dashboardColorway(null)).toBeNull();
  });
});

describe('categoryColorMap', () => {
  it('indexes the palette by the sorted universe, not by input order', () => {
    const map = categoryColorMap({}, 'habitat', ['Soil', 'Groundwater', 'Riverwater'], PALETTE);
    expect([...map.entries()]).toEqual([
      ['Groundwater', '#111111'],
      ['Riverwater', '#222222'],
      ['Soil', '#333333'],
    ]);
  });

  it('keeps every value’s colour when the visible subset changes', () => {
    // The universe is what the colours hang off: a filter narrowing the data
    // must not shift the remaining values onto other palette slots.
    const full = categoryColorMap({}, 'h', ['a', 'b', 'c'], PALETTE);
    const again = categoryColorMap({}, 'h', ['c', 'a', 'b', 'a'], PALETTE);
    expect(again).toEqual(full);
  });

  it('lets pinned colours win without shifting the others', () => {
    const map = categoryColorMap(dashboard, 'habitat', ['Groundwater', 'Sediment', 'Soil'], PALETTE);
    expect(map.get('Groundwater')).toBe('#111111');
    expect(map.get('Sediment')).toBe('#d6336c');
    expect(map.get('Soil')).toBe('#f0a04b');
  });
});
