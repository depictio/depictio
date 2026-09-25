import { describe, it, expect, beforeAll } from 'vitest';
import {
  autofitHeights,
  effectiveFit,
  fitLayoutHeights,
  heightForRows,
  isAutofitted,
  publishContentDemand,
  rowsForHeight,
} from './autofit';

/** A grid item, at the stored position the author gave it. */
const item = (i: string, y: number, h: number) => ({ i, y, h });
/** A component, with the `fit` the dashboard stores (absent = the default). */
const member = (index: string, component_type: string, fit?: 'auto' | 'fixed') => ({
  index,
  component_type,
  ...(fit ? { fit } : {}),
});
/** The measurement a tile of `rows` rows would publish. */
const asMeasured = (rows: number) => heightForRows(rows);

describe('row conversion', () => {
  it('round-trips rows through pixels', () => {
    for (const rows of [1, 2, 3, 5, 12]) {
      expect(rowsForHeight(heightForRows(rows))).toBe(rows);
    }
  });

  it('charges a whole row for one pixel over', () => {
    expect(rowsForHeight(heightForRows(2) + 1)).toBe(3);
  });
});

describe('effectiveFit', () => {
  it('fits the content types and pins the authored ones', () => {
    expect(effectiveFit('text')).toBe('auto');
    expect(effectiveFit('card')).toBe('auto');
    expect(effectiveFit('table')).toBe('auto');
    expect(effectiveFit('advanced_viz')).toBe('auto');
    expect(effectiveFit('figure')).toBe('fixed');
    expect(effectiveFit('multiqc')).toBe('fixed');
  });

  it('lets a stored value override the default either way', () => {
    expect(effectiveFit('figure', 'auto')).toBe('auto');
    expect(effectiveFit('text', 'fixed')).toBe('fixed');
  });

  it('never fits a type with no policy, whatever it says', () => {
    expect(isAutofitted(member('a', 'jbrowse', 'auto'))).toBe(false);
    expect(isAutofitted(member('a', 'map', 'auto'))).toBe(false);
    expect(isAutofitted(member('a', 'text'))).toBe(true);
    expect(isAutofitted(member('a', 'figure'))).toBe(false);
  });
});

describe('fitLayoutHeights', () => {
  it('grows and shrinks a text tile to its prose', () => {
    const members = [member('t', 'text')];
    const grown = fitLayoutHeights(members, [item('t', 0, 2)], { t: asMeasured(5) });
    expect(grown[0].h).toBe(5);
    const shrunk = fitLayoutHeights(members, [item('t', 0, 6)], { t: asMeasured(1) });
    expect(shrunk[0].h).toBe(1);
  });

  it('grows a card but never shrinks it', () => {
    const members = [member('c', 'card')];
    const grown = fitLayoutHeights(members, [item('c', 0, 2)], { c: asMeasured(3) });
    expect(grown[0].h).toBe(3);
    const kept = fitLayoutHeights(members, [item('c', 0, 3)], { c: asMeasured(1) });
    expect(kept[0].h).toBe(3);
  });

  it('levels a row on its tallest answer', () => {
    const members = [member('a', 'card'), member('b', 'card'), member('c', 'card')];
    const sized = fitLayoutHeights(
      members,
      [item('a', 0, 2), item('b', 0, 2), item('c', 0, 2)],
      { a: asMeasured(1), b: asMeasured(4), c: asMeasured(2) },
    );
    expect(sized.map((l) => l.h)).toEqual([4, 4, 4]);
  });

  it('keys rows on the stored y, not on the packed one', () => {
    // Two rows of two. The second row must not inherit the first row's answer.
    const members = [member('a', 'card'), member('b', 'card'), member('c', 'card')];
    const sized = fitLayoutHeights(
      members,
      [item('a', 0, 2), item('b', 0, 2), item('c', 4, 2)],
      { a: asMeasured(4), b: asMeasured(1), c: asMeasured(2) },
    );
    expect(sized.map((l) => l.h)).toEqual([4, 4, 2]);
  });

  it('shrinks the MultiQC general statistics table but not a MultiQC plot', () => {
    const generalStats = { ...member('g', 'multiqc'), selected_plot: 'general_stats' };
    const plot = { ...member('p', 'multiqc'), selected_module: 'fastqc', selected_plot: 'x' };
    expect(isAutofitted(generalStats)).toBe(true);
    expect(isAutofitted(plot)).toBe(false);
    const sized = fitLayoutHeights(
      [generalStats, plot],
      [item('g', 0, 8), item('p', 8, 8)],
      { g: asMeasured(3), p: asMeasured(3) },
    );
    expect(sized.map((l) => l.h)).toEqual([3, 8]);
    const kept = fitLayoutHeights([generalStats], [item('g', 0, 3)], { g: asMeasured(6) });
    expect(kept[0].h).toBe(3);
  });

  it('leaves a tile the user fixed exactly where it is', () => {
    const members = [member('t', 'text', 'fixed')];
    const sized = fitLayoutHeights(members, [item('t', 0, 6)], { t: asMeasured(1) });
    expect(sized[0].h).toBe(6);
  });

  it('lets a fixed neighbour hold the row up', () => {
    const members = [member('t', 'text'), member('f', 'figure')];
    const sized = fitLayoutHeights(members, [item('t', 0, 2), item('f', 0, 6)], {
      t: asMeasured(1),
    });
    expect(sized.find((l) => l.i === 't')!.h).toBe(6);
    expect(sized.find((l) => l.i === 'f')!.h).toBe(6);
  });

  it('leaves a tile that cannot reach its row at its own height', () => {
    // A two-line card beside a six-row figure: growing it to its 4-row cap
    // would not fill the row either, and would only empty the card out.
    const members = [member('c', 'card'), member('f', 'figure')];
    const sized = fitLayoutHeights(members, [item('c', 0, 2), item('f', 0, 6)], {
      c: asMeasured(2),
    });
    expect(sized.find((l) => l.i === 'c')!.h).toBe(2);
    expect(sized.find((l) => l.i === 'f')!.h).toBe(6);
  });

  it('holds the row up for a neighbour that has not answered yet', () => {
    const members = [member('a', 'table'), member('b', 'table')];
    const sized = fitLayoutHeights(members, [item('a', 0, 5), item('b', 0, 5)], {
      a: asMeasured(2),
    });
    expect(sized.map((l) => l.h)).toEqual([5, 5]);
  });

  it('ignores a figure demand until the figure opts in', () => {
    const fixed = fitLayoutHeights([member('f', 'figure')], [item('f', 0, 5)], {
      f: asMeasured(2),
    });
    expect(fixed[0].h).toBe(5);
    const opted = fitLayoutHeights([member('f', 'figure', 'auto')], [item('f', 0, 5)], {
      f: asMeasured(2),
    });
    expect(opted[0].h).toBe(2);
  });

  it('clamps growth to the type bound', () => {
    // A card stops at 4 rows even when its content asks for 9...
    const capped = fitLayoutHeights([member('c', 'card')], [item('c', 0, 2)], {
      c: asMeasured(9),
    });
    expect(capped[0].h).toBe(4);
    // ...but a taller stored card is an authoring decision, not a violation.
    const authored = fitLayoutHeights([member('c', 'card')], [item('c', 0, 6)], {
      c: asMeasured(9),
    });
    expect(authored[0].h).toBe(6);
  });

  it('clamps a shrink to the type floor', () => {
    const table = fitLayoutHeights([member('t', 'table')], [item('t', 0, 6)], {
      t: asMeasured(1),
    });
    expect(table[0].h).toBe(2);
  });

  it('never grows a table past the height its author chose', () => {
    // A full page of rows is what scrolling is for; the tile stays as stored.
    const table = fitLayoutHeights([member('t', 'table')], [item('t', 0, 6)], {
      t: asMeasured(40),
    });
    expect(table[0].h).toBe(6);
  });

  it('does nothing at all when the dashboard turns autofit off', () => {
    const layouts = [item('t', 0, 6), item('c', 0, 2)];
    const sized = fitLayoutHeights(
      [member('t', 'text'), member('c', 'card')],
      layouts,
      { t: asMeasured(1), c: asMeasured(4) },
      false,
    );
    expect(sized.map((l) => l.h)).toEqual([6, 2]);
  });

  it('keeps every item, measured or not, and its other keys', () => {
    const layouts = [{ i: 't', x: 2, y: 0, w: 4, h: 3 }];
    const sized = fitLayoutHeights([member('t', 'text')], layouts, { t: asMeasured(2) });
    expect(sized).toEqual([{ i: 't', x: 2, y: 0, w: 4, h: 2 }]);
  });
});

describe('publishContentDemand', () => {
  beforeAll(() => {
    // The module publishes through the window it shares with the grids; this
    // suite runs in node, so stand one up.
    (globalThis as unknown as { window: { dispatchEvent: (e: Event) => boolean } }).window = {
      dispatchEvent: () => true,
    };
  });

  it('converts rows to the height a tile of that many rows offers', () => {
    publishContentDemand('demand-a', { rows: 2 });
    expect(autofitHeights().get('demand-a')).toBe(heightForRows(2));
    const sized = fitLayoutHeights(
      [member('demand-a', 'advanced_viz', 'auto')],
      [item('demand-a', 0, 8)],
      Object.fromEntries(autofitHeights()),
    );
    // advanced_viz grows only, and its floor is 3 rows.
    expect(sized[0].h).toBe(8);
  });

  it('says nothing for a tile that never had a demand', () => {
    publishContentDemand('demand-c', { rows: 0 });
    expect(autofitHeights().has('demand-c')).toBe(false);
  });

  it('releases a demand it can no longer make', () => {
    publishContentDemand('demand-b', { rows: 4 });
    expect(autofitHeights().get('demand-b')).toBe(heightForRows(4));
    publishContentDemand('demand-b', { rows: 0 });
    expect(autofitHeights().get('demand-b')).toBe(0);
    const sized = fitLayoutHeights(
      [member('demand-b', 'table')],
      [item('demand-b', 0, 6)],
      Object.fromEntries(autofitHeights()),
    );
    expect(sized[0].h).toBe(6);
  });
});
