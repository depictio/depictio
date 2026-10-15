import { describe, expect, it } from 'vitest';

import { visibleTableColumns } from './tableColumns';

const cols = (...fields: string[]) => fields.map((field) => ({ field }));
const fields = (c: { field: string }[]) => c.map((x) => x.field);

describe('visibleTableColumns', () => {
  it('keeps every column, in the response order, with no allowlist', () => {
    expect(fields(visibleTableColumns(cols('a', 'b', 'c'), {}, undefined))).toEqual(['a', 'b', 'c']);
    expect(fields(visibleTableColumns(cols('a', 'b', 'c'), null, []))).toEqual(['a', 'b', 'c']);
  });

  it("follows the allowlist's order, so key columns come first", () => {
    expect(fields(visibleTableColumns(cols('a', 'b', 'c', 'd'), {}, ['c', 'a']))).toEqual([
      'c',
      'a',
    ]);
  });

  it('skips allowlisted names the response does not hold', () => {
    expect(fields(visibleTableColumns(cols('a', 'b'), {}, ['gone', 'b', 'a']))).toEqual(['b', 'a']);
  });

  it('still drops a column the builder hid, allowlisted or not', () => {
    const hidden = { b: { hide: true } };
    expect(fields(visibleTableColumns(cols('a', 'b', 'c'), hidden, ['b', 'c']))).toEqual(['c']);
    expect(fields(visibleTableColumns(cols('a', 'b', 'c'), hidden, undefined))).toEqual(['a', 'c']);
  });
});
