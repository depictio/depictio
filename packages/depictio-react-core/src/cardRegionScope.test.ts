import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from './api';
import { cardScopedFilters } from './selection';

const sample: InteractiveFilter = { index: 'f', value: ['S1'], column_name: 'sample' };
const region: InteractiveFilter[] = [
  { index: 'nav', value: ['chr2'], source: 'genome_selection', column_name: 'chrom' },
  { index: 'nav::pos', value: [1, 2], source: 'genome_selection', column_name: 'start' },
];

describe('cardScopedFilters (mirrors region_scope.py)', () => {
  it('drops the region for a card that does not follow it', () => {
    expect(cardScopedFilters([sample, ...region], { follow_region_filter: false })).toEqual([sample]);
    // A card on a region-only tab reports no active filter.
    expect(cardScopedFilters(region, {})).toHaveLength(0);
  });

  it('keeps the region for a card that opts in', () => {
    const filters = [sample, ...region];
    expect(cardScopedFilters(filters, { follow_region_filter: true })).toBe(filters);
  });
});
