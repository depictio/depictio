import { describe, expect, it } from 'vitest';
import {
  AXIS_LINE_WIDTH,
  autoMarker,
  embeddingAxisLayout,
  embeddingFamily,
  reassertAxisLines,
} from './embeddingAxisStyle';

const colors = { axis: '#444', grid: 'rgba(0,0,0,0.08)', text: '#222' };

describe('embeddingFamily', () => {
  it('follows the live method', () => {
    expect(embeddingFamily({}, 'umap')).toBe('neighbour');
    expect(embeddingFamily({}, 'tsne')).toBe('neighbour');
    expect(embeddingFamily({}, 'pca')).toBe('linear');
    expect(embeddingFamily({}, 'pcoa')).toBe('linear');
  });

  it('reads the prefix or column names in precomputed mode', () => {
    expect(embeddingFamily({ dim_1_col: 'UMAP_1', dim_2_col: 'UMAP_2' })).toBe('neighbour');
    expect(embeddingFamily({ axis_prefix: 't-SNE ' })).toBe('neighbour');
    expect(embeddingFamily({ dim_1_col: 'PC1', dim_2_col: 'PC2' })).toBe('linear');
    expect(embeddingFamily({ dim_1_col: 'dim_1', dim_2_col: 'dim_2' })).toBe('linear');
  });
});

describe('embeddingAxisLayout', () => {
  it('draws bold axes with an arrow on each, and keeps PCA tick labels', () => {
    const l = embeddingAxisLayout({ style: 'default', family: 'linear', titles: ['PC1 (34%)', 'PC2'], colors });
    expect(l.xaxis.showline).toBe(true);
    expect(l.xaxis.linewidth).toBe(AXIS_LINE_WIDTH);
    expect(l.xaxis.showgrid).toBe(false);
    expect(l.xaxis.showticklabels).toBe(true);
    expect((l.xaxis.title as { text: string }).text).toBe('PC1 (34%)');
    expect(l.annotations).toHaveLength(2);
    // paper-referenced tips at the two axis ends
    expect(l.annotations.map((a) => [a.x, a.y, a.xref, a.yref])).toEqual([
      [1, 0, 'paper', 'paper'],
      [0, 1, 'paper', 'paper'],
    ]);
    expect(l.annotations.every((a) => a.arrowcolor === colors.axis)).toBe(true);
  });

  it('hides tick labels and corners the titles for UMAP / t-SNE', () => {
    const l = embeddingAxisLayout({ style: 'default', family: 'neighbour', titles: ['UMAP 1', 'UMAP 2'], colors });
    expect(l.xaxis.showticklabels).toBe(false);
    expect((l.xaxis.title as { text: string }).text).toBe('');
    const labels = l.annotations.filter((a) => !a.showarrow);
    expect(labels.map((a) => a.text)).toEqual(['UMAP 1', 'UMAP 2']);
    expect(labels[1].textangle).toBe(-90);
    expect(l.annotations.filter((a) => a.showarrow)).toHaveLength(2);
  });

  it('keeps the grid fainter than the axis in the grid style, without arrows', () => {
    const l = embeddingAxisLayout({ style: 'grid', family: 'linear', titles: ['a', 'b'], colors });
    expect(l.xaxis.showgrid).toBe(true);
    expect(l.xaxis.gridwidth as number).toBeLessThan(l.xaxis.linewidth as number);
    expect(l.xaxis.linecolor).toBe(colors.axis);
    expect(l.xaxis.gridcolor).toBe(colors.grid);
    expect(l.annotations).toHaveLength(0);
  });

  it('draws bare axis lines in the lines style and nothing in clean', () => {
    const lines = embeddingAxisLayout({ style: 'lines', family: 'linear', titles: ['a', 'b'], colors });
    expect(lines.xaxis.showline).toBe(true);
    expect(lines.xaxis.showticklabels).toBe(false);
    expect(lines.annotations).toHaveLength(0);
    const clean = embeddingAxisLayout({ style: 'clean', family: 'linear', titles: ['a', 'b'], colors });
    expect(clean.xaxis.showline).toBe(false);
    expect(clean.annotations).toHaveLength(0);
  });

  it('anchors y to x so the embedding is not stretched', () => {
    const l = embeddingAxisLayout({ style: 'default', family: 'linear', titles: ['a', 'b'], colors });
    expect(l.yaxis.scaleanchor).toBe('x');
  });
});

describe('reassertAxisLines', () => {
  it('restores the line colour the theme pass tinted to the grid', () => {
    const source = embeddingAxisLayout({ style: 'default', family: 'linear', titles: ['a', 'b'], colors });
    const themed = {
      xaxis: { ...source.xaxis, linecolor: 'rgba(0,0,0,0.08)' },
      yaxis: { ...source.yaxis, linecolor: 'rgba(0,0,0,0.08)' },
      font: { color: 'x' },
    };
    const out = reassertAxisLines(themed, source as never) as typeof themed;
    expect(out.xaxis.linecolor).toBe(colors.axis);
    expect(out.yaxis.linecolor).toBe(colors.axis);
    expect(out.font).toEqual({ color: 'x' });
  });

  it('undoes a chrome patch that switches the axis line and ticks off', () => {
    const source = embeddingAxisLayout({ style: 'grid', family: 'linear', titles: ['a', 'b'], colors });
    const themed = {
      xaxis: { ...source.xaxis, showline: false, ticks: '', showgrid: false, title: { text: 'a' } },
      yaxis: { ...source.yaxis, showline: false, ticks: '' },
    };
    const out = reassertAxisLines(themed, source as never) as typeof themed;
    expect(out.xaxis.showline).toBe(true);
    expect(out.xaxis.ticks).toBe('outside');
    expect(out.xaxis.showgrid).toBe(true);
    expect(out.xaxis.title).toEqual({ text: 'a' });
    expect(out.yaxis.showline).toBe(true);
  });

  it('leaves a 3D layout untouched', () => {
    const themed = { scene: { a: 1 } };
    expect(reassertAxisLines(themed, { scene: {} })).toEqual(themed);
  });
});

describe('autoMarker', () => {
  it('draws a few points big and outlined', () => {
    expect(autoMarker(12)).toEqual({ size: 20, outlineWidth: 2.5 });
    expect(autoMarker(50)).toEqual({ size: 20, outlineWidth: 2.5 });
  });
  it('shrinks the points and thins the outline as the count grows', () => {
    expect(autoMarker(51)).toEqual({ size: 8, outlineWidth: 0.5 });
    expect(autoMarker(1000)).toEqual({ size: 8, outlineWidth: 0.5 });
  });
  it('drops the outline on a dense cloud', () => {
    expect(autoMarker(5000)).toEqual({ size: 4, outlineWidth: 0 });
  });
});
