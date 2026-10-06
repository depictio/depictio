import { describe, expect, it } from 'vitest';

import {
  colourUpsetSets,
  inkUpsetForDark,
  resolveUpsetSetColors,
  upsetColumnSets,
  upsetSetNames,
  withUpsetSetLabelDots,
} from './upsetFigure';

// The shape plotly-upset draws for three sites in the per-set colour mode:
// sets Athens, Barcelona, Naples at y = 0, 1, 2; intersections
// 0 = all three, 1 = Barcelona, 2 = Athens, 3 = Barcelona & Naples.
const layout = {
  yaxis: { title: { text: 'Intersection Size' } },
  yaxis2: { tickvals: [0, 1, 2], ticktext: ['Athens', 'Barcelona', 'Naples'] },
  yaxis3: { tickvals: [0, 1, 2], ticktext: ['Athens', 'Barcelona', 'Naples'], matches: 'y2' },
};
const intersectionBars = {
  type: 'bar',
  name: 'Intersection Size',
  x: [0, 1, 2, 3],
  y: [27, 9, 7, 5],
  marker: { color: ['#7F7F7F', '#E45756', '#4C78A8', '#7F7F7F'] },
};
const emptyDots = {
  type: 'scatter',
  mode: 'markers',
  x: [1, 1, 2, 2, 3],
  y: [0, 2, 1, 2, 0],
  hoverinfo: 'skip',
  marker: { color: '#C2C2C2' },
  xaxis: 'x3',
  yaxis: 'y3',
};
const edge = { type: 'scatter', mode: 'lines', x: [0, 0], y: [0, 2], xaxis: 'x3', yaxis: 'y3' };
const filledDots = {
  type: 'scatter',
  mode: 'markers',
  x: [0, 0, 0, 1, 2, 3, 3],
  y: [0, 1, 2, 1, 0, 1, 2],
  hovertext: ['all', 'all', 'all', 'B', 'A', 'B & N', 'B & N'],
  hoverinfo: 'text',
  marker: { color: '#333333' },
  xaxis: 'x3',
  yaxis: 'y3',
};
const setSizes = {
  type: 'bar',
  orientation: 'h',
  name: 'Set Size',
  x: [39, 44, 36],
  y: [0, 1, 2],
  marker: { color: '#333333' },
  xaxis: 'x2',
  yaxis: 'y2',
};
const figure = [intersectionBars, emptyDots, edge, filledDots, setSizes];

const SITES = { Athens: '#1a4f8f', Barcelona: '#f5a11b', Naples: '#00a550' };
const colorOf = (t: Record<string, unknown>) => (t.marker as { color?: unknown }).color;

describe('reading the figure', () => {
  it('names the sets by row', () => {
    expect(upsetSetNames(layout)).toEqual(['Athens', 'Barcelona', 'Naples']);
  });

  it('places names by tickvals, not by position in the list', () => {
    expect(upsetSetNames({ yaxis2: { tickvals: [1, 0], ticktext: ['B', 'A'] } })).toEqual(['A', 'B']);
  });

  it('lists the sets each intersection joins, from the filled dots only', () => {
    expect(upsetColumnSets(figure, layout)).toEqual(
      new Map([
        [0, ['Athens', 'Barcelona', 'Naples']],
        [1, ['Barcelona']],
        [2, ['Athens']],
        [3, ['Barcelona', 'Naples']],
      ]),
    );
  });
});

describe('resolveUpsetSetColors', () => {
  const dashboard = { inherited_category_colors: { locality: SITES } };

  it('finds the column whose category colours pin every set', () => {
    expect(resolveUpsetSetColors(dashboard, ['Athens', 'Barcelona', 'Naples'])).toEqual(SITES);
  });

  it('reads the dashboard own colours before the inherited ones', () => {
    const own = { ...dashboard, category_colors: { locality: { Athens: '#000000' } } };
    expect(resolveUpsetSetColors(own, ['Athens', 'Naples'], { column: 'locality' })).toEqual({
      Athens: '#000000',
      Naples: '#00a550',
    });
  });

  it('keeps the plain look when no column colours the sets', () => {
    expect(resolveUpsetSetColors(null, ['Athens'])).toBeNull();
    expect(resolveUpsetSetColors({ category_colors: { season: { Summer: '#f00' } } }, ['Athens'])).toBeNull();
  });

  it('does not guess between columns that colour the same sets differently', () => {
    const two = { category_colors: { locality: SITES, city: { ...SITES, Athens: '#ffffff' } } };
    expect(resolveUpsetSetColors(two, ['Athens', 'Naples'])).toBeNull();
    expect(resolveUpsetSetColors(two, ['Athens', 'Naples'], { column: 'city' })).toEqual({
      Athens: '#ffffff',
      Naples: '#00a550',
    });
  });

  it('needs every set pinned to find the column by value, not with it named', () => {
    const sets = ['Athens', 'Rome'];
    expect(resolveUpsetSetColors(dashboard, sets)).toBeNull();
    expect(resolveUpsetSetColors(dashboard, sets, { column: 'locality' })).toEqual({ Athens: '#1a4f8f' });
  });

  it('lets the component set_colors win per set', () => {
    expect(
      resolveUpsetSetColors(dashboard, ['Athens', 'Naples'], { overrides: { Naples: '#123456' } }),
    ).toEqual({ Athens: '#1a4f8f', Naples: '#123456' });
  });
});

describe('colourUpsetSets', () => {
  const [bars, empty, line, filled, sizes] = colourUpsetSets(figure, layout, SITES);

  it('colours each set size bar and each filled dot by its set', () => {
    expect(colorOf(sizes)).toEqual(['#1a4f8f', '#f5a11b', '#00a550']);
    expect(colorOf(filled)).toEqual(['#1a4f8f', '#f5a11b', '#00a550', '#f5a11b', '#1a4f8f', '#f5a11b', '#00a550']);
  });

  it('gives a single-set bar its set colour and leaves shared bars neutral', () => {
    expect(colorOf(bars)).toEqual(['#7F7F7F', '#f5a11b', '#1a4f8f', '#7F7F7F']);
  });

  it('leaves the empty dots and the edges alone', () => {
    expect(empty).toBe(emptyDots);
    expect(line).toBe(edge);
  });

  it('keeps a set with no colour as it was drawn', () => {
    const [, , , dots, size] = colourUpsetSets(figure, layout, { Naples: '#00a550' });
    expect(colorOf(size)).toEqual(['#333333', '#333333', '#00a550']);
    expect(colorOf(dots)).toEqual(['#333333', '#333333', '#00a550', '#333333', '#333333', '#333333', '#00a550']);
  });

  it('leaves the single colour and the degree colouring to the author', () => {
    const single = { ...intersectionBars, marker: { color: '#333333' } };
    const degree = { type: 'bar', name: '1', x: [1, 2], y: [9, 7], marker: { color: '#72B7B2' } };
    const [one, two] = colourUpsetSets([single, degree, filledDots], layout, SITES);
    expect(one).toBe(single);
    expect(two).toBe(degree);
  });

  it('returns the figure unchanged without colours, and never mutates it', () => {
    expect(colourUpsetSets(figure, layout, null)).toBe(figure);
    expect(setSizes.marker.color).toBe('#333333');
    expect(intersectionBars.marker.color).toEqual(['#7F7F7F', '#E45756', '#4C78A8', '#7F7F7F']);
  });
});

describe('withUpsetSetLabelDots', () => {
  it('puts a dot of the set colour before each coloured set name', () => {
    const out = withUpsetSetLabelDots(layout, { Athens: '#1a4f8f' });
    expect((out.yaxis2 as { ticktext: string[] }).ticktext).toEqual([
      '<span style="color:#1a4f8f">●</span> Athens',
      'Barcelona',
      'Naples',
    ]);
    expect((out.yaxis3 as { matches: string }).matches).toBe('y2');
    expect(out.yaxis).toBe(layout.yaxis);
    expect(layout.yaxis2.ticktext[0]).toBe('Athens');
  });

  it('leaves the layout alone without colours', () => {
    expect(withUpsetSetLabelDots(layout, null)).toBe(layout);
  });
});

describe('inkUpsetForDark', () => {
  const ink = { ink: '#ced4da', empty: '#424242' };
  const colouredEdge = { ...edge, line: { color: '#333333', width: 2 } };
  const [bars, empty, line, filled, sizes] = inkUpsetForDark(
    [intersectionBars, emptyDots, colouredEdge, filledDots, setSizes],
    layout,
    ink,
  );

  it('dims the empty dots and lights up the plain ink', () => {
    expect(colorOf(empty)).toBe('#424242');
    expect(colorOf(filled)).toBe('#ced4da');
    expect(colorOf(sizes)).toBe('#ced4da');
    expect((line.line as { color: string }).color).toBe('#ced4da');
  });

  it('keeps the colours the figure was given on purpose', () => {
    expect(bars).toBe(intersectionBars);
    const [setBars] = inkUpsetForDark([{ ...setSizes, marker: { color: ['#333333', '#f5a11b'] } }], layout, ink);
    expect(colorOf(setBars)).toEqual(['#ced4da', '#f5a11b']);
  });
});
