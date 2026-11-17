import { describe, expect, it } from 'vitest';

import {
  asKey,
  fileColumnKeys,
  matchDroppedTable,
  parseDroppedTable,
  parsePastedBlock,
  type ParsedTable,
} from './annotationInput';

const parsed = (name: string, text: string) => parseDroppedTable(name, text) as ParsedTable;

describe('asKey (mirrors table_merge._as_key)', () => {
  it('normalises like the server', () => {
    expect(asKey(3.0)).toBe('3');
    expect(asKey(2.5)).toBe('2.5');
    expect(asKey(true)).toBe('true');
    expect(asKey(Number.NaN)).toBeNull();
    expect(asKey('  S1 ')).toBe('S1');
    expect(asKey('   ')).toBeNull();
    expect(asKey(null)).toBeNull();
  });
  it('reads a numeric file column as numbers, a text column as text', () => {
    expect(fileColumnKeys(['1.0', '2', ''])).toEqual(['1', '2', null]);
    expect(fileColumnKeys(['1.0', 'S2'])).toEqual(['1.0', 'S2']);
  });
});

describe('parseDroppedTable', () => {
  it('takes the delimiter from the extension, else from the header', () => {
    expect(parsed('a.tsv', 'sample\tgroup\nS1\tx\n').columns).toEqual(['sample', 'group']);
    expect(parsed('a.txt', 'sample\tgroup\nS1\tx\n').columns).toEqual(['sample', 'group']);
    expect(parsed('a.csv', '﻿sample,group\r\nS1,"x, y"\r\n').rows).toEqual([
      { sample: 'S1', group: 'x, y' },
    ]);
  });
  it('refuses repeated column names', () => {
    expect(parseDroppedTable('a.csv', 'a,a\n1,2\n')).toEqual({
      error: 'Two columns of the file have the same name.',
    });
  });
});

describe('matchDroppedTable', () => {
  const keys = new Set(['S1', 'S2', 'S3']);

  it('uses the column named like the key and makes one annotation per other column', () => {
    const m = matchDroppedTable(parsed('a.csv', 'sample,response,batch\nS1,yes,b1\nS2,no,\nS9,yes,b2\n'), 'sample', keys);
    expect(m).toEqual({
      fileKeyColumn: 'sample',
      annotations: [
        { name: 'response', values: { S1: 'yes', S2: 'no' } },
        { name: 'batch', values: { S1: 'b1' } },
      ],
      matchedRows: 2,
      unmatchedRows: 1,
      unmatchedSample: ['S9'],
    });
  });

  it('falls back to the unique column that matches most keys', () => {
    const m = matchDroppedTable(parsed('a.csv', 'id,label\nS1,a\nS3,b\n'), 'sample', keys);
    expect(m).toMatchObject({ fileKeyColumn: 'id', matchedRows: 2 });
  });

  it('matches integer floats against integer keys', () => {
    const m = matchDroppedTable(parsed('a.csv', 'n,label\n1.0,a\n2.0,b\n'), 'n', new Set(['1', '2']));
    expect(m).toMatchObject({ matchedRows: 2 });
  });

  it('refuses repeated keys, no match, and nothing to annotate with', () => {
    expect(matchDroppedTable(parsed('a.csv', 'sample,r\nS1,a\nS1,b\n'), 'sample', keys)).toHaveProperty('error');
    expect(matchDroppedTable(parsed('a.csv', 'x,r\nQ1,a\n'), 'sample', keys)).toHaveProperty('error');
    expect(matchDroppedTable(parsed('a.csv', 'sample\nS1\n'), 'sample', keys)).toHaveProperty('error');
  });

  it('refuses a label over the cap rather than cutting it', () => {
    const long = 'x'.repeat(81);
    expect(matchDroppedTable(parsed('a.csv', `sample,r\nS1,${long}\n`), 'sample', keys)).toHaveProperty('error');
  });
});

describe('parsePastedBlock', () => {
  it('splits spreadsheet clipboard text', () => {
    expect(parsePastedBlock('a\tb\r\nc\td\r\n')).toEqual([
      ['a', 'b'],
      ['c', 'd'],
    ]);
    expect(parsePastedBlock('"x\ty"\tz\n')).toEqual([['x\ty', 'z']]);
    expect(parsePastedBlock('one')).toEqual([['one']]);
    expect(parsePastedBlock('')).toEqual([]);
  });
});
