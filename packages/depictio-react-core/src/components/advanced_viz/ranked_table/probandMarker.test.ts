import { describe, expect, it } from 'vitest';

import {
  LABEL_OFFSET,
  labelBaseline,
  markerReach,
  outlineDistance,
  probandMarker,
} from './probandMarker';

const SEXES = ['male', 'female', 'unknown'] as const;
const dist = (p: { x: number; y: number }) => Math.hypot(p.x, p.y);

describe('outlineDistance', () => {
  it('is the radius for a circle, the corner for a square, the edge for a diamond', () => {
    expect(outlineDistance('female', 9)).toBeCloseTo(9);
    expect(outlineDistance('male', 9)).toBeCloseTo(9 * Math.SQRT2);
    // diamond radius 1.2 * 9 = 10.8; on the diagonal |x| + |y| = r gives r / sqrt 2
    expect(outlineDistance('unknown', 9)).toBeCloseTo(10.8 / Math.SQRT2);
  });

  it('grows with the ring drawn around the symbol', () => {
    expect(outlineDistance('female', 9, 3.5)).toBeCloseTo(12.5);
  });
});

describe('probandMarker', () => {
  it('rests its tip just outside the outline, whatever the sex', () => {
    for (const sex of SEXES) {
      const m = probandMarker(sex, 9, { ring: 3.5 });
      expect(dist(m.tip) - outlineDistance(sex, 9, 3.5)).toBeCloseTo(1.5);
    }
  });

  it('comes from the lower left', () => {
    for (const sex of SEXES) {
      const m = probandMarker(sex, 9);
      expect(m.tip.x).toBeLessThan(0);
      expect(m.tip.y).toBeGreaterThan(0);
      expect(m.tail.x).toBeLessThan(m.tip.x);
      expect(m.tail.y).toBeGreaterThan(m.tip.y);
      // 45 degrees: the shaft runs along the diagonal
      expect(m.tail.x - m.tip.x).toBeCloseTo(-(m.tail.y - m.tip.y));
    }
  });

  it('draws the head at the tip, behind it along the shaft', () => {
    const m = probandMarker('female', 9, { ring: 3.5 });
    for (const stroke of m.head) {
      // each stroke ends on the tail's side of the tip
      expect(stroke.x).toBeLessThan(m.tip.x + 1e-9);
      expect(stroke.y).toBeGreaterThan(m.tip.y - 1e-9);
      expect(Math.hypot(stroke.x - m.tip.x, stroke.y - m.tip.y)).toBeCloseTo(5.5);
    }
    // symmetric about the shaft
    const [a, b] = m.head;
    expect(dist({ x: a.x - m.tip.x, y: a.y - m.tip.y })).toBeCloseTo(
      dist({ x: b.x - m.tip.x, y: b.y - m.tip.y }),
    );
  });

  it('scales with the symbol', () => {
    const one = probandMarker('female', 9, { ring: 3.5 });
    const half = probandMarker('female', 9, { ring: 3.5, scale: 0.5 });
    const shaft = (m: typeof one) => Math.hypot(m.tail.x - m.tip.x, m.tail.y - m.tip.y);
    expect(shaft(half)).toBeCloseTo(shaft(one) / 2);
  });

  it('keeps the P clear of the label under the symbol, for every sex and ring', () => {
    // The label is centred, up to about 8 characters of 9 px text (4.6 wide each).
    const labelHalfWidth = 18.5;
    const labelTop = labelBaseline(9) - 8;
    for (const sex of SEXES) {
      for (const ring of [0, 3.5]) {
        const m = probandMarker(sex, 9, { ring });
        const letterRight = m.letter.x + 3.5;
        const letterBottom = m.letter.y + 3.5;
        // Either the P is to the left of the label, or above it
        expect(letterRight < -labelHalfWidth || letterBottom < labelTop).toBe(true);
        // and so is the end of the shaft
        expect(m.tail.x < -labelHalfWidth || m.tail.y < labelTop).toBe(true);
      }
    }
  });

  it('stays inside the margin the drawing reserves', () => {
    const reach = markerReach(9, 3.5);
    for (const sex of SEXES) {
      const m = probandMarker(sex, 9, { ring: 3.5 });
      expect(-m.letter.x + 3.5).toBeLessThanOrEqual(reach.left + 1e-9);
      expect(m.letter.y + 3.5).toBeLessThanOrEqual(reach.down + 1e-9);
    }
    // and the P does not reach the neighbour's ring in a 54 px slot (ring 12.5)
    expect(reach.left).toBeLessThan(54 - 12.5);
  });
});

describe('labelBaseline', () => {
  it('sits below the symbol edge by LABEL_OFFSET', () => {
    expect(labelBaseline(9)).toBe(9 + LABEL_OFFSET);
  });
});
