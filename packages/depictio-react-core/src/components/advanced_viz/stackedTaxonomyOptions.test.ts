import { describe, expect, it } from 'vitest';

import {
  taxonomyAxisTitle,
  taxonomyLegend,
  visibleTaxonomyControls,
} from './stackedTaxonomyOptions';

describe('visibleTaxonomyControls', () => {
  it('offers every control when nothing is hidden, as the taxonomy tile always did', () => {
    const all = { rank: true, sample_sort: true, top_n: true, normalise: true };
    expect(visibleTaxonomyControls(undefined)).toEqual(all);
    expect(visibleTaxonomyControls(null)).toEqual(all);
    expect(visibleTaxonomyControls([])).toEqual(all);
  });

  it('drops only the controls the config hides', () => {
    expect(visibleTaxonomyControls(['rank', 'top_n', 'sample_sort'])).toEqual({
      rank: false,
      sample_sort: false,
      top_n: false,
      normalise: true,
    });
  });
});

describe('taxonomyAxisTitle', () => {
  it('falls back to the sample column when unset', () => {
    expect(taxonomyAxisTitle(undefined, 'sample_id')).toBe('sample_id');
    expect(taxonomyAxisTitle(null, 'sample_id')).toBe('sample_id');
  });

  it('uses the configured title, and none for an empty string', () => {
    expect(taxonomyAxisTitle('Library', 'library')).toBe('Library');
    expect(taxonomyAxisTitle('', 'library')).toBeUndefined();
  });
});

describe('taxonomyLegend', () => {
  it('keeps the horizontal legend under the bars by default', () => {
    expect(taxonomyLegend(undefined)).toEqual({ orientation: 'h', y: -0.25 });
    expect(taxonomyLegend('bottom')).toEqual({ orientation: 'h', y: -0.25 });
  });

  it('puts a vertical legend beside the bars on request', () => {
    expect(taxonomyLegend('right')).toMatchObject({ orientation: 'v', x: 1.02, xanchor: 'left' });
  });
});
