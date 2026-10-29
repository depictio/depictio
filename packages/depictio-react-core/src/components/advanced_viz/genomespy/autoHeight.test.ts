import { describe, expect, it } from 'vitest';

import {
  ANNOTATION_PX,
  AUTO_LANE_PX,
  AUTO_SINGLE_TRACK_PX,
  AXIS_PX,
  genomeContentPx,
  LANE_OVERHEAD_PX,
  tileFitPx,
} from './autoHeight';

describe('genomeContentPx', () => {
  it('gives an unfaceted tile one comfortable track and the axis', () => {
    expect(genomeContentPx({ lanes: 0 })).toBe(AUTO_SINGLE_TRACK_PX + AXIS_PX);
    expect(genomeContentPx({ lanes: 1 })).toBe(AUTO_SINGLE_TRACK_PX + AXIS_PX);
  });

  it('adds the gene lane when one is drawn', () => {
    expect(genomeContentPx({ lanes: 1, annotation: true })).toBe(
      AUTO_SINGLE_TRACK_PX + AXIS_PX + ANNOTATION_PX,
    );
  });

  it('grows with the lanes, each at the auto pitch plus its title and gap', () => {
    const three = genomeContentPx({ lanes: 3 });
    const four = genomeContentPx({ lanes: 4 });
    expect(four - three).toBe(AUTO_LANE_PX + LANE_OVERHEAD_PX);
    expect(three).toBe(3 * (AUTO_LANE_PX + LANE_OVERHEAD_PX) + AXIS_PX);
  });

  it('honours a fixed lane height', () => {
    const thin = genomeContentPx({ lanes: 12, laneHeight: 18 });
    expect(thin).toBe(12 * (18 + LANE_OVERHEAD_PX) + AXIS_PX);
    expect(thin).toBeLessThan(genomeContentPx({ lanes: 12 }));
  });

  it('counts a file-backed lane by its floor', () => {
    expect(genomeContentPx({ lanes: 2, fileLaneMinPx: 70 })).toBe(2 * 78 - 8 + AXIS_PX);
  });

  it('never depends on the tile, so the grid answering cannot ask for more', () => {
    expect(genomeContentPx({ lanes: 5, laneHeight: 40 })).toBe(genomeContentPx({ lanes: 5, laneHeight: 40 }));
  });
});

describe('tileFitPx', () => {
  it('adds what the tile spends around the box', () => {
    expect(tileFitPx(400, 90)).toBe(490);
    expect(tileFitPx(400.2, 90)).toBe(491);
  });

  it('is no demand until the chrome is measured, or without content', () => {
    expect(tileFitPx(400, null)).toBeNull();
    expect(tileFitPx(0, 90)).toBeNull();
    expect(tileFitPx(Number.NaN, 90)).toBeNull();
  });
});
