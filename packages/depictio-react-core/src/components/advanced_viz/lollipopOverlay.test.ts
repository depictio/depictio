import { describe, expect, it } from 'vitest';

import { residueOverlay, type LollipopLane, type LollipopStem } from './lollipopOverlay';

const lanes: LollipopLane[] = [
  { gene: 'A', yref: 'y', domain: [0.54, 1] },
  { gene: 'B', yref: 'y2', domain: [0.04, 0.5] },
];
const stems: LollipopStem[] = [
  { gene: 'A', position: 10, height: 2, row: 0 },
  { gene: 'A', position: 40, height: 1, row: 1 },
  { gene: 'B', position: 12, height: 3, row: 2 },
];
const base = { lanes, stems, positionColumn: 'position', pointSize: 8 };

describe('residueOverlay', () => {
  it('draws nothing without a pick or a hover', () => {
    expect(residueOverlay({ ...base, picked: null, highlight: null })).toEqual({
      shapes: [],
      rings: [],
    });
  });

  it('shades the picked range on the picked lane and rings its stems', () => {
    const out = residueOverlay({
      ...base,
      picked: { entity: 'A', start: 5, end: 15 },
      highlight: null,
    });
    expect(out.shapes).toEqual([{ kind: 'band', x0: 4.5, x1: 15.5, y0: 0.54, y1: 1 }]);
    expect(out.rings).toEqual([{ yref: 'y', x: [10], y: [2], size: 16 }]);
  });

  it('applies a pick with no entity to every lane', () => {
    const out = residueOverlay({
      ...base,
      picked: { entity: null, start: 12, end: 12 },
      highlight: null,
    });
    expect(out.shapes).toHaveLength(2);
    expect(out.rings).toEqual([{ yref: 'y2', x: [12], y: [3], size: 16 }]);
  });

  it('draws the hovered residue as a line on matching lanes only', () => {
    const out = residueOverlay({
      ...base,
      picked: null,
      highlight: { sourceIndex: 'mol', entity: 'B', start: 7, end: 9 },
    });
    expect(out.shapes).toEqual([
      { kind: 'line', x0: 7, x1: 7, y0: 0.04, y1: 0.5 },
      { kind: 'line', x0: 9, x1: 9, y0: 0.04, y1: 0.5 },
    ]);
  });

  it('ignores a hover on another axis', () => {
    const out = residueOverlay({
      ...base,
      picked: null,
      highlight: { sourceIndex: 'p', start: 7, positionColumn: 'distance_to_tss' },
    });
    expect(out.shapes).toEqual([]);
  });
});
