import { describe, it, expect } from 'vitest';
import { parseFixture } from '../catalog/parseFixture';

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
  it('preserves raw content verbatim', () => {
    const raw = 'a,b\n1,2\n';
    expect(parseFixture('x.csv', raw).raw).toBe(raw);
  });
});
