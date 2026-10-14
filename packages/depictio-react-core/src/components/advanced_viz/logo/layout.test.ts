import { describe, expect, it } from 'vitest';

import {
  HIT_ROW_MIN_PX,
  HIT_ROW_PX,
  insertLengthShare,
  LANE_PX,
  laneAt,
  layoutLanes,
  LOGO_MIN_PX,
  logoAxis,
  rampColour,
  type LaneFlags,
} from './layout';

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

  it('shrinks hit rows, then drops the ones that do not fit, keeping the logo', () => {
    const many = layoutLanes(300, { ...NONE, hits: true, hitRows: 500 });
    expect(many.hitRowPx).toBe(HIT_ROW_MIN_PX);
    expect(many.hitRowsShown).toBeLessThan(500);
    const free = 300 - LANE_PX.coverage - LANE_PX.ruler;
    expect(many.byKey.hits!.h).toBeLessThanOrEqual(free * 0.45);
    expect(many.byKey.logo!.h).toBeGreaterThan(many.byKey.hits!.h);
    expect(many.byKey.logo!.h).toBeGreaterThanOrEqual(LOGO_MIN_PX);
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
