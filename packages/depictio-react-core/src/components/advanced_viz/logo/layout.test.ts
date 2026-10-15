import { describe, expect, it } from 'vitest';

import {
  HIT_BAR_PX,
  HIT_GAP_PX,
  HIT_ROW_PX,
  hitBarTop,
  hitRowAt,
  HITS_MAX_SHARE,
  HITS_NATURAL_ROWS,
  insertLengthShare,
  LANE_PX,
  laneAt,
  layoutLanes,
  LOGO_MIN_PX,
  LOGO_MIN_SHARE,
  logoAxis,
  rampColour,
  type LaneFlags,
} from './layout';
import { COLLAPSED_TRACK_PX } from './tracks';

const NONE: LaneFlags = {
  consensus: false,
  rf: false,
  cs: false,
  insertProb: false,
  insertLength: false,
  occupancy: false,
  hits: false,
  hitRows: 0,
};

describe('layoutLanes', () => {
  it('gives the logo everything but the ruler when nothing else is on', () => {
    const l = layoutLanes(300, NONE);
    expect(l.lanes.map((x) => x.key)).toEqual(['logo', 'ruler']);
    expect(l.byKey.logo).toEqual({ key: 'logo', y: 0, h: 300 - LANE_PX.ruler });
    expect(l.byKey.ruler?.y).toBe(300 - LANE_PX.ruler);
  });

  it('stacks the lanes in the documented order', () => {
    const all = { consensus: true, rf: true, cs: true, insertProb: true, insertLength: true, occupancy: true };
    const l = layoutLanes(400, { ...NONE, ...all, hits: true, hitRows: 3 });
    expect(l.lanes.map((x) => x.key)).toEqual([
      'logo',
      'consensus',
      'rf',
      'cs',
      'insertProb',
      'insertLength',
      'occupancy',
      'coverage',
      'hits',
      'ruler',
    ]);
    // Contiguous, and filling the panel.
    l.lanes.slice(1).forEach((lane, i) => expect(lane.y).toBe(l.lanes[i].y + l.lanes[i].h));
    const last = l.lanes[l.lanes.length - 1];
    expect(last.y + last.h).toBe(400);
    expect(l.hitRowPx).toBe(HIT_ROW_PX);
    expect(l.hitRowsShown).toBe(3);
  });

  it('draws compact bars, 4 px with a 1 px gap, however many rows there are', () => {
    expect(HIT_BAR_PX).toBe(4);
    expect(HIT_GAP_PX).toBe(1);
    expect(HIT_ROW_PX).toBe(5);
    for (const height of [200, 300, 420, 800, 2000]) {
      for (const hitRows of [1, 5, 33, 500]) {
        const l = layoutLanes(height, { ...NONE, hits: true, hitRows });
        if (l.hitRowsShown > 0) {
          expect(l.hitBarPx).toBe(HIT_BAR_PX);
          expect(l.hitRowPx).toBe(HIT_ROW_PX);
        } else {
          expect(l.hitBarPx).toBe(0);
        }
      }
    }
  });

  it('caps the hits block at 28 % of what the fixed rows leave, and drops the rows past it', () => {
    const flags = { ...NONE, hits: true, hitRows: 500 };
    const many = layoutLanes(420, flags);
    const free = 420 - LANE_PX.ruler;
    const block = many.byKey.coverage!.h + many.byKey.hits!.h;
    expect(block).toBeLessThanOrEqual(free * HITS_MAX_SHARE);
    expect(many.hitRowsShown).toBeGreaterThan(0);
    expect(many.hitRowsShown).toBeLessThan(500);
    expect(many.hitRowsTotal).toBe(500);
    // One more row would break the cap.
    expect(block + HIT_ROW_PX).toBeGreaterThan(free * HITS_MAX_SHARE);
  });

  it('keeps the logo at 55 % of the panel, the hits giving way before it', () => {
    const rows = { consensus: true, rf: true, cs: true, insertProb: true, insertLength: true, occupancy: true };
    for (const height of [260, 320, 400, 600, 1000]) {
      for (const extra of [{}, rows]) {
        const l = layoutLanes(height, { ...NONE, ...extra, hits: true, hitRows: 33 });
        const bare = layoutLanes(height, { ...NONE, ...extra, hits: true, hitRows: 0 });
        // Whenever bars are drawn the logo still holds its share.
        if (l.hitRowsShown > 0) {
          expect(l.byKey.logo!.h).toBeGreaterThanOrEqual(Math.max(LOGO_MIN_PX, LOGO_MIN_SHARE * height) - 1e-9);
        }
        // And the bars never cost the coverage lane.
        expect(l.byKey.coverage!.h).toBe(LANE_PX.coverage);
        expect(bare.byKey.coverage!.h).toBe(LANE_PX.coverage);
      }
    }
  });

  it('takes a 33 row hits lane down to a fraction of the plot, the logo staying the larger part', () => {
    const l = layoutLanes(420, { ...NONE, hits: true, hitRows: 33 });
    const hitsBlock = l.byKey.coverage!.h + l.byKey.hits!.h;
    // The 33 full width bars used to take about 45 % of the plot.
    expect(hitsBlock / 420).toBeLessThan(0.3);
    expect(l.byKey.logo!.h / 420).toBeGreaterThanOrEqual(LOGO_MIN_SHARE);
    expect(l.hitRowsShown).toBeLessThan(33);
  });

  it('draws no bars where the coverage lane alone fills the cap, and keeps the coverage', () => {
    const l = layoutLanes(120, { ...NONE, hits: true, hitRows: 33 });
    expect(l.hitRowsShown).toBe(0);
    expect(l.byKey.hits).toBeUndefined();
    expect(l.byKey.coverage).toBeDefined();
  });

  it('hits-tests the rows it draws with the pitch it draws them at', () => {
    const l = layoutLanes(420, { ...NONE, hits: true, hitRows: 33 });
    const lane = l.byKey.hits!;
    for (let row = 0; row < l.hitRowsShown; row++) {
      const top = hitBarTop(lane, row);
      expect(hitRowAt(l, top)).toBe(row);
      expect(hitRowAt(l, top + l.hitBarPx - 0.01)).toBe(row);
      // The gap under a bar belongs to its row.
      expect(hitRowAt(l, top + l.hitRowPx - 0.01)).toBe(row);
      expect(hitBarTop(lane, row) + l.hitBarPx).toBeLessThanOrEqual(lane.y + lane.h);
    }
    expect(hitRowAt(l, lane.y - 1)).toBe(-1);
    expect(hitRowAt(l, lane.y + lane.h)).toBe(-1);
    expect(hitRowAt(layoutLanes(420, NONE), 10)).toBe(-1);
  });

  it('is natural at the height where its preferred rows are all drawn', () => {
    const rows = { consensus: true, rf: true, cs: true, insertProb: true, insertLength: true, occupancy: true };
    for (const extra of [{}, rows]) {
      for (const hitRows of [3, 8, 16, 33]) {
        const flags = { ...NONE, ...extra, hits: true, hitRows };
        const natural = layoutLanes(0, flags).natural;
        const at = layoutLanes(natural, flags);
        expect(at.hitRowsShown).toBe(Math.min(hitRows, HITS_NATURAL_ROWS));
      }
    }
  });

  it('has no bars lane without hits, but keeps the coverage lane', () => {
    const l = layoutLanes(300, { ...NONE, hits: true, hitRows: 0 });
    expect(l.byKey.coverage).toBeDefined();
    expect(l.byKey.hits).toBeUndefined();
  });

  it('asks for more room as lanes are added', () => {
    const bare = layoutLanes(200, NONE).natural;
    const full = layoutLanes(200, { ...NONE, consensus: true, hits: true, hitRows: 10 }).natural;
    expect(full).toBeGreaterThan(bare);
  });

  it('finds the lane under a point', () => {
    const l = layoutLanes(300, { ...NONE, consensus: true });
    expect(laneAt(l, 0)?.key).toBe('logo');
    expect(laneAt(l, l.byKey.consensus!.y + 1)?.key).toBe('consensus');
    expect(laneAt(l, 1000)).toBeNull();
  });
});

describe('layoutLanes tracks', () => {
  const ALL = { consensus: true, rf: true, cs: true, insertProb: true, insertLength: true, occupancy: true };
  const flags = { ...NONE, ...ALL, hits: true, hitRows: 4 };

  it('is unchanged without hidden or collapsed tracks', () => {
    const plain = layoutLanes(420, flags);
    const empty = layoutLanes(420, { ...flags, hiddenTracks: [], collapsedTracks: [] });
    expect(empty).toEqual(plain);
    expect(plain.strips).toEqual({});
    expect(plain.tracks.map((t) => t.track)).toEqual(['consensus', 'insert', 'occupancy', 'hits', 'ruler']);
  });

  it('gives the room of a hidden track to the logo', () => {
    const before = layoutLanes(420, flags);
    const after = layoutLanes(420, { ...flags, hiddenTracks: ['consensus'] });
    expect(after.byKey.consensus).toBeUndefined();
    expect(after.byKey.rf).toBeUndefined();
    expect(after.byKey.logo!.h).toBeGreaterThan(before.byKey.logo!.h);
    const last = after.lanes[after.lanes.length - 1];
    expect(last.y + last.h).toBe(420);
    expect(after.natural).toBeLessThan(before.natural);
  });

  it('swaps a collapsed track for one strip and frees the rest', () => {
    const before = layoutLanes(420, flags);
    const after = layoutLanes(420, { ...flags, collapsedTracks: ['insert'] });
    expect(after.byKey.insertProb).toBeUndefined();
    expect(after.strips.insert).toEqual({ key: 'strip', track: 'insert', y: after.strips.insert!.y, h: COLLAPSED_TRACK_PX });
    expect(after.byKey.logo!.h).toBe(before.byKey.logo!.h + LANE_PX.insertProb + LANE_PX.insertLength - COLLAPSED_TRACK_PX);
    expect(after.tracks.find((t) => t.track === 'insert')).toMatchObject({ collapsed: true, h: COLLAPSED_TRACK_PX });
    const last = after.lanes[after.lanes.length - 1];
    expect(last.y + last.h).toBe(420);
  });

  it('lets hidden win over collapsed', () => {
    const l = layoutLanes(420, { ...flags, hiddenTracks: ['occupancy'], collapsedTracks: ['occupancy'] });
    expect(l.strips.occupancy).toBeUndefined();
    expect(l.tracks.some((t) => t.track === 'occupancy')).toBe(false);
  });

  it('collapses the hits to a strip: no bars, no rows, no coverage lane', () => {
    const l = layoutLanes(420, { ...flags, collapsedTracks: ['hits'] });
    expect(l.byKey.coverage).toBeUndefined();
    expect(l.byKey.hits).toBeUndefined();
    expect(l.strips.hits).toBeDefined();
    expect(l.hitRowsShown).toBe(0);
    expect(l.hitRowsTotal).toBe(0);
    expect(hitRowAt(l, l.strips.hits!.y + 2)).toBe(-1);
    expect(laneAt(l, l.strips.hits!.y + 2)?.key).toBe('strip');
  });

  it('keeps only the logo above the ruler when every other track is hidden', () => {
    const l = layoutLanes(300, { ...flags, hiddenTracks: ['consensus', 'insert', 'occupancy', 'hits'] });
    expect(l.lanes.map((x) => x.key)).toEqual(['logo', 'ruler']);
    expect(l.byKey.logo!.h).toBe(300 - LANE_PX.ruler);
  });

  it('keeps the logo when everything, the ruler included, is hidden', () => {
    const l = layoutLanes(300, { ...flags, hiddenTracks: ['consensus', 'insert', 'occupancy', 'hits', 'ruler'] });
    expect(l.lanes.map((x) => x.key)).toEqual(['logo']);
    expect(l.byKey.logo).toEqual({ key: 'logo', y: 0, h: 300 });
    expect(l.gridBottom).toBe(300);
  });

  it('shows the hits alone with its bars when the other tracks are hidden', () => {
    const l = layoutLanes(420, { ...flags, hiddenTracks: ['consensus', 'insert', 'occupancy', 'ruler'] });
    expect(l.lanes.map((x) => x.key)).toEqual(['logo', 'coverage', 'hits']);
    expect(l.hitRowsShown).toBeGreaterThan(0);
    const lane = l.byKey.hits!;
    expect(hitRowAt(l, hitBarTop(lane, 0))).toBe(0);
  });

  it('puts the grid bottom at the ruler, or at its strip', () => {
    expect(layoutLanes(300, NONE).gridBottom).toBe(300 - LANE_PX.ruler);
    const l = layoutLanes(300, { ...NONE, collapsedTracks: ['ruler'] });
    expect(l.gridBottom).toBe(300 - COLLAPSED_TRACK_PX);
  });

  it('is natural at its own height with tracks hidden or collapsed', () => {
    for (const extra of [{ hiddenTracks: ['insert'] }, { collapsedTracks: ['hits', 'consensus'] }, { collapsedTracks: ['occupancy'] }] as Partial<LaneFlags>[]) {
      const f = { ...flags, hitRows: 8, ...extra };
      const natural = layoutLanes(0, f).natural;
      const at = layoutLanes(natural, f);
      expect(at.byKey.logo!.h).toBeGreaterThanOrEqual(150 - 1);
    }
  });
});

describe('logoAxis', () => {
  it('rounds the tallest stack up to a 1-2-5 tick', () => {
    expect(logoAxis(4.3, 'relent_abovebg')).toEqual({ top: 5, ticks: [0, 1, 2, 3, 4, 5], unit: 'bits' });
    expect(logoAxis(1.9, 'relent_all').top).toBe(2);
    expect(logoAxis(0.2, 'relent_all').top).toBe(1);
    expect(logoAxis(0, 'relent_all').top).toBe(1);
  });

  it('is 0 to 1 in probability mode', () => {
    expect(logoAxis(7, 'probability')).toEqual({ top: 1, ticks: [0, 0.5, 1], unit: 'prob' });
  });
});

describe('ramps', () => {
  it('interpolates between stops', () => {
    const stops: [number, number, number][] = [
      [0, 0, 0],
      [100, 200, 50],
      [200, 200, 200],
    ];
    expect(rampColour(stops, 0)).toEqual([0, 0, 0]);
    expect(rampColour(stops, 0.25)).toEqual([50, 100, 25]);
    expect(rampColour(stops, 1)).toEqual([200, 200, 200]);
    expect(rampColour(stops, 9)).toEqual([200, 200, 200]);
    expect(rampColour([[1, 2, 3]], 0.5)).toEqual([1, 2, 3]);
  });

  it('puts insert lengths on a log share of the longest', () => {
    expect(insertLengthShare(1, 100)).toBe(0);
    expect(insertLengthShare(10, 100)).toBeCloseTo(0.5);
    expect(insertLengthShare(100, 100)).toBe(1);
    expect(insertLengthShare(null, 100)).toBe(0);
    expect(insertLengthShare(5, 1)).toBe(0);
  });
});
