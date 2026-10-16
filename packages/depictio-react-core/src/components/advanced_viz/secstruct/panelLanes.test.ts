import { describe, expect, it } from 'vitest';

import {
  AGREEMENT_PX,
  EXTRA_RIBBON_PX,
  LANE_GAP,
  LANE_GAP_MAX,
  LETTERS_PX,
  layoutPanelLanes,
  naturalPanelHeight,
  PROB_MAX_PX,
  PROB_PX,
  RULER_PX,
  type PanelLanePresence,
} from './panelLanes';
import { DEFAULT_RIBBON_PX, MAIN_RIBBON_MAX_PX, MAIN_RIBBON_SOLO_MAX_PX } from './ribbonHeight';

const bare: PanelLanePresence = {
  letters: false,
  extraSources: 0,
  agreement: false,
  probabilities: false,
};
const full: PanelLanePresence = {
  letters: true,
  extraSources: 1,
  agreement: true,
  probabilities: true,
};
const single: PanelLanePresence = { ...bare, probabilities: true };

const heightsOf = (layout: ReturnType<typeof layoutPanelLanes>, key: string) =>
  layout.lanes.filter((l) => l.key === key).map((l) => l.h);
const heightOf = (layout: ReturnType<typeof layoutPanelLanes>, key: string) =>
  heightsOf(layout, key)[0];

describe('naturalPanelHeight', () => {
  it('sums the base heights and a gap per lane', () => {
    expect(naturalPanelHeight(bare)).toBe(RULER_PX + DEFAULT_RIBBON_PX + 2 * LANE_GAP);
    expect(naturalPanelHeight(full)).toBe(
      RULER_PX +
        LETTERS_PX +
        DEFAULT_RIBBON_PX +
        EXTRA_RIBBON_PX +
        AGREEMENT_PX +
        PROB_PX +
        6 * LANE_GAP,
    );
  });

  it('draws as many extra ribbons as there are further sources', () => {
    const one = naturalPanelHeight({ ...bare, extraSources: 1 });
    const three = naturalPanelHeight({ ...bare, extraSources: 3 });
    expect(three - one).toBe(2 * (EXTRA_RIBBON_PX + LANE_GAP));
    expect(naturalPanelHeight({ ...bare, extraSources: -2 })).toBe(naturalPanelHeight(bare));
  });

  it('counts a chosen ribbon height instead of the default', () => {
    expect(naturalPanelHeight({ ...bare, ribbonHeight: 48 })).toBe(RULER_PX + 48 + 2 * LANE_GAP);
    expect(naturalPanelHeight({ ...bare, ribbonHeight: null })).toBe(naturalPanelHeight(bare));
  });
});

describe('layoutPanelLanes', () => {
  it('lists the lanes top to bottom, ribbons by source', () => {
    const layout = layoutPanelLanes({ ...full, extraSources: 2 }, 400);
    expect(layout.lanes.map((l) => l.key)).toEqual([
      'ruler',
      'letters',
      'ribbon',
      'ribbon',
      'ribbon',
      'agreement',
      'probabilities',
    ]);
    expect(layout.lanes.filter((l) => l.key === 'ribbon').map((l) => l.source)).toEqual([0, 1, 2]);
  });

  it('keeps every lane at its base height when there is no spare room', () => {
    const natural = naturalPanelHeight(full);
    for (const viewH of [natural, natural - 40, 0, Number.NaN]) {
      const layout = layoutPanelLanes(full, viewH);
      expect(layout.top).toBe(0);
      expect(layout.gap).toBe(LANE_GAP);
      expect(layout.stackH).toBe(natural);
      expect(layout.lanes.map((l) => l.h)).toEqual([
        RULER_PX,
        LETTERS_PX,
        DEFAULT_RIBBON_PX,
        EXTRA_RIBBON_PX,
        AGREEMENT_PX,
        PROB_PX,
      ]);
    }
  });

  it('places lanes top to bottom with the gap between them', () => {
    const layout = layoutPanelLanes(full, 330);
    let y = layout.top;
    for (const lane of layout.lanes) {
      expect(lane.y).toBe(y);
      y += lane.h + layout.gap;
    }
    expect(layout.stackH).toBe(y - layout.top);
  });

  it('gives the probabilities most of a little spare room, the ribbon some, the ruler none', () => {
    const layout = layoutPanelLanes(single, naturalPanelHeight(single) + 30);
    const grew = (key: string, base: number) => heightOf(layout, key) - base;
    expect(grew('ruler', RULER_PX)).toBe(0);
    expect(grew('ribbon', DEFAULT_RIBBON_PX)).toBeGreaterThan(0);
    expect(grew('probabilities', PROB_PX)).toBeGreaterThan(grew('ribbon', DEFAULT_RIBBON_PX));
    // The spare room is spent to the pixel: nothing to centre or to widen the gaps with.
    expect(layout.top).toBe(0);
    expect(layout.gap).toBe(LANE_GAP);
    expect(layout.stackH).toBe(naturalPanelHeight(single) + 30);
  });

  it('fills a ~330 px cell: the small lanes at their caps, the probabilities take the rest', () => {
    const viewH = 330;
    const layout = layoutPanelLanes(full, viewH);
    expect(heightOf(layout, 'letters')).toBe(22);
    expect(heightOf(layout, 'agreement')).toBe(20);
    expect(heightsOf(layout, 'ribbon')[0]).toBe(MAIN_RIBBON_MAX_PX);
    expect(heightOf(layout, 'probabilities')).toBeGreaterThan(150);
    expect(heightOf(layout, 'probabilities')).toBeLessThan(PROB_MAX_PX);
    expect(layout.top).toBe(0);
    expect(layout.top + layout.stackH).toBeLessThanOrEqual(viewH);
    expect(layout.stackH).toBeGreaterThan(viewH - 10);
  });

  it('fills a linked-view pane (~540 px) with the probabilities rather than with air', () => {
    const viewH = 540;
    const layout = layoutPanelLanes(single, viewH);
    expect(heightOf(layout, 'probabilities')).toBeGreaterThan(300);
    expect(layout.top).toBeLessThan(10);
    expect(layout.top + layout.stackH).toBeLessThanOrEqual(viewH);
  });

  it('caps every lane, widens the gaps to their limit, centres the stack in a tall cell', () => {
    const viewH = 1400;
    const layout = layoutPanelLanes(full, viewH);
    expect(heightOf(layout, 'probabilities')).toBe(PROB_MAX_PX);
    expect(heightOf(layout, 'ruler')).toBe(RULER_PX);
    expect(layout.gap).toBe(LANE_GAP_MAX);
    const below = viewH - (layout.top + layout.stackH);
    expect(layout.top).toBeGreaterThan(0);
    expect(Math.abs(layout.top - below)).toBeLessThanOrEqual(1);
    // The offset is part of every lane's y, so hit-testing needs no second correction.
    expect(layout.lanes[0].y).toBe(layout.top);
  });

  it('lets the ribbon grow further when there is no probability lane to feed', () => {
    const withProbs = layoutPanelLanes(single, 600);
    const solo = layoutPanelLanes(bare, 600);
    expect(heightOf(withProbs, 'ribbon')).toBe(MAIN_RIBBON_MAX_PX);
    expect(heightOf(solo, 'ribbon')).toBe(MAIN_RIBBON_SOLO_MAX_PX);
    // Nothing else can take the room: the stack is centred.
    expect(solo.top).toBeGreaterThan(0);
  });

  it('draws a chosen ribbon height exactly, on a cell of any size', () => {
    for (const ribbonHeight of [16, 30, 44, 64]) {
      for (const probabilities of [true, false]) {
        const present = { ...bare, probabilities, ribbonHeight };
        for (const viewH of [0, naturalPanelHeight(present), 400, 1200]) {
          expect(heightOf(layoutPanelLanes(present, viewH), 'ribbon')).toBe(ribbonHeight);
        }
      }
    }
  });

  it('gives a chosen ribbon height no share of the spare room: the probabilities take it', () => {
    const viewH = 300;
    const grown = layoutPanelLanes({ ...single, ribbonHeight: null }, viewH);
    const chosen = layoutPanelLanes({ ...single, ribbonHeight: DEFAULT_RIBBON_PX }, viewH);
    expect(heightOf(chosen, 'probabilities')).toBeGreaterThan(heightOf(grown, 'probabilities'));
  });

  it('lets a lane hand its unused share on once it is at its cap', () => {
    // The ribbon and the extra ribbon saturate long before the probabilities do:
    // what they leave over goes to the probability lane, not to air.
    const present = { ...bare, extraSources: 1, probabilities: true };
    const layout = layoutPanelLanes(present, 500);
    expect(heightsOf(layout, 'ribbon')).toEqual([MAIN_RIBBON_MAX_PX, 28]);
    expect(layout.top).toBe(0);
    expect(layout.stackH).toBe(500);
  });

  it('keeps whole pixels, so the canvas rules stay crisp', () => {
    for (const present of [bare, single, full, { ...full, ribbonHeight: 37.4 }]) {
      for (const viewH of [133, 157, 201, 249.6, 318, 411, 777]) {
        const layout = layoutPanelLanes(present, viewH);
        expect(Number.isInteger(layout.top)).toBe(true);
        expect(Number.isInteger(layout.gap)).toBe(true);
        expect(Number.isInteger(layout.naturalH)).toBe(true);
        for (const lane of layout.lanes) {
          expect(Number.isInteger(lane.y)).toBe(true);
          expect(Number.isInteger(lane.h)).toBe(true);
        }
      }
    }
  });

  it('never draws past the cell it was given', () => {
    for (const present of [bare, single, full]) {
      for (const viewH of [60, 133, 200, 330, 420, 800, 1400]) {
        const layout = layoutPanelLanes(present, viewH);
        if (viewH >= layout.naturalH) {
          expect(layout.top + layout.stackH).toBeLessThanOrEqual(viewH);
        }
      }
    }
  });

  it('reports the natural height a panel with no cell of its own takes', () => {
    expect(layoutPanelLanes(full, 500).naturalH).toBe(naturalPanelHeight(full));
    expect(layoutPanelLanes(bare, 500).naturalH).toBe(naturalPanelHeight(bare));
  });
});
