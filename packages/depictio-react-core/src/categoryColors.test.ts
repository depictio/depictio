import { describe, expect, it } from 'vitest';

import {
  NEUTRAL_CATEGORY_COLOR,
  categoryColor,
  categoryColorMap,
  chipCategoryDots,
  columnCategoryColors,
  dashboardColorway,
  hasPinnedColors,
  pinnedCategoryColor,
  pinnedCategoryDots,
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

describe('the auto key', () => {
  // `{"*": "auto"}` is resolved at import; a stray one must not read as a value.
  const stray: CategoryColorSource = {
    category_colors: { condition: { '*': 'auto', control: '#868e96' }, batch: { '*': 'auto' } },
  };

  it('is never a value’s colour', () => {
    expect(pinnedCategoryColor(stray, 'condition', '*')).toBeNull();
    expect(pinnedCategoryColor(stray, 'condition', 'control')).toBe('#868e96');
  });

  it('does not make a column count as pinned', () => {
    expect(hasPinnedColors(stray, 'batch')).toBe(false);
    expect(hasPinnedColors(stray, 'condition')).toBe(true);
    expect(pinnedCategoryDots(stray, 'batch', ['b1', 'b2'])).toBeNull();
  });
});

describe('columnCategoryColors', () => {
  it('layers the main tab, the tab, then the component, most specific last', () => {
    expect(columnCategoryColors(dashboard, 'habitat', { Sediment: '#123456' })).toEqual({
      Soil: '#f0a04b',
      Sediment: '#123456',
    });
    expect(columnCategoryColors(dashboard, 'city')).toEqual({ Athens: '#1c7ed6' });
  });

  it('drops the auto key and empty colours', () => {
    const source: CategoryColorSource = {
      category_colors: { condition: { '*': 'auto', control: '#868e96', treated: '' } },
    };
    expect(columnCategoryColors(source, 'condition', { '*': 'auto' })).toEqual({ control: '#868e96' });
  });

  it('is null when nothing names a value, and only the component’s without a column', () => {
    expect(columnCategoryColors(dashboard, 'depth')).toBeNull();
    expect(columnCategoryColors(null, 'habitat')).toBeNull();
    expect(columnCategoryColors(dashboard, null, { a: '#000000' })).toEqual({ a: '#000000' });
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

describe('pinnedCategoryDots (filter chips)', () => {
  // The TREC shape: colours for the city, none for the size class or season.
  const trec: CategoryColorSource = {
    category_colors: {
      locality: { Athens: '#1a4f8f', Barcelona: '#f5a11b', Naples: '#00a550' },
    },
    brand_theme: { plots: { colorway: ['#aa0000', '#00aa00'] } },
  };

  it('dots a column the dashboard gives colours to, in those colours', () => {
    const dots = pinnedCategoryDots(trec, 'locality', ['Naples', 'Athens', 'Barcelona']);
    expect(dots && [...dots.entries()]).toEqual([
      ['Athens', '#1a4f8f'],
      ['Barcelona', '#f5a11b'],
      ['Naples', '#00a550'],
    ]);
  });

  it('gives no dot at all to any other column, whatever the brand palette', () => {
    expect(pinnedCategoryDots(trec, 'size_class', ['Large', 'Medium', 'Small'])).toBeNull();
    expect(pinnedCategoryDots(trec, 'season', ['Spring', 'Summer'])).toBeNull();
    expect(pinnedCategoryDots(null, 'locality', ['Athens'])).toBeNull();
    expect(pinnedCategoryDots(trec, undefined, ['Athens'])).toBeNull();
  });

  it('greys a value the author did not list, so the row keeps its dots', () => {
    const dots = pinnedCategoryDots(trec, 'locality', ['Athens', 'Marseille']);
    expect(dots?.get('Athens')).toBe('#1a4f8f');
    expect(dots?.get('Marseille')).toBe(NEUTRAL_CATEGORY_COLOR);
  });

  it('reads the main tab’s colours on a child tab', () => {
    const child: CategoryColorSource = { inherited_category_colors: trec.category_colors };
    expect(hasPinnedColors(child, 'locality')).toBe(true);
    expect(pinnedCategoryDots(child, 'locality', ['Naples'])?.get('Naples')).toBe('#00a550');
  });

  it('treats an empty entry as no colours', () => {
    expect(hasPinnedColors({ category_colors: { season: {} } }, 'season')).toBe(false);
  });
});

describe('chipCategoryDots (filter bar chips)', () => {
  const trec: CategoryColorSource = {
    category_colors: {
      locality: { Athens: '#1a4f8f', Barcelona: '#f5a11b', Naples: '#00a550' },
    },
  };
  const colorway = ['#aa0000', '#00aa00', '#0000aa', '#aaaa00'];

  it('takes the dashboard’s colours where it gives the column some', () => {
    const dots = chipCategoryDots(trec, 'locality', ['Naples', 'Athens'], colorway, 9);
    expect(dots?.get('Athens')).toBe('#1a4f8f');
    expect(dots?.get('Naples')).toBe('#00a550');
  });

  it('colours a short column without any from the colorway, by sorted position', () => {
    const dots = chipCategoryDots(trec, 'size_class', ['Small', 'Large', 'Medium'], colorway, 9);
    expect(dots && [...dots.entries()]).toEqual([
      ['Large', '#aa0000'],
      ['Medium', '#00aa00'],
      ['Small', '#0000aa'],
    ]);
  });

  it('gives no dots where two values would share a hue, or past the limit', () => {
    const five = ['a', 'b', 'c', 'd', 'e'];
    expect(chipCategoryDots(trec, 'site', five, colorway, 9)).toBeNull();
    expect(chipCategoryDots(trec, 'site', ['a', 'b', 'c'], colorway, 2)).toBeNull();
  });

  it('gives none without a colorway, a column, or with the fallback turned off', () => {
    expect(chipCategoryDots(trec, 'season', ['Spring', 'Summer'], null, 9)).toBeNull();
    expect(chipCategoryDots(trec, undefined, ['Spring'], colorway, 9)).toBeNull();
    expect(chipCategoryDots(trec, 'season', ['Spring', 'Summer'], colorway, 0)).toBeNull();
  });
});
