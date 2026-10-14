import { describe, expect, it } from 'vitest';

import {
  DENSE_AXIS_BARS,
  isDenseTaxonomyAxis,
  taxonomyAxisTitle,
  taxonomyLegend,
  taxonomyLegendTopPx,
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
  it('reads "Sample" when unset, as the tile always did', () => {
    expect(taxonomyAxisTitle(undefined)).toBe('Sample');
    expect(taxonomyAxisTitle(null)).toBe('Sample');
  });

  it('uses the configured title, and none for an empty string', () => {
    expect(taxonomyAxisTitle('Library')).toBe('Library');
    expect(taxonomyAxisTitle('')).toBeUndefined();
  });
});

describe('dense axis', () => {
  it('starts past 40 bars', () => {
    expect(DENSE_AXIS_BARS).toBe(40);
    expect(isDenseTaxonomyAxis(40)).toBe(false);
    expect(isDenseTaxonomyAxis(41)).toBe(true);
  });
});

describe('taxonomyLegend', () => {
  it('keeps the titled column right of the bars by default, dense or not', () => {
    for (const pos of [undefined, null, 'right'] as const) {
      expect(taxonomyLegend(pos, false, 'Phylum')).toEqual({
        orientation: 'v',
        x: 1.02,
        xanchor: 'left',
        y: 1,
        yanchor: 'top',
        title: { text: 'Phylum ' },
        font: { size: 10 },
      });
    }
    expect(taxonomyLegend('right', true, 'Phylum')).toMatchObject({ orientation: 'v', x: 1.02 });
    expect(taxonomyLegendTopPx('right', true, true)).toBe(0);
  });

  it('draws rows under the whole figure on request', () => {
    expect(taxonomyLegend('bottom', false, 'Level')).toMatchObject({
      orientation: 'h',
      y: 0,
      yref: 'container',
      yanchor: 'bottom',
      title: { text: 'Level ' },
    });
    expect(taxonomyLegendTopPx('bottom', false, true)).toBe(0);
  });

  it('lifts a bottom legend above the bars once the sample labels are hidden', () => {
    expect(taxonomyLegend('bottom', true, 'Level')).toMatchObject({
      orientation: 'h',
      y: 1.02,
      yanchor: 'bottom',
    });
    expect(taxonomyLegendTopPx('bottom', true, true)).toBe(40);
    // No legend shown, no room kept for it.
    expect(taxonomyLegendTopPx('bottom', true, false)).toBe(0);
  });
});
