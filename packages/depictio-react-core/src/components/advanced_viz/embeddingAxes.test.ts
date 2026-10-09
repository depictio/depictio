import { describe, expect, it } from 'vitest';
import { embeddingAxisTitles } from './embeddingAxes';

describe('embeddingAxisTitles', () => {
  it('names the dimensions after the configured prefix', () => {
    expect(embeddingAxisTitles({ dim_1_col: 'dim_1', dim_2_col: 'dim_2', axis_prefix: 'PCo' })).toEqual([
      'PCo1',
      'PCo2',
      'PCo3',
    ]);
  });

  it('takes the prefix from the live method when none is configured', () => {
    expect(embeddingAxisTitles({ dim_1_col: 'dim_1', dim_2_col: 'dim_2' }, 'pca').slice(0, 2)).toEqual([
      'PC1',
      'PC2',
    ]);
    expect(embeddingAxisTitles({}, 'tsne')[0]).toBe('t-SNE 1');
  });

  it('prefers the configured prefix over the live method', () => {
    expect(embeddingAxisTitles({ axis_prefix: 'Axis ' }, 'umap')[0]).toBe('Axis 1');
  });

  it('keeps the column names when nothing names the dimensions', () => {
    expect(embeddingAxisTitles({ dim_1_col: 'UMAP_1', dim_2_col: 'UMAP_2' })).toEqual([
      'UMAP_1',
      'UMAP_2',
      'dim_3',
    ]);
  });
});
