import { describe, expect, it } from 'vitest';

import { applyHighlight, highlightLayout, MAX_HIGHLIGHT_RINGS, selectedIndices } from './highlightTraces';

const paint = { slot: 1, ringColor: '#123456' };

const volcano = () => ({
  type: 'scattergl',
  x: [1, 2, 3, 4],
  y: [10, 20, 30, 40],
  customdata: [
    ['LabelA', 'g1'],
    ['LabelB', 'g2'],
    ['LabelC', 'g3'],
    ['LabelD', 'g4'],
  ],
});

describe('selectedIndices', () => {
  it('finds the points whose id sits at the slot', () => {
    expect(selectedIndices(volcano(), new Set(['g2', 'g4']), 1)).toEqual([1, 3]);
  });

  it('is null for a trace with no customdata or no id at the slot', () => {
    expect(selectedIndices({ x: [1] }, new Set(['g1']), 1)).toBeNull();
    expect(selectedIndices({ customdata: [['a'], ['b']] }, new Set(['a']), 1)).toBeNull();
  });

  it('reads an object-shaped customdata entry', () => {
    expect(selectedIndices({ customdata: [{ 1: 'k' }] }, new Set(['k']), 1)).toEqual([0]);
  });
});

describe('applyHighlight', () => {
  it('returns the traces untouched when nothing is picked', () => {
    const data = [volcano()];
    expect(applyHighlight(data, [], paint)).toBe(data);
  });

  it('selects the picked points, dims the rest and rings the picked ones', () => {
    const out = applyHighlight([volcano()], ['g2', 'g3'], paint) as Record<string, any>[];
    expect(out).toHaveLength(2);
    expect(out[0].selectedpoints).toEqual([1, 2]);
    expect(out[0].unselected.marker.opacity).toBeLessThan(1);
    expect(out[0].selected.marker.opacity).toBe(1);
    expect(out[1]).toMatchObject({ x: [2, 3], y: [20, 30], hoverinfo: 'skip', showlegend: false });
    expect(out[1].marker.color).toBe('#123456');
  });

  it('does not mutate the input trace', () => {
    const trace = volcano();
    applyHighlight([trace], ['g1'], paint);
    expect('selectedpoints' in trace).toBe(false);
  });

  it('leaves traces without ids alone and adds no ring when none is keyed', () => {
    const guide = { type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1] };
    const data = [guide];
    expect(applyHighlight(data, ['g1'], paint)).toBe(data);
  });

  it('dims a keyed trace with no picked point entirely', () => {
    const out = applyHighlight([volcano()], ['absent'], paint) as Record<string, any>[];
    expect(out[0].selectedpoints).toEqual([]);
    expect(out).toHaveLength(1);
  });

  it('caps the rings', () => {
    const n = MAX_HIGHLIGHT_RINGS + 50;
    const trace = {
      x: Array.from({ length: n }, (_, i) => i),
      y: Array.from({ length: n }, (_, i) => i),
      customdata: Array.from({ length: n }, (_, i) => [`id${i}`]),
    };
    const keys = Array.from({ length: n }, (_, i) => `id${i}`);
    const out = applyHighlight([trace], keys, { slot: 0, ringColor: 'red' }) as Record<string, any>[];
    expect(out[0].selectedpoints).toHaveLength(n);
    expect(out[1].x).toHaveLength(MAX_HIGHLIGHT_RINGS);
  });

  it('passes a null figure through', () => {
    expect(applyHighlight(null, ['a'], paint)).toBeNull();
  });
});

describe('highlightLayout', () => {
  it('folds the revision into selectionrevision and defaults the uirevision', () => {
    const out = highlightLayout({ title: 'x' }, 2, 'view-a');
    expect(out.uirevision).toBe('view-a');
    expect(out.selectionrevision).toBe('view-a|h2');
    expect(out.title).toBe('x');
  });

  it('keeps a layout\'s own revisions as the base', () => {
    const out = highlightLayout({ uirevision: 'u', selectionrevision: 'sel-3' }, 1, 'ignored');
    expect(out.uirevision).toBe('u');
    expect(out.selectionrevision).toBe('sel-3|h1');
  });
});

describe('applyHighlight hover ring', () => {
  it('rings the hovered point without dimming the others', () => {
    const out = applyHighlight([volcano()], [], { ...paint, hoverKey: 'g3' }) as Record<string, unknown>[];
    expect(out).toHaveLength(2);
    expect(out[0]).not.toHaveProperty('selectedpoints');
    expect(out[1]).toMatchObject({ name: 'hover', x: [3], y: [30] });
  });

  it('adds nothing for a key no trace holds', () => {
    const data = [volcano()];
    expect(applyHighlight(data, [], { ...paint, hoverKey: 'nope' })).toBe(data);
  });
});
