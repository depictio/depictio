import { describe, expect, it } from 'vitest';

import { distinguishingColumns, rowLabel } from './recordRows';

const rows = [
  { gene: 'FCER1A', resolution: 'graphclust', cluster: 'Cluster 8', log2fc: 7.7 },
  { gene: 'FCER1A', resolution: 'kmeans_10', cluster: 'Cluster 6', log2fc: 5.5 },
  { gene: 'FCER1A', resolution: 'kmeans_6', cluster: 'Cluster 5', log2fc: 6 },
];

describe('distinguishingColumns', () => {
  it('skips the columns every row shares', () => {
    expect(distinguishingColumns(rows, ['gene', 'resolution', 'cluster', 'log2fc'])).toEqual([
      'resolution',
      'cluster',
    ]);
  });

  it('caps the label at the requested width', () => {
    expect(distinguishingColumns(rows, ['resolution', 'cluster', 'log2fc'], 1)).toEqual([
      'resolution',
    ]);
  });

  it('has nothing to say about one row', () => {
    expect(distinguishingColumns(rows.slice(0, 1), ['resolution'])).toEqual([]);
  });
});

describe('rowLabel', () => {
  it('joins the distinguishing values', () => {
    expect(rowLabel(rows[1], ['resolution', 'cluster'], 1)).toBe('kmeans_10 / Cluster 6');
  });

  it('falls back to the position when nothing tells the rows apart', () => {
    expect(rowLabel(rows[1], [], 1)).toBe('row 2');
  });
});
