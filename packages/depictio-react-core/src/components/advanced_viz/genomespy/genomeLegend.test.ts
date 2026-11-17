import { describe, expect, it } from 'vitest';

import type { GenomeTracksColourKey } from '../../jbrowse/genomeTracksStore';
import { browserKeyLegend } from './genomeLegend';

const ramp: GenomeTracksColourKey = {
  column: 'time_point',
  values: ['0h', '1h', '4h'],
  ordered: true,
  scheme: 'viridis',
  sampleGroups: { A: '0h', B: '0h', C: '1h', D: '4h' },
};
const colours = { '0h': '#440154', '1h': '#21918c', '4h': '#fde725' };

describe('browserKeyLegend', () => {
  it('is a ramp over the values the drawn libraries carry, in colour order', () => {
    const legend = browserKeyLegend(ramp, ['A', 'B', 'C', 'D'], colours);
    expect(legend?.title).toBe('time point');
    expect(legend?.entries).toEqual([]);
    expect(legend?.ramp).toMatchObject({ from: '0h', to: '4h', values: ['0h', '1h', '4h'] });
    expect(legend?.ramp?.stops).toHaveLength(7);
    expect(browserKeyLegend(ramp, ['A', 'C'], colours)?.ramp?.values).toEqual(['0h', '1h']);
  });

  it('is swatches, one hue per value, for an unordered column', () => {
    const legend = browserKeyLegend({ ...ramp, ordered: false }, ['A', 'C', 'D'], colours);
    expect(legend?.ramp).toBeNull();
    expect(legend?.entries.map((e) => [e.label, e.color])).toEqual([
      ['0h', '#440154'],
      ['1h', '#21918c'],
      ['4h', '#fde725'],
    ]);
  });

  it('has none for a single value, an unknown sample or no key', () => {
    expect(browserKeyLegend(ramp, ['A', 'B'], colours)).toBeNull();
    expect(browserKeyLegend(ramp, ['Z'], colours)).toBeNull();
    expect(browserKeyLegend(null, ['A', 'C'], colours)).toBeNull();
  });
});
