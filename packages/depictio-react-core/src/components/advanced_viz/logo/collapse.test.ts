import { describe, expect, it } from 'vitest';

import {
  addHidden,
  columnsInView,
  expandStub,
  extentAtX,
  indexAtX,
  placeColumns,
  planColumns,
  segmentOfIndex,
  spanOfIndices,
  STUB_PX,
  visibleSegments,
  windowIndices,
  xOfIndex,
  type CollapseSpec,
  type StubSegment,
} from './collapse';

const states = (n: number) => Array.from({ length: n }, (_, i) => i + 1);

/** Information by column: high everywhere but the listed low stretches. */
const info = (n: number, low: Array<[number, number]>) => {
  const out = new Float64Array(n).fill(2);
  for (const [a, b] of low) for (let i = a; i <= b; i++) out[i] = 0.1;
  return out;
};

const shape = (spec: CollapseSpec) =>
  planColumns(spec).segments.map((s) => `${s.kind === 'stub' ? 'S' : 'L'}${s.start}-${s.end}`);

describe('windowIndices', () => {
  it('is the whole profile when open on both sides', () => {
    expect(windowIndices(states(10), null, null)).toEqual([0, 9]);
    expect(windowIndices(states(10), undefined, undefined)).toEqual([0, 9]);
  });
  it('reads 1-based state numbers, not indices', () => {
    expect(windowIndices(states(10), 3, 6)).toEqual([2, 5]);
    expect(windowIndices(states(10), 4, null)).toEqual([3, 9]);
    expect(windowIndices(states(10), null, 4)).toEqual([0, 3]);
  });
  it('follows state numbers when the profile has holes', () => {
    expect(windowIndices([2, 3, 7, 8, 12], 4, 10)).toEqual([2, 3]);
  });
  it('is null when it holds no state', () => {
    expect(windowIndices(states(5), 8, 9)).toBeNull();
    expect(windowIndices([], null, null)).toBeNull();
  });
});

describe('planColumns, window only', () => {
  it('draws the whole profile by default', () => {
    const plan = planColumns({ states: states(8) });
    expect(plan.segments).toEqual([{ kind: 'states', start: 0, end: 7 }]);
    expect(plan).toMatchObject({ first: 0, last: 7, shown: 8, stubs: 0 });
  });
  it('draws only the states inside the window', () => {
    const plan = planColumns({ states: states(20), windowStart: 5, windowEnd: 12 });
    expect(plan.segments).toEqual([{ kind: 'states', start: 4, end: 11 }]);
    expect(plan.shown).toBe(8);
  });
  it('is empty when the window holds nothing', () => {
    expect(planColumns({ states: states(5), windowStart: 9 })).toMatchObject({ segments: [], shown: 0, first: -1 });
  });
});

describe('planColumns, low-information runs', () => {
  const base = (n: number, low: Array<[number, number]>, extra: Partial<CollapseSpec> = {}): CollapseSpec => ({
    states: states(n),
    information: info(n, low),
    belowIc: 0.5,
    minRun: 4,
    ...extra,
  });

  it('folds nothing without a threshold', () => {
    expect(shape({ ...base(12, [[2, 8]]), belowIc: null })).toEqual(['L0-11']);
  });
  it('folds a long enough run into a stub', () => {
    const plan = planColumns(base(12, [[3, 8]]));
    expect(shape(base(12, [[3, 8]]))).toEqual(['L0-2', 'S3-8', 'L9-11']);
    const stub = plan.segments[1] as StubSegment;
    expect(stub).toMatchObject({ source: 'auto', count: 6, key: '3-8' });
    expect(plan).toMatchObject({ shown: 6, stubs: 1 });
  });
  it('keeps a run shorter than the minimum', () => {
    expect(shape(base(12, [[3, 5]]))).toEqual(['L0-11']);
    expect(shape(base(12, [[3, 5]], { minRun: 3 }))).toEqual(['L0-2', 'S3-5', 'L6-11']);
  });
  it('treats the threshold as strict and the minimum as inclusive', () => {
    const information = Float64Array.from([2, 0.5, 0.5, 0.5, 0.5, 2]);
    expect(shape({ states: states(6), information, belowIc: 0.5, minRun: 1 })).toEqual(['L0-5']);
    expect(shape({ states: states(6), information, belowIc: 0.6, minRun: 4 })).toEqual(['L0-0', 'S1-4', 'L5-5']);
  });
  it('folds each run on its own', () => {
    expect(shape(base(20, [[2, 6], [10, 15]]))).toEqual(['L0-1', 'S2-6', 'L7-9', 'S10-15', 'L16-19']);
  });
  it('folds a run that reaches either end of the profile', () => {
    expect(shape(base(10, [[0, 4], [7, 9]], { minRun: 3 }))).toEqual(['S0-4', 'L5-6', 'S7-9']);
  });
  it('measures a run inside the window only', () => {
    // The run is 3-12, but the window cuts it to 8-12 (index): five columns fold.
    const spec = base(20, [[3, 12]], { windowStart: 9, windowEnd: 16 });
    expect(shape(spec)).toEqual(['S8-12', 'L13-15']);
    // Cut to three columns it no longer reaches the minimum.
    expect(shape(base(20, [[3, 12]], { windowStart: 11, windowEnd: 16 }))).toEqual(['L10-15']);
  });
  it('does not fold when the information is unknown', () => {
    expect(shape({ states: states(8), belowIc: 0.5, minRun: 1 })).toEqual(['L0-7']);
    expect(shape({ states: states(4), information: [NaN, NaN, NaN, NaN], belowIc: 0.5, minRun: 1 })).toEqual(['L0-3']);
  });
  it('opens one run and leaves the others folded', () => {
    const spec = base(20, [[2, 6], [10, 15]]);
    expect(shape({ ...spec, expanded: ['2-6'] })).toEqual(['L0-9', 'S10-15', 'L16-19']);
    expect(shape({ ...spec, expanded: ['2-6', '10-15'] })).toEqual(['L0-19']);
    expect(shape({ ...spec, expanded: ['99-100'] })).toEqual(['L0-1', 'S2-6', 'L7-9', 'S10-15', 'L16-19']);
  });
});

describe('planColumns, ranges hidden by hand', () => {
  it('folds the range whatever its length', () => {
    const plan = planColumns({ states: states(10), hidden: [[4, 4]] });
    expect(shape({ states: states(10), hidden: [[4, 4]] })).toEqual(['L0-3', 'S4-4', 'L5-9']);
    expect(plan.segments[1]).toMatchObject({ source: 'manual', count: 1 });
  });
  it('merges ranges that overlap or touch', () => {
    expect(shape({ states: states(12), hidden: [[2, 4], [4, 6], [7, 8]] })).toEqual(['L0-1', 'S2-8', 'L9-11']);
  });
  it('is cut at a window edge', () => {
    const spec = { states: states(20), windowStart: 6, windowEnd: 15 };
    expect(shape({ ...spec, hidden: [[2, 7]] })).toEqual(['S5-7', 'L8-14']);
    expect(shape({ ...spec, hidden: [[12, 18]] })).toEqual(['L5-11', 'S12-14']);
    expect(shape({ ...spec, hidden: [[0, 3]] })).toEqual(['L5-14']);
  });
  it('wins over an automatic run it overlaps', () => {
    const spec: CollapseSpec = {
      states: states(14),
      information: info(14, [[2, 11]]),
      belowIc: 0.5,
      minRun: 4,
      hidden: [[5, 7]],
    };
    // The run is broken at the hidden range: 2-4 is too short, 8-11 folds.
    expect(shape(spec)).toEqual(['L0-4', 'S5-7', 'S8-11', 'L12-13']);
    expect(planColumns(spec).segments.map((s) => (s.kind === 'stub' ? s.source : '-'))).toEqual(['-', 'manual', 'auto', '-']);
  });
});

describe('placeColumns and the mapping', () => {
  const spec: CollapseSpec = { states: states(20), information: info(20, [[5, 10]]), belowIc: 0.5, minRun: 4 };
  const layout = placeColumns(planColumns(spec), 10);

  it('places letters at the state width and a stub at its own', () => {
    expect(layout.segments.map((s) => [s.kind, s.x, s.w])).toEqual([
      ['states', 0, 50],
      ['stub', 50, STUB_PX],
      ['states', 50 + STUB_PX, 90],
    ]);
    expect(layout.width).toBe(50 + STUB_PX + 90);
  });
  it('keeps the stub width when the state width changes', () => {
    const wide = placeColumns(planColumns(spec), 30);
    expect(wide.segments[1].w).toBe(STUB_PX);
    expect(wide.width).toBe(5 * 30 + STUB_PX + 9 * 30);
  });
  it('maps a column to its left edge', () => {
    expect(xOfIndex(layout, 0)).toBe(0);
    expect(xOfIndex(layout, 4)).toBe(40);
    expect(xOfIndex(layout, 5)).toBe(50);
    expect(xOfIndex(layout, 10)).toBe(50);
    expect(xOfIndex(layout, 11)).toBe(50 + STUB_PX);
    expect(xOfIndex(layout, 19)).toBe(50 + STUB_PX + 80);
    expect(xOfIndex(layout, 20)).toBeNull();
    expect(segmentOfIndex(layout, 7)?.kind).toBe('stub');
  });
  it('inverts the mapping', () => {
    for (const i of [0, 3, 4, 11, 15, 19]) {
      const x = xOfIndex(layout, i)!;
      expect(indexAtX(layout, x + 1)?.index).toBe(i);
    }
    expect(indexAtX(layout, 49.9)?.index).toBe(4);
    const over = indexAtX(layout, 55);
    expect(over?.segment.kind).toBe('stub');
    expect(over?.index).toBe(5);
    expect(indexAtX(layout, -1)).toBeNull();
    expect(indexAtX(layout, layout.width)).toBeNull();
  });
  it('spans columns across a stub, whole stubs at the ends', () => {
    expect(spanOfIndices(layout, 3, 12)).toEqual({ x0: 30, x1: 50 + STUB_PX + 20, clippedStart: false, clippedEnd: false });
    expect(spanOfIndices(layout, 12, 3)).toEqual(spanOfIndices(layout, 3, 12));
    // A span that starts inside a stub starts at the stub's edge, and ends at its far edge.
    expect(spanOfIndices(layout, 7, 7)).toEqual({ x0: 50, x1: 50 + STUB_PX, clippedStart: false, clippedEnd: false });
  });
  it('cuts a span to the window', () => {
    const windowed = placeColumns(planColumns({ states: states(20), windowStart: 5, windowEnd: 10 }), 10);
    expect(spanOfIndices(windowed, 0, 6)).toEqual({ x0: 0, x1: 30, clippedStart: true, clippedEnd: false });
    expect(spanOfIndices(windowed, 8, 19)).toEqual({ x0: 40, x1: 60, clippedStart: false, clippedEnd: true });
    expect(spanOfIndices(windowed, 0, 3)).toBeNull();
    expect(spanOfIndices(windowed, 12, 19)).toBeNull();
    expect(xOfIndex(windowed, 4)).toBe(0);
    expect(xOfIndex(windowed, 3)).toBeNull();
  });
  it('brushes the hidden columns under a stub', () => {
    // Letters 2 to 3 into the stub: the stub is covered whole.
    expect(extentAtX(layout, 25, 55)).toEqual([2, 10]);
    // From inside the stub to a letter after it.
    expect(extentAtX(layout, 55, 100)).toEqual([5, 14]);
    // Across it.
    expect(extentAtX(layout, 25, 100)).toEqual([2, 14]);
    // Any direction, clamped to the grid.
    expect(extentAtX(layout, 100, -20)).toEqual([0, 14]);
    expect(extentAtX(layout, 25, 9999)).toEqual([2, 19]);
    // A click on a letter is one column.
    expect(extentAtX(layout, 33, 33)).toEqual([3, 3]);
  });
  it('lists what the viewport shows', () => {
    expect(visibleSegments(layout, 0, 40).map((s) => s.kind)).toEqual(['states']);
    expect(visibleSegments(layout, 45, 30).map((s) => s.kind)).toEqual(['states', 'stub', 'states']);
    const second = layout.segments[2];
    if (second.kind !== 'states') throw new Error('expected letters');
    expect(columnsInView(layout, second, 0, 10_000)).toEqual([11, 19]);
    expect(columnsInView(layout, second, 50 + STUB_PX + 25, 20, 0)).toEqual([13, 15]);
  });
});

describe('addHidden and expandStub', () => {
  it('merges ranges that overlap or touch, in order', () => {
    expect(addHidden([[2, 4]], [9, 7])).toEqual([[2, 4], [7, 9]]);
    expect(addHidden([[2, 4], [7, 9]], [5, 6])).toEqual([[2, 9]]);
    expect(addHidden([[6, 8]], [1, 3])).toEqual([[1, 3], [6, 8]]);
  });
  it('opens one automatic run and leaves the rest', () => {
    const spec: CollapseSpec = {
      states: states(20),
      information: info(20, [[2, 6], [10, 15]]),
      belowIc: 0.5,
      minRun: 4,
    };
    const stubs = planColumns(spec).segments.filter((s): s is Omit<StubSegment, 'x' | 'w'> & { kind: 'stub' } => s.kind === 'stub');
    const placed = placeColumns(planColumns(spec), 10).segments.filter((s): s is StubSegment => s.kind === 'stub');
    expect(stubs).toHaveLength(2);
    const next = expandStub({ hidden: [], expanded: [] }, placed[0]);
    expect(next).toEqual({ hidden: [], expanded: ['2-6'] });
    expect(shape({ ...spec, ...next })).toEqual(['L0-9', 'S10-15', 'L16-19']);
    // Opening it twice changes nothing.
    expect(expandStub(next, placed[0])).toBe(next);
  });
  it('opens a hand-hidden range by dropping it', () => {
    const spec: CollapseSpec = { states: states(20), hidden: [[2, 4], [10, 12]] };
    const placed = placeColumns(planColumns(spec), 10).segments.filter((s): s is StubSegment => s.kind === 'stub');
    const next = expandStub({ hidden: spec.hidden!, expanded: [] }, placed[1]);
    expect(next.hidden).toEqual([[2, 4]]);
    expect(shape({ ...spec, hidden: next.hidden })).toEqual(['L0-1', 'S2-4', 'L5-19']);
  });
});
