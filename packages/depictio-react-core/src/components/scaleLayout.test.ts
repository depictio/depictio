import { describe, expect, it } from 'vitest';

import { scaleLayout } from '../gridConfig';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });
const geometry = (tiles: ReturnType<typeof tile>[]) =>
  Object.fromEntries(tiles.map((t) => [t.i, [t.x, t.y, t.w, t.h]]));

describe('scaleLayout', () => {
  const cards = [tile('a', 0, 2, 2, 2), tile('b', 2, 2, 2, 2), tile('c', 4, 2, 2, 2), tile('d', 6, 2, 2, 2)];

  it('wraps a row of four cards into two lines of two at six columns', () => {
    expect(geometry(scaleLayout(cards, 6))).toEqual({
      a: [0, 2, 3, 2],
      b: [3, 2, 3, 2],
      c: [0, 4, 3, 2],
      d: [3, 4, 3, 2],
    });
  });

  it('keeps the row when the columns divide it', () => {
    expect(scaleLayout(cards, 4).map((t) => [t.x, t.y, t.w])).toEqual([
      [0, 2, 1],
      [1, 2, 1],
      [2, 2, 1],
      [3, 2, 1],
    ]);
  });

  it('moves the rows below a wrapped row down by the line it gained', () => {
    const lg = [tile('intro', 0, 0, 8, 2), ...cards, tile('fig', 0, 4, 4, 5), tile('fig2', 4, 4, 4, 5)];
    const out = geometry(scaleLayout(lg, 6));
    expect(out.intro).toEqual([0, 0, 6, 2]);
    expect(out.fig).toEqual([0, 6, 3, 5]);
    expect(out.fig2).toEqual([3, 6, 3, 5]);
  });

  it('scales the edges of a row that is not a set of equal tiles', () => {
    const lg = [tile('wide', 0, 0, 6, 3), tile('narrow', 6, 0, 2, 3)];
    expect(geometry(scaleLayout(lg, 6))).toEqual({ wide: [0, 0, 5, 3], narrow: [5, 0, 1, 3] });
  });
});
