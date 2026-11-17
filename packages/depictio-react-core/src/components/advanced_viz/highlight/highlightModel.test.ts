import { describe, expect, it } from 'vitest';

import {
  EMPTY_HIGHLIGHT,
  isAdditiveClick,
  reduceHighlight,
  sameKeys,
  selectionFromClick,
} from './highlightModel';

describe('reduceHighlight', () => {
  it('sets the keys, deduplicated and without blanks', () => {
    const s = reduceHighlight(EMPTY_HIGHLIGHT, {
      type: 'set',
      keys: ['a', 'b', 'a', ''],
      source: 'plot-select',
    });
    expect(s.keys).toEqual(['a', 'b']);
    expect(s.source).toBe('plot-select');
  });

  it('returns the same state for an echo of the same set, in any order', () => {
    const s = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'set', keys: ['a', 'b'], source: 'plot-select' });
    expect(reduceHighlight(s, { type: 'set', keys: ['b', 'a'], source: 'table' })).toBe(s);
  });

  it('keeps Plotly its own selection after a box or lasso, and resets it otherwise', () => {
    const lasso = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'set', keys: ['a'], source: 'plot-select' });
    expect(lasso.revision).toBe(0);
    const click = reduceHighlight(lasso, { type: 'set', keys: ['b'], source: 'plot-click' });
    expect(click.revision).toBe(1);
    const table = reduceHighlight(click, { type: 'set', keys: ['c'], source: 'table' });
    expect(table.revision).toBe(2);
    const cleared = reduceHighlight(table, { type: 'clear', source: 'external' });
    expect(cleared.keys).toEqual([]);
    expect(cleared.revision).toBe(3);
  });

  it('asks the table to scroll only for a pick made in the plot', () => {
    const plot = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'set', keys: ['a'], source: 'plot-click' });
    expect(plot.reveal).toBe(1);
    const table = reduceHighlight(plot, { type: 'set', keys: ['a', 'b'], source: 'table' });
    expect(table.reveal).toBe(1);
    const emptied = reduceHighlight(table, { type: 'clear', source: 'plot-select' });
    expect(emptied.reveal).toBe(1);
  });

  it('toggles one key', () => {
    const on = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'toggle', key: 'a', source: 'table' });
    expect(on.keys).toEqual(['a']);
    const off = reduceHighlight(on, { type: 'toggle', key: 'a', source: 'table' });
    expect(off.keys).toEqual([]);
    expect(reduceHighlight(off, { type: 'toggle', key: '', source: 'table' })).toBe(off);
  });

  it('clearing nothing changes nothing', () => {
    expect(reduceHighlight(EMPTY_HIGHLIGHT, { type: 'clear', source: 'external' })).toBe(EMPTY_HIGHLIGHT);
  });
});

describe('selectionFromClick', () => {
  it('a plain click picks that point alone, a second click lets go', () => {
    expect(selectionFromClick(['a', 'b'], 'c', false)).toEqual(['c']);
    expect(selectionFromClick(['c'], 'c', false)).toEqual([]);
    expect(selectionFromClick(['c', 'd'], 'c', false)).toEqual(['c']);
  });

  it('a modified click adds or removes', () => {
    expect(selectionFromClick(['a'], 'b', true)).toEqual(['a', 'b']);
    expect(selectionFromClick(['a', 'b'], 'a', true)).toEqual(['b']);
  });

  it('ignores a point with no id', () => {
    expect(selectionFromClick(['a'], '', false)).toEqual(['a']);
  });
});

describe('helpers', () => {
  it('compares key sets without order', () => {
    expect(sameKeys(['a', 'b'], ['b', 'a'])).toBe(true);
    expect(sameKeys(['a'], ['a', 'b'])).toBe(false);
  });

  it('reads the modifier keys of a Plotly click', () => {
    expect(isAdditiveClick({ event: { shiftKey: true } })).toBe(true);
    expect(isAdditiveClick({ event: { metaKey: true } })).toBe(true);
    expect(isAdditiveClick({ event: {} })).toBe(false);
    expect(isAdditiveClick(null)).toBe(false);
  });
});

describe('hover', () => {
  it('records the hovered key and its surface without touching the selection', () => {
    const picked = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'set', keys: ['a'], source: 'table' });
    const s = reduceHighlight(picked, { type: 'hover', key: 'b', source: 'plot' });
    expect(s.hover).toBe('b');
    expect(s.hoverSource).toBe('plot');
    expect(s.keys).toEqual(['a']);
    expect(s.revision).toBe(picked.revision);
  });

  it('lets only the surface that set the hover clear it', () => {
    const s = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'hover', key: 'b', source: 'table' });
    expect(reduceHighlight(s, { type: 'hover', key: null, source: 'plot' })).toBe(s);
    expect(reduceHighlight(s, { type: 'hover', key: null, source: 'table' }).hover).toBeNull();
  });

  it('keeps the same state for a repeated hover', () => {
    const s = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'hover', key: 'b', source: 'table' });
    expect(reduceHighlight(s, { type: 'hover', key: 'b', source: 'table' })).toBe(s);
  });

  it('keeps the hover when the selection changes', () => {
    const s = reduceHighlight(EMPTY_HIGHLIGHT, { type: 'hover', key: 'b', source: 'table' });
    expect(reduceHighlight(s, { type: 'set', keys: ['c'], source: 'plot-click' }).hover).toBe('b');
  });
});
