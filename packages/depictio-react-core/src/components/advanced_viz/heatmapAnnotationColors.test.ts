import { describe, expect, it } from 'vitest';

import { annotationStripCategories, recolourAnnotationStrips } from './heatmapAnnotationColors';

/** A strip as plotly-complexheatmap emits it: a block per split plus legend entries. */
function strip(name: string, cats: string[], colours: string[]) {
  const n = cats.length;
  const block = {
    type: 'heatmap',
    hovertemplate: `${name}: %{customdata}<extra></extra>`,
    colorscale: colours.flatMap((c, i) => [
      [i / n, c],
      [(i + 1) / n, c],
    ]),
    zmin: -0.5,
    zmax: n - 0.5,
  };
  const legend = cats.map((cat, i) => ({
    type: 'scatter',
    x: [null],
    y: [null],
    name: `${name}: ${cat}`,
    legendgroup: name,
    marker: { size: 10, color: colours[i], symbol: 'square' },
  }));
  return { block, legend };
}

const condition = strip('condition', ['control', 'treated'], ['#66c2a5', '#fc8d62']);
const batch = strip('batch', ['b1', 'b2'], ['#1b9e77', '#d95f02']);
const matrix = {
  type: 'heatmap',
  hovertemplate: 'row: %{customdata[0]}<br>col: %{customdata[1]}<br>value: %{z:.3f}<extra></extra>',
  colorscale: 'RdBu',
};
const data = [matrix, condition.block, condition.block, batch.block, ...condition.legend, ...batch.legend];

describe('annotationStripCategories', () => {
  it('reads each strip’s categories in band order off its legend', () => {
    expect(Object.fromEntries(annotationStripCategories(data))).toEqual({
      condition: ['control', 'treated'],
      batch: ['b1', 'b2'],
    });
  });
});

describe('recolourAnnotationStrips', () => {
  it('gives the pinned values their colour in every block and in the legend', () => {
    const out = recolourAnnotationStrips(data, (s) => (s === 'condition' ? { treated: '#e8590c' } : null));
    const blocks = out.filter((t) => t.hovertemplate === 'condition: %{customdata}<extra></extra>');
    expect(blocks).toHaveLength(2);
    for (const b of blocks) {
      expect(b.colorscale).toEqual([
        [0, '#66c2a5'],
        [0.5, '#66c2a5'],
        [0.5, '#e8590c'],
        [1, '#e8590c'],
      ]);
    }
    const swatches = out.filter((t) => t.legendgroup === 'condition').map((t) => (t.marker as any).color);
    expect(swatches).toEqual(['#66c2a5', '#e8590c']);
  });

  it('leaves the matrix, the strips nothing pins and the input alone', () => {
    const out = recolourAnnotationStrips(data, (s) => (s === 'condition' ? { treated: '#e8590c' } : null));
    expect(out[0]).toBe(matrix);
    expect(out.find((t) => t.hovertemplate === 'batch: %{customdata}<extra></extra>')).toBe(batch.block);
    expect((condition.block.colorscale[2] as [number, string])[1]).toBe('#fc8d62');
  });

  it('leaves a strip alone when its bands do not match its legend', () => {
    const odd = { ...condition.block, colorscale: [[0, '#000000'], [1, '#000000']] };
    const out = recolourAnnotationStrips([odd, ...condition.legend], () => ({ treated: '#e8590c' }));
    expect(out[0]).toBe(odd);
  });
});
