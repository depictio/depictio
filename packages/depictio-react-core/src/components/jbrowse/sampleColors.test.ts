import { describe, expect, it } from 'vitest';

import type { JBrowseTrackRow } from '../../api';
import {
  colourAlignmentTracks,
  colourTracksBy,
  conditionColourMap,
  conditionOf,
  conditionSequentialMap,
  sampleColourColumn,
  sampleColourMap,
  trackColoursBy,
} from './sampleColors';
import { sequentialColor } from '../../categoryColors';

const row = (track_id: string, sample: string | null, selection_value = sample): JBrowseTrackRow => ({
  track_id,
  name: track_id,
  format: 'bam',
  sample,
  selection_value,
});

const rows = [row('a', 'S2'), row('b', 'S10'), row('c', 'S2'), row('v', 'S2'), row('n', null)];
const source = { category_colors: { sample: { S2: '#111111' } } };
const palette = ['#aa0000', '#00aa00', '#0000aa'];

describe('sampleColourColumn', () => {
  it('uses the selection column when it holds the sample', () => {
    expect(sampleColourColumn('sample_id', rows)).toBe('sample_id');
  });
  it('falls back to "sample" without a selection column or when it holds something else', () => {
    expect(sampleColourColumn(null, rows)).toBe('sample');
    expect(sampleColourColumn('mark', [row('a', 'S2', 'H3K27')])).toBe('sample');
  });
});

describe('sampleColourMap', () => {
  it('pins first, then walks the colorway in sorted order', () => {
    const map = sampleColourMap(source, 'sample', rows, palette);
    expect(map.get('S2')).toBe('#111111');
    // S2 < S10 numerically, so S10 is index 1 of the sorted universe.
    expect(map.get('S10')).toBe('#00aa00');
    expect(map.size).toBe(2);
  });
});

describe('colourAlignmentTracks', () => {
  const colours = sampleColourMap(source, 'sample', rows, palette);
  const tracks = [
    { type: 'AlignmentsTrack', trackId: 'a' },
    { type: 'AlignmentsTrack', trackId: 'b', displays: [{ type: 'LinearAlignmentsDisplay', displayId: 'b-d' }] },
    { type: 'VariantTrack', trackId: 'v' },
    { type: 'AlignmentsTrack', trackId: 'n' },
  ];

  it('sets the coverage renderer colour on an alignments track, creating the displays', () => {
    const [a] = colourAlignmentTracks(tracks, rows, colours);
    expect(a.displays).toEqual([
      {
        type: 'LinearAlignmentsDisplay',
        displayId: 'a-LinearAlignmentsDisplay',
        snpCoverageDisplay: {
          type: 'LinearSNPCoverageDisplay',
          displayId: 'a-LinearSNPCoverageDisplay',
          renderers: { SNPCoverageRenderer: { color: '#111111' } },
        },
      },
    ]);
  });

  it('keeps an existing display and its id', () => {
    const out = colourAlignmentTracks(tracks, rows, colours);
    expect(out[1].displays).toMatchObject([
      { displayId: 'b-d', snpCoverageDisplay: { renderers: { SNPCoverageRenderer: { color: '#00aa00' } } } },
    ]);
  });

  it('leaves variant tracks and sample-less tracks untouched, and does not mutate the input', () => {
    const out = colourAlignmentTracks(tracks, rows, colours);
    expect(out[2]).toBe(tracks[2]);
    expect(out[3]).toBe(tracks[3]);
    expect(tracks[0]).toEqual({ type: 'AlignmentsTrack', trackId: 'a' });
  });

  it('does not override a colour the track already carries', () => {
    const authored = {
      type: 'AlignmentsTrack',
      trackId: 'a',
      displays: [
        {
          type: 'LinearAlignmentsDisplay',
          snpCoverageDisplay: { renderers: { SNPCoverageRenderer: { color: 'tomato' } } },
        },
      ],
    };
    const [out] = colourAlignmentTracks([authored], rows, colours);
    expect(out).toBe(authored);
  });
});

describe('colour by condition', () => {
  const meta = (condition: string | null) => ({ metadata: condition === null ? {} : { condition } });
  const confs: Array<Record<string, unknown> & { trackId: string }> = [
    { type: 'QuantitativeTrack', trackId: 'w1', ...meta('treated') },
    { type: 'QuantitativeTrack', trackId: 'w2', ...meta('control') },
    { type: 'AlignmentsTrack', trackId: 'b1', ...meta('treated') },
    { type: 'VariantTrack', trackId: 'v1', ...meta('treated') },
    { type: 'QuantitativeTrack', trackId: 'w3', ...meta(null) },
  ];
  const src = { category_colors: { condition: { treated: '#ff0000' } } };
  const colours = conditionColourMap(src, 'condition', confs, ['#0000ff', '#00ff00']);

  it('reads the value from the manifest row on the track config', () => {
    expect(conditionOf(confs[0], 'condition')).toBe('treated');
    expect(conditionOf(confs[4], 'condition')).toBeNull();
    expect(conditionOf({ trackId: 'x' }, 'condition')).toBeNull();
  });

  it('pins first, then walks the colorway over the sorted conditions', () => {
    expect(colours.get('treated')).toBe('#ff0000');
    // control sorts before treated: index 0 of the colorway.
    expect(colours.get('control')).toBe('#0000ff');
  });

  it('colours signal tracks on their plot renderers and alignments on their coverage', () => {
    const out = colourTracksBy(confs, 'condition', colours);
    expect((out[0].displays as unknown[])).toEqual([
      {
        type: 'LinearWiggleDisplay',
        displayId: 'w1-LinearWiggleDisplay',
        renderers: {
          XYPlotRenderer: { color: '#ff0000' },
          LinePlotRenderer: { color: '#ff0000' },
          DensityRenderer: { color: '#ff0000' },
        },
      },
    ]);
    expect((out[1].displays as unknown[])[0]).toMatchObject({ renderers: { XYPlotRenderer: { color: '#0000ff' } } });
    expect(out[2].displays).toMatchObject([
      { snpCoverageDisplay: { renderers: { SNPCoverageRenderer: { color: '#ff0000' } } } },
    ]);
  });

  it('leaves other kinds, tracks with no value and authored colours alone', () => {
    const authored = {
      type: 'QuantitativeTrack',
      trackId: 'w9',
      ...meta('treated'),
      displays: [{ type: 'LinearWiggleDisplay', renderers: { XYPlotRenderer: { color: 'tomato' } } }],
    };
    const out = colourTracksBy([...confs, authored], 'condition', colours);
    expect(out[3]).toBe(confs[3]);
    expect(out[4]).toBe(confs[4]);
    expect(out[5]).toBe(authored);
  });

  it('then lets the per-sample colour fill only what is still bare', () => {
    const byCondition = colourTracksBy(confs, 'condition', colours);
    const sampleRows = [
      { track_id: 'b1', name: 'b1', format: 'bam', sample: 'S1', selection_value: 'S1' },
    ];
    const out = colourAlignmentTracks(byCondition, sampleRows, new Map([['S1', '#123456']]));
    expect(out[2]).toBe(byCondition[2]);
  });
});

describe('color_scale over the tracks', () => {
  const sig = (trackId: string, timepoint: string, day: number, type = 'QuantitativeTrack') => ({
    type,
    trackId,
    metadata: { timepoint, day },
  });
  const tracks = [sig('a', 'late', 14), sig('b', 'early', 0), sig('c', 'mid', 3), sig('d', 'early', 0)];

  it('orders the values by order_by and spreads them over the ramp', () => {
    const map = conditionSequentialMap({ column: 'timepoint', order_by: 'day', scheme: 'blues' }, tracks);
    expect([...map.keys()]).toEqual(['early', 'mid', 'late']);
    expect(map.get('early')).toBe(sequentialColor('blues', 0));
    expect(map.get('mid')).toBe(sequentialColor('blues', 0.5));
    expect(map.get('late')).toBe(sequentialColor('blues', 1));
  });

  it('falls back to the natural order of the values without order_by', () => {
    const map = conditionSequentialMap({ column: 'timepoint' }, tracks);
    expect([...map.keys()]).toEqual(['early', 'late', 'mid']);
  });

  it('paints the signal tracks through colourTracksBy like a categorical map', () => {
    const map = conditionSequentialMap({ column: 'timepoint', order_by: 'day', scheme: 'blues' }, tracks);
    const [late] = colourTracksBy(tracks, 'timepoint', map);
    const renderers = ((late as any).displays as any[])[0].renderers;
    expect(renderers.XYPlotRenderer.color).toBe(sequentialColor('blues', 1));
  });

  it('reports the group and sample colours to share, skipping a manifest colour', () => {
    const map = conditionSequentialMap({ column: 'timepoint', order_by: 'day' }, tracks);
    const trackRows: JBrowseTrackRow[] = [
      { ...row('a', 'S1'), color: null },
      { ...row('b', 'S2'), color: '#123456' },
      row('c', 'S3'),
    ];
    const shared = trackColoursBy(tracks, trackRows, 'timepoint', map);
    expect(Object.keys(shared.groups).sort()).toEqual(['early', 'late', 'mid']);
    expect(shared.samples).toEqual({
      S1: map.get('late'),
      S3: map.get('mid'),
    });
  });
});
