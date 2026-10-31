import { describe, expect, it } from 'vitest';

import { collectAllPages, columnsCsv, csvField, csvText, exportFileName } from './tableExport';

describe('csv', () => {
  it('quotes fields that hold a comma, a quote or a line break', () => {
    expect(csvField('plain')).toBe('plain');
    expect(csvField('a,b')).toBe('"a,b"');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField('two\nlines')).toBe('"two\nlines"');
    expect(csvField(null)).toBe('');
    expect(csvField(3)).toBe('3');
  });

  it('writes a header line then one line per row', () => {
    expect(csvText(['a', 'b'], [[1, 'x,y'], [2, null]])).toBe('a,b\r\n1,"x,y"\r\n2,\r\n');
  });

  it('writes column-oriented rows, skipping columns the data lacks', () => {
    const data = { sample: ['s1', 's2'], reads: [10, 20] };
    expect(columnsCsv(data)).toBe('sample,reads\r\ns1,10\r\ns2,20\r\n');
    expect(columnsCsv(data, ['reads', 'missing'])).toBe('reads\r\n10\r\n20\r\n');
    expect(columnsCsv({})).toBe('\r\n');
  });
});

describe('collectAllPages', () => {
  const server = (n: number) => async (start: number, end: number) => ({
    rows: Array.from({ length: Math.max(0, Math.min(end, n) - start) }, (_, i) => start + i),
    total: n,
  });

  it('pages until the total is reached', async () => {
    const out = await collectAllPages(server(450), { pageSize: 200 });
    expect(out.rows).toHaveLength(450);
    expect(out.rows[449]).toBe(449);
    expect(out.truncated).toBe(false);
  });

  it('stops at the cap and says so', async () => {
    const out = await collectAllPages(server(1000), { pageSize: 200, max: 500 });
    expect(out.rows).toHaveLength(500);
    expect(out.total).toBe(1000);
    expect(out.truncated).toBe(true);
  });

  it('stops on an empty page even when the total says more', async () => {
    const out = await collectAllPages(async () => ({ rows: [], total: 99 }));
    expect(out.rows).toEqual([]);
  });
});

describe('exportFileName', () => {
  it('keeps a safe stem and falls back when nothing is left', () => {
    expect(exportFileName('Genome browser: regions')).toBe('Genome_browser_regions.csv');
    expect(exportFileName('  ', 'tsv')).toBe('table.tsv');
  });
});
