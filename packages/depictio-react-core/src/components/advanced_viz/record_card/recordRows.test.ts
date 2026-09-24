import { describe, expect, it } from 'vitest';

import {
  distinguishingColumns,
  latestPickedValue,
  recordOptionLabel,
  rowLabel,
} from './recordRows';

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

describe('latestPickedValue', () => {
  it('is the value the previous selection did not have, whatever its position', () => {
    expect(latestPickedValue(['B', 'D'], ['A', 'B', 'D'])).toBe('A');
    expect(latestPickedValue(null, ['A', 'B'])).toBe('A');
  });

  it('falls back to the last value when nothing was added, and to null when empty', () => {
    expect(latestPickedValue(['A', 'B', 'C'], ['A', 'C'])).toBe('C');
    expect(latestPickedValue(['A'], [])).toBeNull();
  });
});

describe('recordOptionLabel', () => {
  const row = { gene_id: 'ENSG1', gene_name: 'FCER1A', resolution: 'kmeans_6', cluster: 'Cluster 5' };

  it('leads with the title, then the id, then the distinguishing values', () => {
    expect(
      recordOptionLabel(row, {
        idCol: 'gene_id',
        titleCol: 'gene_name',
        labelColumns: ['gene_id', 'resolution', 'cluster'],
        position: 0,
      }),
    ).toBe('FCER1A (ENSG1) · kmeans_6 · Cluster 5');
  });

  it('shows the id alone when there is no title column', () => {
    expect(recordOptionLabel(row, { idCol: 'gene_id', labelColumns: [], position: 0 })).toBe(
      'ENSG1',
    );
  });
});
