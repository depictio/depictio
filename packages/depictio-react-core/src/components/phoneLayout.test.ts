import { describe, expect, it } from 'vitest';

import { phoneLayout } from '../gridConfig';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });

describe('phoneLayout', () => {
  it('pairs a row of four quarter-width cards, in reading order', () => {
    const lg = [tile('d', 6, 0, 2, 2), tile('a', 0, 0, 2, 2), tile('c', 4, 0, 2, 2), tile('b', 2, 0, 2, 2)];
    const out = Object.fromEntries(phoneLayout(lg, 2).map((t) => [t.i, [t.x, t.y, t.w]]));
    expect(out).toEqual({ a: [0, 0, 1], b: [1, 0, 1], c: [0, 2, 1], d: [1, 2, 1] });
  });

  it('gives anything wider than a quarter the full row', () => {
    const lg = [tile('map', 0, 0, 4, 5), tile('pcoa', 4, 0, 4, 5), tile('text', 0, 5, 8, 2)];
    const out = phoneLayout(lg, 2).map((t) => [t.i, t.x, t.y, t.w]);
    expect(out).toEqual([
      ['map', 0, 0, 2],
      ['pcoa', 0, 5, 2],
      ['text', 0, 10, 2],
    ]);
  });

  it('starts a new row when a full-width tile follows a lone half', () => {
    const lg = [tile('a', 0, 0, 2, 3), tile('b', 0, 3, 8, 2)];
    expect(phoneLayout(lg, 2).map((t) => [t.x, t.y, t.w])).toEqual([
      [0, 0, 1],
      [0, 3, 2],
    ]);
  });
});
