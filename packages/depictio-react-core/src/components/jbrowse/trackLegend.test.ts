import { describe, expect, it } from 'vitest';

import type { JBrowseTrackRow } from '../../api';
import { foldByColour, legendRamp, trackLegend, variantLegend } from './trackLegend';

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

describe('foldByColour', () => {
  it('shares one entry between categories drawn alike', () => {
    const entries = foldByColour([
      { label: 'AD', color: '#1c7ed6' },
      { label: 'XR', color: '#0ca678' },
      { label: 'XD', color: '#0ca678' },
    ]);
    expect(entries.map((e) => e.label)).toEqual(['AD', 'XR, XD']);
    expect(entries[1].names).toEqual(['XR', 'XD']);
  });

  it('folds a long list into +N', () => {
    const entries = foldByColour(['a', 'b', 'c', 'd'].map((label) => ({ label, color: '#111' })));
    expect(entries).toHaveLength(1);
    expect(entries[0].label).toBe('a, b +2');
  });
});

describe('variantLegend', () => {
  const payload = {
    title: 'genetic_model',
    entries: [
      { label: 'AR_comp', color: '#7048e8' },
      { label: 'AD', color: '#1c7ed6' },
    ],
    fallback: { label: 'other', color: 'goldenrod' },
  };

  it('lists the categories then the fallback, under a readable title', () => {
    const key = variantLegend(payload);
    expect(key?.title).toBe('genetic model');
    expect(key?.entries.map((e) => [e.label, e.color])).toEqual([
      ['AR_comp', '#7048e8'],
      ['AD', '#1c7ed6'],
      ['other', 'goldenrod'],
    ]);
  });

  it('is null when the tile colours no variant', () => {
    expect(variantLegend(null)).toBeNull();
    expect(variantLegend({ ...payload, entries: [] })).toBeNull();
  });
});
