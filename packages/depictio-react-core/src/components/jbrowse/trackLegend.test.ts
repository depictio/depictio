import { describe, expect, it } from 'vitest';

import type { JBrowseTrackRow } from '../../api';
import { legendRamp, trackLegend } from './trackLegend';

const row = (track_id: string, over: Partial<JBrowseTrackRow> = {}): JBrowseTrackRow => ({
  track_id,
  name: track_id,
  format: 'bigwig',
  sample: null,
  selection_value: null,
  ...over,
});

describe('trackLegend', () => {
  const rows = [
    row('a1', { sample: 'A_R1', group: 'A', color: 'red' }),
    row('a2', { sample: 'A_R2', group: 'A', color: 'red' }),
    row('b1', { sample: 'B_R1', group: 'B', color: 'blue' }),
    row('genes', { source: 'annotation' }),
    row('s1', { sample: 'S1', color: 'teal' }),
    row('s2', { sample: 'S2', color: 'teal' }),
    row('s3', { sample: 'S3', color: 'teal' }),
  ];
  const colourOf = (r: JBrowseTrackRow) => r.color;

  it('has one entry per colour of the open tracks, in their order, by group', () => {
    expect(trackLegend(rows, ['b1', 'genes', 'a1', 'a2'], colourOf)).toEqual([
      { color: 'blue', label: 'B', names: ['B'] },
      { color: 'red', label: 'A', names: ['A'] },
    ]);
  });

  it('falls back on the samples and folds a long list', () => {
    expect(trackLegend(rows, ['s1', 's2', 's3'], colourOf)).toEqual([
      { color: 'teal', label: 'S1, S2 +1', names: ['S1', 'S2', 'S3'] },
    ]);
  });

  it('names the colours by track when one sample wears several', () => {
    const callers = [
      row('hc', { sample: 'NA12878', name: 'NA12878 haplotypecaller', color: 'blue' }),
      row('dv', { sample: 'NA12878', name: 'NA12878 deepvariant', color: 'orange' }),
    ];
    expect(trackLegend(callers, ['hc', 'dv'], colourOf).map((e) => e.label)).toEqual([
      'haplotypecaller',
      'deepvariant',
    ]);
  });

  it('is empty when no open track wears a colour', () => {
    expect(trackLegend(rows, ['genes', 'gone'], colourOf)).toEqual([]);
  });
});

describe('legendRamp', () => {
  const rows = [
    row('a', { group: 'early' }),
    row('b', { group: 'late' }),
    row('c', { group: 'mid' }),
    row('genes', { source: 'annotation' }),
  ];
  const scale = new Map([
    ['early', '#000001'],
    ['mid', '#000002'],
    ['late', '#000003'],
  ]);

  it('spans the extreme open values, in scale order', () => {
    const ramp = legendRamp(rows, ['b', 'genes', 'a', 'c'], scale, 'blues');
    expect(ramp).toMatchObject({ from: 'early', to: 'late', values: ['early', 'mid', 'late'] });
    expect(ramp?.stops).toHaveLength(7);
  });

  it('follows what is open, and is absent for a single value', () => {
    expect(legendRamp(rows, ['a', 'c'], scale, 'blues')).toMatchObject({ from: 'early', to: 'mid' });
    expect(legendRamp(rows, ['a'], scale, 'blues')).toBeNull();
    expect(legendRamp(rows, ['genes'], scale, 'blues')).toBeNull();
  });
});
