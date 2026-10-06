import { describe, expect, it } from 'vitest';

import { isPhoneWidth, phoneLayout } from '../gridConfig';
import { fitPhoneRows, GRID_ROW_GAP_PX, GRID_ROW_PX, PHONE_ROW_PX } from './autofit';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });

describe('phoneLayout', () => {
  it('pairs a row of four quarter-width cards, in reading order', () => {
    const lg = [tile('d', 6, 0, 2, 2), tile('a', 0, 0, 2, 2), tile('c', 4, 0, 2, 2), tile('b', 2, 0, 2, 2)];
    const out = Object.fromEntries(phoneLayout(lg, 2).map((t) => [t.i, [t.x, t.y, t.w]]));
    expect(out).toEqual({ a: [0, 0, 1], b: [1, 0, 1], c: [0, 4, 1], d: [1, 4, 1] });
  });

  it('gives anything wider than a quarter the full row', () => {
    const lg = [tile('map', 0, 0, 4, 5), tile('pcoa', 4, 0, 4, 5), tile('text', 0, 5, 8, 2)];
    const out = phoneLayout(lg, 2).map((t) => [t.i, t.x, t.y, t.w]);
    expect(out).toEqual([
      ['map', 0, 0, 2],
      ['pcoa', 0, 10, 2],
      ['text', 0, 20, 2],
    ]);
  });

  it('starts a new row when a full-width tile follows a lone half', () => {
    const lg = [tile('a', 0, 0, 2, 3), tile('b', 0, 3, 8, 2)];
    expect(phoneLayout(lg, 2).map((t) => [t.x, t.y, t.w])).toEqual([
      [0, 0, 1],
      [0, 6, 2],
    ]);
  });

  it('keeps a tile its desktop height, in phone rows', () => {
    const lg = [tile('fig', 0, 0, 8, 4)];
    const [fig] = phoneLayout(lg, 2);
    // Four desktop rows, and the same pixels in phone rows.
    expect(fig.h * PHONE_ROW_PX + (fig.h - 1) * GRID_ROW_GAP_PX).toBe(
      4 * GRID_ROW_PX + 3 * GRID_ROW_GAP_PX,
    );
  });

  it('sizes a fitted tile to its phone rows and stacks the next one under it', () => {
    const lg = [tile('text', 0, 0, 8, 4), tile('fig', 0, 4, 8, 2)];
    const out = phoneLayout(lg, 2, { text: 11 });
    expect(out.map((t) => [t.i, t.y, t.h])).toEqual([
      ['text', 0, 11],
      ['fig', 11, 4],
    ]);
  });
});

describe('isPhoneWidth', () => {
  it('matches the xs breakpoint', () => {
    expect(isPhoneWidth(390)).toBe(true);
    expect(isPhoneWidth(560)).toBe(true);
    expect(isPhoneWidth(561)).toBe(false);
  });
});

describe('fitPhoneRows', () => {
  const members = [
    { index: 'text', component_type: 'text' },
    { index: 'card', component_type: 'card' },
    { index: 'fig', component_type: 'figure' },
  ];
  const stored = [
    { i: 'text', y: 0, h: 4 },
    { i: 'card', y: 4, h: 2 },
    { i: 'fig', y: 6, h: 5 },
  ];

  it('stops text within half a desktop row of its content', () => {
    // 521px: six desktop rows (620px), but eleven phone rows (568px).
    const rows = fitPhoneRows(members, stored, { text: 521 });
    expect(rows.text).toBe(11);
    expect(rows.text * PHONE_ROW_PX + (rows.text - 1) * GRID_ROW_GAP_PX).toBeLessThan(
      521 + PHONE_ROW_PX + GRID_ROW_GAP_PX,
    );
  });

  it('grows a card from its authored height and leaves figures alone', () => {
    expect(fitPhoneRows(members, stored, { card: 150 })).toMatchObject({ card: 4, fig: 10 });
    expect(fitPhoneRows(members, stored, { card: 260 }).card).toBe(6);
  });

  it('measures nothing in the editor', () => {
    expect(fitPhoneRows(members, stored, { text: 521 }, false).text).toBe(8);
  });
});
