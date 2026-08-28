import { describe, it, expect } from 'vitest';
import { parseFixture, headerLooksLikeData } from '../catalog/parseFixture';

describe('parseFixture', () => {
  it('detects CSV delimiter and infers dtypes', () => {
    const f = parseFixture('x.csv', ['a,b,c,d', '1,1.5,foo,true', '2,2.5,bar,false'].join('\n'));
    expect(f.delimiter).toBe(',');
    const dt = Object.fromEntries(f.columns.map((c) => [c.name, c.dtype]));
    expect(dt).toEqual({ a: 'Int64', b: 'Float64', c: 'String', d: 'Boolean' });
    expect(f.rows).toHaveLength(2);
  });
  it('detects TSV by extension', () => {
    const f = parseFixture('x.tsv', 'a\tb\n1\t2\n');
    expect(f.delimiter).toBe('\t');
    expect(f.columns.map((c) => c.name)).toEqual(['a', 'b']);
  });
  it('infers Datetime for ISO dates', () => {
    const f = parseFixture('d.csv', ['ts', '2026-05-21 19:31:50', '2026-05-22 10:00:00'].join('\n'));
    expect(f.columns[0].dtype).toBe('Datetime');
  });

  it('sniffs the delimiter when the extension does not state one', () => {
    // What most real tool outputs look like: a .txt that is really a TSV.
    const tsv = parseFixture('abricate_summary.txt', 'a\tb\tc\n1\t2\t3\n');
    expect(tsv.delimiter).toBe('\t');
    expect(tsv.columns.map((c) => c.name)).toEqual(['a', 'b', 'c']);

    const csv = parseFixture('output.txt', 'a,b,c\n1,2,3\n');
    expect(csv.delimiter).toBe(',');
    expect(csv.columns).toHaveLength(3);
  });

  it('sniffs past a comment banner but does not strip it', () => {
    // depictio's reader has no comment_prefix, so the banner must NOT be
    // silently dropped here: that would show columns CI cannot find. Sniffing
    // still ignores it, and the Fixture step warns about the banner instead.
    const f = parseFixture('stats.txt', ['# produced by tool', 'a\tb', '1\t2'].join('\n'));
    expect(f.delimiter).toBe('\t');
    expect(f.columns.map((c) => c.name)).toEqual(['# produced by tool']);
    expect(f.raw.startsWith('# produced by tool')).toBe(true);
  });

  it('commits a tab-delimited non-.tsv file under a .tsv name', () => {
    // depictio only uses a tab separator for .tsv, so the name has to say so.
    const f = parseFixture('abricate_summary.txt', 'a\tb\n1\t2\n');
    expect(f.fileName).toBe('abricate_summary.tsv');
    expect(f.renamedFrom).toBe('abricate_summary.txt');
    expect(f.raw).toBe('a\tb\n1\t2\n');
  });

  it('leaves a comma-delimited name alone whatever its extension', () => {
    // Comma is the else-branch of depictio's rule, so .txt already reads right.
    const f = parseFixture('output.txt', 'a,b\n1,2\n');
    expect(f.fileName).toBe('output.txt');
    expect(f.renamedFrom).toBeUndefined();
  });

  it('lets an explicit extension win over the content', () => {
    // A comma-delimited .tsv must keep mis-parsing loudly: the Fixture step
    // warns on the single wide column, which is how the author notices.
    const f = parseFixture('mislabelled.tsv', 'a,b\n1,2\n');
    expect(f.delimiter).toBe('\t');
    expect(f.columns).toHaveLength(1);
  });

  it('preserves raw content verbatim', () => {
    const raw = 'a,b\n1,2\n';
    expect(parseFixture('x.csv', raw).raw).toBe(raw);
  });
});

describe('headerLooksLikeData', () => {
  it('flags a kraken2 report, which ships no header at all', () => {
    // First line of a real report: ' 25.41\t147167\t147167\tU\t0\tunclassified'.
    const f = parseFixture('SAMPLE_01.kraken2.report.txt', [
      ' 25.41\t147167\t147167\tU\t0\tunclassified',
      ' 74.59\t431894\t0\tR\t1\troot',
    ].join('\n'));
    expect(headerLooksLikeData(f.columns.map((c) => c.name))).toBe(true);
  });

  it('leaves a real header alone', () => {
    expect(headerLooksLikeData(['task_id', 'hash', 'native_id', 'name', 'status'])).toBe(false);
    expect(headerLooksLikeData(['gene', 'log2fc', 'pvalue'])).toBe(false);
  });

  it('tolerates a single numeric name among many', () => {
    // A column genuinely called '2024' should not condemn the whole header.
    expect(headerLooksLikeData(['sample', '2024', 'depth', 'mean', 'sd', 'n'])).toBe(false);
  });

  it('says nothing about a one-column file', () => {
    expect(headerLooksLikeData(['42'])).toBe(false);
  });
});
