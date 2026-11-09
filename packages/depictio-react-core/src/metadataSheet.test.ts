import { describe, expect, it } from 'vitest';
import { buildMetadataSheet, metadataSheetName } from './metadataSheet';
import type { AnnotationColumn } from './sessionAnnotations';

const col = (name: string, values: Record<string, string>): AnnotationColumn => ({
  id: name,
  name,
  dcId: 'dc',
  keyColumn: 'sample',
  values,
});

describe('buildMetadataSheet', () => {
  const rows = [
    { sample: 'S1', habitat: 'River' },
    { sample: 'S2', habitat: 'Soil' },
    { sample: 'S1', habitat: 'River' },
  ];

  it('adds one column per label, empty where a key has none', () => {
    const tsv = buildMetadataSheet(['sample', 'habitat'], rows, 'sample', [col('response', { S1: 'yes' })]);
    expect(tsv).toBe('sample\thabitat\tresponse\nS1\tRiver\tyes\nS2\tSoil\t\nS1\tRiver\tyes\n');
  });

  it('renames a label column the table already has', () => {
    const tsv = buildMetadataSheet(['sample', 'habitat'], rows.slice(0, 1), 'sample', [
      col('habitat', { S1: 'upstream' }),
    ]);
    expect(tsv.split('\n')[0]).toBe('sample\thabitat\thabitat (label)');
  });

  it('quotes a value holding a tab, a newline or a quote', () => {
    const tsv = buildMetadataSheet(['sample'], [{ sample: 'S1' }], 'sample', [
      col('note', { S1: 'a\tb "c"' }),
    ]);
    expect(tsv.split('\n')[1]).toBe('S1\t"a\tb ""c"""');
  });

  it('matches keys as the panel does (integer floats as integers)', () => {
    const tsv = buildMetadataSheet(['id'], [{ id: 3.0 }], 'id', [
      { ...col('g', { '3': 'x' }), keyColumn: 'id' },
    ]);
    expect(tsv.split('\n')[1]).toBe('3\tx');
  });
});

describe('metadataSheetName', () => {
  it('is safe as a file name', () => {
    expect(metadataSheetName('Metadata full')).toBe('Metadata_full_with_labels.tsv');
    expect(metadataSheetName('')).toBe('metadata_with_labels.tsv');
  });
  it('leaves out the columns Depictio adds at ingest', () => {
    const text = buildMetadataSheet(
      ['sample', 'habitat', 'depictio_run_id', 'aggregation_time'],
      [{ sample: 'S1', habitat: 'Soil', depictio_run_id: 'r', aggregation_time: 't' }],
      'sample',
      [{ id: 'a', name: 'response', dcId: 'd', keyColumn: 'sample', values: { S1: 'yes' } }],
    );
    expect(text).toBe('sample\thabitat\tresponse\nS1\tSoil\tyes\n');
  });
});
