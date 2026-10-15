import { describe, expect, it } from 'vitest';

import {
  LANE_GAP,
  LANE_GAP_MAX,
  LANE_SPECS,
  lanePresenceOf,
  layoutLanes,
  naturalStripHeight,
  presentLanes,
  type LanePresence,
} from './stripLanes';

const all: LanePresence = {
  letters: true,
  category: true,
  value: true,
  domains: true,
  variants: true,
};
const none: LanePresence = {
  letters: false,
  category: false,
  value: false,
  domains: false,
  variants: false,
};

const heightOf = (layout: ReturnType<typeof layoutLanes>, key: string) =>
  layout.lanes.find((l) => l.key === key)?.h;

describe('presentLanes', () => {
  it('always draws the ruler, then the lanes that are present, top to bottom', () => {
    expect(presentLanes(none)).toEqual(['ruler']);
    expect(presentLanes(all)).toEqual([
      'ruler',
      'letters',
      'category',
      'value',
      'domains',
      'variants',
    ]);
    expect(presentLanes({ ...none, variants: true, value: true })).toEqual([
      'ruler',
      'value',
      'variants',
    ]);
  });
});

describe('naturalStripHeight', () => {
  it('sums the base heights and a gap per lane', () => {
    expect(naturalStripHeight(none)).toBe(LANE_SPECS.ruler.base + LANE_GAP);
    expect(naturalStripHeight(all)).toBe(18 + 14 + 12 + 22 + 18 + 30 + 6 * LANE_GAP);
  });
});

describe('layoutLanes', () => {
  it('keeps every lane at its base height when there is no spare room', () => {
    const natural = naturalStripHeight(all);
    for (const viewH of [natural, natural - 40, 0, Number.NaN]) {
      const layout = layoutLanes(all, viewH);
      expect(layout.top).toBe(0);
      expect(layout.gap).toBe(LANE_GAP);
      for (const lane of layout.lanes) expect(lane.h).toBe(LANE_SPECS[lane.key].base);
    }
  });

  it('places lanes top to bottom with the gap between them', () => {
    const layout = layoutLanes(all, 260);
    let y = layout.top;
    for (const lane of layout.lanes) {
      expect(lane.y).toBe(y);
      y += lane.h + layout.gap;
    }
    expect(layout.stackH).toBe(y - layout.top);
  });

  it('spreads spare height over the lanes by weight, the value and variants lanes most', () => {
    const natural = naturalStripHeight(all);
    const layout = layoutLanes(all, natural + 30);
    const grew = (key: keyof typeof LANE_SPECS) => heightOf(layout, key)! - LANE_SPECS[key].base;
    expect(grew('ruler')).toBe(0);
    expect(grew('value')).toBeGreaterThan(grew('domains'));
    expect(grew('variants')).toBeGreaterThan(grew('letters'));
    expect(grew('variants')).toBe(grew('value'));
    // Nothing is left to centre or to widen the gaps with.
    expect(layout.top).toBe(0);
    expect(layout.gap).toBe(LANE_GAP);
  });

  it('fills a ~330 px cell: lanes at or near their caps, gaps opened, no blank block below', () => {
    const viewH = 330;
    const layout = layoutLanes(all, viewH);
    expect(heightOf(layout, 'variants')).toBe(LANE_SPECS.variants.max);
    expect(heightOf(layout, 'value')).toBe(LANE_SPECS.value.max);
    expect(heightOf(layout, 'letters')).toBe(LANE_SPECS.letters.max);
    expect(heightOf(layout, 'category')).toBe(LANE_SPECS.category.max);
    expect(heightOf(layout, 'domains')).toBe(LANE_SPECS.domains.max);
    expect(layout.top + layout.stackH).toBeLessThanOrEqual(viewH);
    // The stack takes (almost) the whole cell.
    expect(viewH - (layout.top + layout.stackH)).toBeLessThanOrEqual(layout.top + 1);
    expect(layout.stackH).toBeGreaterThan(viewH - 20);
  });

  it('caps every lane, widens the gaps to their limit, centres the stack in a tall cell', () => {
    const viewH = 600;
    const layout = layoutLanes(all, viewH);
    for (const lane of layout.lanes) expect(lane.h).toBeLessThanOrEqual(LANE_SPECS[lane.key].max);
    expect(layout.gap).toBe(LANE_GAP_MAX);
    const below = viewH - (layout.top + layout.stackH);
    expect(layout.top).toBeGreaterThan(0);
    expect(Math.abs(layout.top - below)).toBeLessThanOrEqual(1);
    // The offset is part of every lane's y, so hit-testing needs no second correction.
    expect(layout.lanes[0].y).toBe(layout.top);
  });

  it('lets a lane hand its unused share on once it is at its cap', () => {
    // Value and variants only, equal weights: a spare of 160 would split 80 and
    // 80, but the value lane takes at most 74 (cap 96 over its base 22), and
    // the 6 it leaves go to the variants lane.
    const present = { ...none, value: true, variants: true };
    const natural = naturalStripHeight(present);
    const layout = layoutLanes(present, natural + 160);
    expect(heightOf(layout, 'value')).toBe(LANE_SPECS.value.max);
    expect(heightOf(layout, 'variants')).toBe(LANE_SPECS.variants.base + (160 - 74));
  });

  it('never grows the ruler', () => {
    expect(heightOf(layoutLanes(all, 900), 'ruler')).toBe(LANE_SPECS.ruler.max);
    expect(heightOf(layoutLanes(none, 900), 'ruler')).toBe(LANE_SPECS.ruler.base);
  });

  it('keeps whole pixels, so the canvas rules stay crisp', () => {
    for (const viewH of [133, 157, 201, 249.6, 318, 411, 777]) {
      const layout = layoutLanes(all, viewH);
      expect(Number.isInteger(layout.top)).toBe(true);
      expect(Number.isInteger(layout.gap)).toBe(true);
      for (const lane of layout.lanes) {
        expect(Number.isInteger(lane.y)).toBe(true);
        expect(Number.isInteger(lane.h)).toBe(true);
      }
    }
  });

  it('never draws past the cell it was given', () => {
    for (const viewH of [60, 133, 200, 330, 420, 800]) {
      const layout = layoutLanes(all, viewH);
      if (viewH >= layout.naturalH) {
        expect(layout.top + layout.stackH).toBeLessThanOrEqual(viewH);
      }
    }
  });

  it('reports the natural height a strip with no cell of its own takes', () => {
    expect(layoutLanes(all, 500).naturalH).toBe(naturalStripHeight(all));
    expect(layoutLanes(none, 500).naturalH).toBe(naturalStripHeight(none));
  });
});

describe('lanePresenceOf', () => {
  it('reads which lanes the data draws', () => {
    expect(lanePresenceOf([{ position: 1 }])).toEqual(none);
    expect(
      lanePresenceOf(
        [{ position: 1, letter: 'M', value: 91, category: 'H' }],
        [{ start: 1, end: 10 }],
        [{ position: 3 }],
      ),
    ).toEqual(all);
  });

  it('leaves out the letters lane when the strip is told not to show them', () => {
    expect(lanePresenceOf([{ position: 1, letter: 'M' }], [], [], false).letters).toBe(false);
    expect(lanePresenceOf([{ position: 1, letter: 'M' }], [], [], true).letters).toBe(true);
  });

  it('ignores empty categories, missing values and variants with no usable position', () => {
    const present = lanePresenceOf(
      [{ position: 1, category: '', value: null }],
      [],
      [{ position: Number.NaN }],
    );
    expect(present.category).toBe(false);
    expect(present.value).toBe(false);
    expect(present.variants).toBe(false);
  });
});
