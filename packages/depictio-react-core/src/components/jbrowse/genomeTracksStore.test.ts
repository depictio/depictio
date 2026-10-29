import { beforeEach, describe, expect, it } from 'vitest';

import type { JBrowseSessionResponse } from '../../api';
import {
  getGenomeTracks,
  resetGenomeTracks,
  setGenomeTracksColours,
  setGenomeTracksLocus,
  setGenomeTracksPayload,
  trackGroupColours,
  trackSampleColours,
} from './genomeTracksStore';

const payload = { tracks_dc_id: 'dc' } as unknown as JBrowseSessionResponse;

describe('genomeTracksStore', () => {
  beforeEach(resetGenomeTracks);

  it('keeps the payload and the locus of a tile apart from another dashboard', () => {
    setGenomeTracksPayload('d1', 'jb', payload);
    setGenomeTracksLocus('d1', 'jb', 'chr1:1..2');
    setGenomeTracksLocus('d2', 'jb', 'chr9:1..2');
    expect(getGenomeTracks('jb', 'd1')).toMatchObject({ payload, locus: 'chr1:1..2' });
    expect(getGenomeTracks('jb', 'd2')).toMatchObject({ payload: null, locus: 'chr9:1..2' });
    expect(getGenomeTracks('jb', 'd3')).toBeNull();
  });

  it('reads the latest tile of an index when the dashboard is unknown', () => {
    setGenomeTracksLocus('d1', 'jb', 'chr1:1..2');
    setGenomeTracksLocus('d2', 'jb', 'chr9:1..2');
    expect(getGenomeTracks('jb')?.dashboardId).toBe('d2');
    expect(getGenomeTracks('other')).toBeNull();
  });

  it('does not replace an entry when nothing changed', () => {
    setGenomeTracksLocus('d1', 'jb', 'chr1:1..2');
    const before = getGenomeTracks('jb', 'd1');
    setGenomeTracksLocus('d1', 'jb', 'chr1:1..2');
    expect(getGenomeTracks('jb', 'd1')).toBe(before);
  });

  it('collects the sample colours of a dashboard, the first tile winning', () => {
    const rows = (pairs: Array<[string | null, string | null]>) =>
      ({
        track_rows: pairs.map(([sample, color], i) => ({ track_id: `t${i}`, sample, color })),
      }) as unknown as JBrowseSessionResponse;
    setGenomeTracksPayload('d1', 'a', rows([['S1', 'red'], ['S2', null], [null, 'blue']]));
    setGenomeTracksPayload('d1', 'b', rows([['S1', 'green'], ['S3', 'teal']]));
    setGenomeTracksPayload('d2', 'c', rows([['S9', 'pink']]));
    expect(trackSampleColours('d1')).toEqual({ S1: 'red', S3: 'teal' });
    expect(trackSampleColours('d3')).toEqual({});
    // No dashboard: the one written last.
    expect(trackSampleColours()).toEqual({ S9: 'pink' });
  });

  it('shares the colours a tile computed, under the manifest colour', () => {
    const rows = [
      { track_id: 't0', sample: 'S1', color: 'red' },
      { track_id: 't1', sample: 'S2', color: null },
    ];
    setGenomeTracksPayload('d1', 'a', { track_rows: rows } as unknown as JBrowseSessionResponse);
    setGenomeTracksColours('d1', 'a', {
      samples: { S1: 'blue', S2: 'green' },
      groups: { early: 'blue', late: 'green' },
    });
    expect(trackSampleColours('d1')).toEqual({ S1: 'red', S2: 'green' });
    expect(trackGroupColours('d1')).toEqual({ early: 'blue', late: 'green' });
    expect(trackGroupColours('d2')).toEqual({});
  });

  it('keeps the entry when the same colours are written again, and withdraws on null', () => {
    const colours = { samples: { S1: 'x' }, groups: { g: 'x' } };
    setGenomeTracksColours('d1', 'a', colours);
    const before = getGenomeTracks('a', 'd1');
    setGenomeTracksColours('d1', 'a', { samples: { S1: 'x' }, groups: { g: 'x' } });
    expect(getGenomeTracks('a', 'd1')).toBe(before);
    setGenomeTracksColours('d1', 'a', null);
    expect(trackGroupColours('d1')).toEqual({});
  });
});
