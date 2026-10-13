import { describe, expect, it } from 'vitest';

import { describeAggregation } from './describe';

describe('describeAggregation', () => {
  it('says how the number was computed', () => {
    expect(describeAggregation('median', 'shannon')).toBe('Median shannon');
    expect(describeAggregation('nunique', 'Phylum')).toBe('Number of distinct Phylum values');
    expect(describeAggregation('count', 'ID')).toBe('Number of rows');
  });

  it('falls back to the aggregation name for one it does not know', () => {
    expect(describeAggregation('box_plot_stats', 'x')).toBe('Box plot stats of x');
  });

  it('is null without an aggregation', () => {
    expect(describeAggregation(undefined, 'x')).toBeNull();
  });
});
