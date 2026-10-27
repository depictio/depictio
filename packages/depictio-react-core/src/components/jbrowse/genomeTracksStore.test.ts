import { beforeEach, describe, expect, it } from 'vitest';

import type { JBrowseSessionResponse } from '../../api';
import {
  getGenomeTracks,
  resetGenomeTracks,
  setGenomeTracksLocus,
  setGenomeTracksPayload,
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
});
