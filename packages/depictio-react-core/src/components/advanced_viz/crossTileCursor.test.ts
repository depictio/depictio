import { describe, expect, it } from 'vitest';

import type { HighlightEvent } from '../../highlight/bus';
import type { ViewWindowEvent } from '../../highlight/viewWindow';
import {
  cursorShape,
  eventSpan,
  hoveredColor,
  hoverRingShape,
  hoverShape,
  matchChromosome,
  pickRange,
  windowRange,
  windowBandShape,
  withCursorShape,
} from './crossTileCursor';

const ev = (over: Partial<HighlightEvent>): HighlightEvent => ({
  sourceIndex: 'jb',
  entity: 'chr2',
  start: 100,
  ...over,
});

describe('matchChromosome', () => {
  it('matches exactly, then ignoring the chr prefix and the case', () => {
    expect(matchChromosome('chr2', ['chr1', 'chr2'])).toBe('chr2');
    expect(matchChromosome('2', ['chr1', 'chr2'])).toBe('chr2');
    expect(matchChromosome('Chr2', ['1', '2'])).toBe('2');
  });

  it('prefers the exact spelling when both exist', () => {
    expect(matchChromosome('2', ['chr2', '2'])).toBe('2');
  });

  it('matches an alias when the canonical name is absent', () => {
    const chroms = ['MN908947.3'];
    expect(matchChromosome('NC_045512v2', chroms)).toBeNull();
    expect(matchChromosome('NC_045512v2', chroms, ['NC_045512.2', 'MN908947.3'])).toBe(
      'MN908947.3',
    );
  });

  it('keeps the case and chr-prefix tolerance for aliases, and prefers the entity', () => {
    expect(matchChromosome('NC_1', ['2', '1'], ['chr1'])).toBe('1');
    expect(matchChromosome('b', ['a', 'b'], ['a'])).toBe('b');
    // An exact alias beats a tolerant match of the entity.
    expect(matchChromosome('chr2', ['2', 'chr1'], ['chr1'])).toBe('chr1');
    expect(matchChromosome('x', ['chr1'], ['chr1', 'chr2'])).toBe('chr1');
  });

  it('matches nothing for a protein entity, an empty one or an unknown contig', () => {
    expect(matchChromosome('P04637', ['chr1'])).toBeNull();
    expect(matchChromosome(undefined, ['chr1'])).toBeNull();
    expect(matchChromosome('chr', ['chr1'])).toBeNull();
    expect(matchChromosome('chr3', ['chr1', 'chr2'])).toBeNull();
  });
});

describe('eventSpan', () => {
  it('orders the ends and defaults the end to the start', () => {
    expect(eventSpan(ev({ start: 5, end: 3 }))).toEqual({ start: 3, end: 5 });
    expect(eventSpan(ev({ start: 5 }))).toEqual({ start: 5, end: 5 });
  });

  it('is null for no event or a non-finite position', () => {
    expect(eventSpan(null)).toBeNull();
    expect(eventSpan(ev({ start: Number.NaN }))).toBeNull();
  });
});

describe('cursorShape', () => {
  it('is a vertical line for one position, in the given colour', () => {
    expect(cursorShape(10, 10, '#f00')).toMatchObject({
      type: 'line',
      x0: 10,
      x1: 10,
      yref: 'paper',
      line: { color: '#f00' },
    });
  });

  it('is a band for a span', () => {
    expect(cursorShape(10, 20, '#00f')).toMatchObject({
      type: 'rect',
      x0: 10,
      x1: 20,
      fillcolor: '#00f',
    });
  });
});

describe('withCursorShape', () => {
  it('appends to the layout shapes without touching the original', () => {
    const layout = { shapes: [{ type: 'rect' }], title: 't' };
    const shape = cursorShape(1, 1, '#000');
    const out = withCursorShape(layout, shape);
    expect(out.shapes).toEqual([{ type: 'rect' }, shape]);
    expect(layout.shapes).toHaveLength(1);
  });

  it('works on a layout without shapes and returns the same one for no shape', () => {
    const layout = { title: 't' } as Record<string, unknown>;
    expect(withCursorShape(layout, cursorShape(1, 1, '#000')).shapes).toHaveLength(1);
    expect(withCursorShape(layout, null)).toBe(layout);
  });
});

describe('hoverShape', () => {
  const offsets = new Map([
    ['chr1', 0],
    ['chr2', 1000],
  ]);

  it('moves the position onto the cumulative axis through the contig offset', () => {
    expect(hoverShape(ev({ start: 50 }), offsets, '#theme')).toMatchObject({
      type: 'line',
      x0: 1050,
    });
  });

  it('draws a span as a band', () => {
    expect(hoverShape(ev({ start: 50, end: 80 }), offsets, '#theme')).toMatchObject({
      type: 'rect',
      x0: 1050,
      x1: 1080,
    });
  });

  it('wears the hovered mark colour over the theme one', () => {
    expect(hoverShape(ev({ color: '#abc' }), offsets, '#theme')).toMatchObject({
      line: { color: '#abc' },
    });
    expect(hoverShape(ev({}), offsets, '#theme')).toMatchObject({ line: { color: '#theme' } });
    const band = hoverShape(ev({ end: 200, color: '#abc' }), offsets, '#theme');
    expect(band).toMatchObject({ fillcolor: '#abc' });
  });

  it('finds the contig through the browser aliases', () => {
    const viral = new Map([['MN908947.3', 0]]);
    const event = ev({ entity: 'NC_045512v2', entityAliases: ['MN908947.3'], start: 7 });
    expect(hoverShape(event, viral, '#theme')).toMatchObject({ type: 'line', x0: 7 });
    expect(hoverShape(ev({ entity: 'NC_045512v2' }), viral, '#theme')).toBeNull();
  });

  it('ignores a contig the plot does not draw, and no event', () => {
    expect(hoverShape(ev({ entity: 'chr9' }), offsets, '#theme')).toBeNull();
    expect(hoverShape(ev({ entity: 'P04637' }), offsets, '#theme')).toBeNull();
    expect(hoverShape(null, offsets, '#theme')).toBeNull();
  });
});

describe('windowRange', () => {
  const win = (over: Partial<ViewWindowEvent>): ViewWindowEvent => ({
    sourceIndex: 'jb',
    entity: 'NC_1',
    start: 100,
    end: 900,
    ...over,
  });

  it('is the window when it is on a shown contig', () => {
    expect(windowRange(win({}), ['NC_1'])).toEqual([100, 900]);
  });

  it('is the window when only an alias of its contig is shown', () => {
    expect(windowRange(win({ entity: 'NC_045512v2', entityAliases: ['NC_1'] }), ['NC_1'])).toEqual([
      100, 900,
    ]);
  });

  it('is null off the shown contigs, empty, or without extent', () => {
    expect(windowRange(win({ entity: 'NC_2' }), ['NC_1'])).toBeNull();
    expect(windowRange(win({ end: 100 }), ['NC_1'])).toBeNull();
    expect(windowRange(null, ['NC_1'])).toBeNull();
  });
});

describe('pickRange', () => {
  const f: [number, number] = [1, 2];
  const w: [number, number] = [3, 4];

  it('takes the one that exists', () => {
    expect(pickRange('filter', f, null)).toBe(f);
    expect(pickRange('filter', null, w)).toBe(w);
    expect(pickRange('window', null, null)).toBeNull();
  });

  it('takes the most recent when both exist', () => {
    expect(pickRange('filter', f, w)).toBe(f);
    expect(pickRange('window', f, w)).toBe(w);
  });
});

describe('hoveredColor', () => {
  it('reads the per-point marker colour at the hovered point', () => {
    const point = { pointNumber: 1, data: { marker: { color: ['#a', '#b', '#c'] } } };
    expect(hoveredColor(point)).toBe('#b');
  });

  it('reads a single marker colour, then the line colour', () => {
    expect(hoveredColor({ pointNumber: 4, data: { marker: { color: '#m' } } })).toBe('#m');
    expect(hoveredColor({ pointNumber: 4, data: { line: { color: '#l' } } })).toBe('#l');
  });

  it('falls back to the resolved trace', () => {
    expect(hoveredColor({ pointIndex: 0, fullData: { marker: { color: ['#f'] } } })).toBe('#f');
  });

  it('is undefined for a numeric colour array or nothing', () => {
    expect(hoveredColor({ pointNumber: 0, data: { marker: { color: [1, 2] } } })).toBeUndefined();
    expect(hoveredColor({ pointNumber: 9, data: { marker: { color: ['#a'] } } })).toBeUndefined();
    expect(hoveredColor(null)).toBeUndefined();
    expect(hoveredColor({})).toBeUndefined();
  });
});

describe('windowBandShape', () => {
  const offsets = new Map([
    ['chr1', 0],
    ['chr2', 1000],
  ]);
  const win = (over: Partial<ViewWindowEvent>): ViewWindowEvent => ({
    sourceIndex: 'jb',
    entity: 'chr2',
    start: 100,
    end: 400,
    ...over,
  });

  it('spans the window through the contig offset, behind the points', () => {
    expect(windowBandShape(win({}), offsets, '#theme')).toMatchObject({
      type: 'rect',
      x0: 1100,
      x1: 1400,
      yref: 'paper',
      fillcolor: '#theme',
      layer: 'below',
    });
  });

  it('finds the contig through the browser aliases', () => {
    const viral = new Map([['MN908947.3', 0]]);
    const w = win({ entity: 'NC_045512v2', entityAliases: ['MN908947.3'] });
    expect(windowBandShape(w, viral, '#theme')).toMatchObject({ x0: 100, x1: 400 });
    expect(windowBandShape(win({ entity: 'NC_045512v2' }), viral, '#theme')).toBeNull();
  });

  it('is null for no window, an undrawn contig or an empty extent', () => {
    expect(windowBandShape(null, offsets, '#theme')).toBeNull();
    expect(windowBandShape(win({ entity: 'chr9' }), offsets, '#theme')).toBeNull();
    expect(windowBandShape(win({ end: 100 }), offsets, '#theme')).toBeNull();
    expect(windowBandShape(win({ start: Number.NaN }), offsets, '#theme')).toBeNull();
  });
});

describe('hoverRingShape', () => {
  it('is a pixel-sized circle anchored on the data point', () => {
    expect(hoverRingShape(120, 3.5, 'teal', 8)).toMatchObject({
      type: 'circle',
      xsizemode: 'pixel',
      ysizemode: 'pixel',
      xanchor: 120,
      yanchor: 3.5,
      x0: -8,
      x1: 8,
      line: { color: 'teal' },
    });
  });
});
