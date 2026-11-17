import { describe, expect, it } from 'vitest';

import { alignmentTrackIds, initTrackEntry, pairsDisplaySnapshot } from './readPairs';

describe('pairsDisplaySnapshot', () => {
  it('names the lower panel for arcs and cloud', () => {
    expect(pairsDisplaySnapshot('arcs')).toEqual({ lowerPanelType: 'LinearReadArcsDisplay' });
    expect(pairsDisplaySnapshot('cloud')).toEqual({ lowerPanelType: 'LinearReadCloudDisplay' });
  });
  it('passes nothing for the pileup, nothing set or an unknown value', () => {
    expect(pairsDisplaySnapshot('pileup')).toEqual({});
    expect(pairsDisplaySnapshot(undefined)).toEqual({});
    expect(pairsDisplaySnapshot('wat')).toEqual({});
  });
});

describe('alignmentTrackIds / initTrackEntry', () => {
  const alignments = alignmentTrackIds([
    { trackId: 'b', type: 'AlignmentsTrack' },
    { trackId: 'w', type: 'QuantitativeTrack' },
    { trackId: 'x' },
  ]);
  it('keeps only alignment tracks', () => {
    expect([...alignments]).toEqual(['b']);
  });
  it('gives an alignment track its display snapshot, others the bare id', () => {
    expect(initTrackEntry('b', alignments, 'arcs')).toEqual({
      trackId: 'b',
      displaySnapshot: { lowerPanelType: 'LinearReadArcsDisplay' },
    });
    expect(initTrackEntry('w', alignments, 'arcs')).toBe('w');
    expect(initTrackEntry('b', alignments, 'pileup')).toBe('b');
  });
});
