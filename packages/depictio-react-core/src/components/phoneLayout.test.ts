import { describe, expect, it } from 'vitest';

import { phoneLayout, toSplitRows } from '../gridConfig';
import { fitLayoutHeights, GRID_ROW_GAP_PX, GRID_ROW_PX, SPLIT_ROW_PX } from './autofit';

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

describe('read-only rows', () => {
  const span = (rows: number, rowPx: number) => rows * rowPx + (rows - 1) * GRID_ROW_GAP_PX;

  it('keeps a stored tile its height to the pixel', () => {
    const [fig] = toSplitRows([tile('fig', 0, 3, 8, 4)]);
    expect(fig.y).toBe(6);
    expect(span(fig.h, SPLIT_ROW_PX)).toBe(span(4, GRID_ROW_PX));
  });

  const members = [
    { index: 'text', component_type: 'text' },
    { index: 'framed', component_type: 'text', surface: 'card' },
    { index: 'card', component_type: 'card' },
    { index: 'fig', component_type: 'figure' },
  ];
  const stored = toSplitRows([
    { i: 'text', y: 0, h: 4 },
    { i: 'framed', y: 4, h: 2 },
    { i: 'card', y: 6, h: 2 },
    { i: 'fig', y: 8, h: 5 },
  ]);
  const fit = (heights: Record<string, number>) =>
    Object.fromEntries(
      fitLayoutHeights(members, stored, heights, true, SPLIT_ROW_PX).map((l) => [l.i, l.h]),
    );

  it('stops text within half a stored row of its content', () => {
    // 521px: six whole rows (620px), eleven half rows (568px).
    expect(fit({ text: 521 }).text).toBe(11);
    // 210px: three whole rows (308px), five half rows (256px).
    expect(fit({ framed: 210 }).framed).toBe(5);
  });

  it('grows a card from its stored height and leaves figures alone', () => {
    expect(fit({ card: 150 })).toMatchObject({ card: 4, fig: 10 });
    expect(fit({ card: 260 }).card).toBe(6);
  });
});
