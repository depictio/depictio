import { gzipSync } from 'node:zlib';
import { beforeEach, describe, expect, it } from 'vitest';

import { clearObjectCache } from '../molecule/objectText';
import { paeAt, parsePae, PaeParseError, pyFloat, type PaeMatrix } from './paeParse';
import { loadPaeMatrix, PAE_CACHE_NAMESPACE } from './usePaeMatrix';

// Same fixture as depictio/tests/unit/recipes/test_pae_lib.py.
const MATRIX = [
  [0.0, 1.5, 4.25],
  [2.0, 0.0, 10.5],
  [3.75, 12.0, 0.0],
];

function rows(m: PaeMatrix): number[][] {
  return Array.from({ length: m.n }, (_, i) => Array.from({ length: m.n }, (_, j) => paeAt(m, i, j)));
}

describe('parsePae: delimited text', () => {
  it('reads a tab-separated proteinfold matrix', () => {
    const m = parsePae('0.0\t1.5\t4.25\n2.0\t0.0\t10.5\n3.75\t12.0\t0.0\n');
    expect(m.n).toBe(3);
    expect(rows(m)).toEqual(MATRIX);
    expect(m.values).toBeInstanceOf(Float32Array);
    expect(m.max).toBe(12);
    expect(m.declaredMax).toBeNull();
  });

  it('reads whitespace with blank lines and CRLF, commas and semicolons', () => {
    expect(rows(parsePae('\n 0.0   1.5  4.25 \r\n\r\n2.0 0.0 10.5\r\n3.75\t12.0  0.0\n\n'))).toEqual(MATRIX);
    expect(rows(parsePae('0.0,1.5,4.25\n2.0,0.0,10.5\n3.75,12.0,0.0\n'))).toEqual(MATRIX);
    expect(rows(parsePae('0.0;1.5;4.25\n2.0;0.0;10.5\n3.75;12.0;0.0'))).toEqual(MATRIX);
  });

  it('strips a byte-order mark', () => {
    expect(rows(parsePae('﻿0,1.5,4.25\n2,0,10.5\n3.75,12,0\n'))).toEqual(MATRIX);
  });

  it('skips a header row of names, only before the first row', () => {
    expect(rows(parsePae('r1,r2,r3\n0.0,1.5,4.25\n2.0,0.0,10.5\n3.75,12.0,0.0\n'))).toEqual(MATRIX);
    expect(rows(parsePae('A B C\n0 1.5 4.25\n2 0 10.5\n3.75 12 0\n'))).toEqual(MATRIX);
    expect(() => parsePae('0 1\nA B\n')).toThrow(/line 2: non-numeric/);
    // A header that mixes names and numbers is not a header.
    expect(() => parsePae('res 1 2\n0 1\n1 0\n')).toThrow(/line 1: non-numeric/);
  });

  it('reads integers and scientific notation like Python float()', () => {
    expect(rows(parsePae('0 1\n1e0 0\n'))).toEqual([
      [0, 1],
      [1, 0],
    ]);
    expect(pyFloat('-2.5E-1')).toBe(-0.25);
    expect(pyFloat('.5')).toBe(0.5);
    expect(Number.isNaN(pyFloat('nan'))).toBe(true);
    expect(pyFloat('-inf')).toBe(-Infinity);
    expect(pyFloat('Infinity')).toBe(Infinity);
    expect(pyFloat('0x10')).toBeNull();
    expect(pyFloat('abc')).toBeNull();
  });

  it('keeps the largest finite value as max', () => {
    const m = parsePae('0 nan\n3 0\n');
    expect(m.max).toBe(3);
    expect(Number.isNaN(paeAt(m, 0, 1))).toBe(true);
  });
});

describe('parsePae: JSON', () => {
  it('reads AlphaFold DB v3/v4 with its declared maximum', () => {
    const payload = [{ predicted_aligned_error: MATRIX, max_predicted_aligned_error: 31.75 }];
    const m = parsePae(JSON.stringify(payload));
    expect(rows(m)).toEqual(MATRIX);
    expect(m.declaredMax).toBe(31.75);
    expect(m.max).toBe(12);
  });

  it('reads ColabFold objects under either key', () => {
    expect(rows(parsePae(JSON.stringify({ predicted_aligned_error: MATRIX })))).toEqual(MATRIX);
    const m = parsePae(JSON.stringify({ pae: MATRIX, plddt: [90, 80, 70], max_pae: 31.75 }));
    expect(rows(m)).toEqual(MATRIX);
    expect(m.declaredMax).toBe(31.75);
  });

  it('reads a bare list of rows', () => {
    expect(rows(parsePae(JSON.stringify(MATRIX)))).toEqual(MATRIX);
  });

  it('reads AlphaFold DB v1 flattened pairs, in any order', () => {
    const residue1 = [1, 1, 1, 2, 2, 2, 3, 3, 3];
    const residue2 = [1, 2, 3, 1, 2, 3, 1, 2, 3];
    const distance = MATRIX.flat();
    const payload = [{ residue1, residue2, distance, max_predicted_aligned_error: 31.75 }];
    expect(rows(parsePae(JSON.stringify(payload)))).toEqual(MATRIX);
    const reversed = [
      {
        residue1: [...residue1].reverse(),
        residue2: [...residue2].reverse(),
        distance: [...distance].reverse(),
      },
    ];
    expect(rows(parsePae(JSON.stringify(reversed)))).toEqual(MATRIX);
  });

  it('refuses incomplete or malformed pair lists', () => {
    const missing = [{ residue1: [1, 1, 2], residue2: [1, 2, 1], distance: [0, 1, 1] }];
    expect(() => parsePae(JSON.stringify(missing))).toThrow(/full 2 x 2/);
    expect(() =>
      parsePae(JSON.stringify([{ residue1: [1], residue2: [1, 2], distance: [0] }])),
    ).toThrow(/differ in length/);
    expect(() =>
      parsePae(JSON.stringify([{ residue1: [0], residue2: [1], distance: [0] }])),
    ).toThrow(/1-based/);
  });
});

describe('parsePae: errors (same messages as read_pae)', () => {
  it.each([
    ['1 2 3\n4 5 6\n', /square/],
    ['1 2\n3 4\n5 6\n', /square/],
    ['1 2 3\n4 5\n6 7 8\n', /square/],
    [JSON.stringify({ predicted_aligned_error: [[1, 2, 3], [4, 5, 6]] }), /square/],
    [JSON.stringify([{ predicted_aligned_error: [[1, 2], [3]] }]), /square/],
    ['', /empty/],
    ['   \n\n', /empty/],
    ['0 1\n1 x\n', /non-numeric/],
    ['{not json', /not valid/],
    [JSON.stringify({ something: 1 }), /none of/],
    [JSON.stringify({ pae: [[1, 'a'], [2, 3]] }), /non-numeric/],
    [JSON.stringify({ pae: [[1, true], [2, 3]] }), /non-numeric/],
    [JSON.stringify({ pae: [1, 2] }), /list of rows/],
    [JSON.stringify({ pae: [] }), /no PAE rows/],
    ['[7]', /list of rows/],
    ['null', /no PAE rows/],
  ])('%j', (text, message) => {
    expect(() => parsePae(text)).toThrow(PaeParseError);
    expect(() => parsePae(text)).toThrow(message);
  });

  it('names the row lengths of a non-square matrix', () => {
    expect(() => parsePae('1 2 3\n4 5 6\n')).toThrow('PAE matrix must be square: 2 rows, row lengths [3]');
  });
});

describe('loadPaeMatrix: through the object loader', () => {
  beforeEach(() => clearObjectCache(PAE_CACHE_NAMESPACE));

  it('gunzips gzipped TSV and JSON bytes before parsing', async () => {
    const tsv = gzipSync(Buffer.from('0\t1.5\t4.25\n2\t0\t10.5\n3.75\t12\t0\n'));
    const a = await loadPaeMatrix('https://s3/bucket/a.pae.tsv.gz?sig=1', {
      fetcher: async () => new Response(tsv),
    });
    expect(rows(a)).toEqual(MATRIX);
    const json = gzipSync(Buffer.from(JSON.stringify([{ predicted_aligned_error: MATRIX }])));
    const b = await loadPaeMatrix('https://s3/bucket/b.pae.json.gz', {
      fetcher: async () => new Response(json),
    });
    expect(rows(b)).toEqual(MATRIX);
  });

  it('parses an object once, whatever its presigned signature', async () => {
    let fetched = 0;
    const fetcher = async () => {
      fetched += 1;
      return new Response('0 1\n1 0\n');
    };
    const first = await loadPaeMatrix('https://s3/bucket/x.pae.tsv?sig=old', { fetcher });
    const second = await loadPaeMatrix('https://s3/bucket/x.pae.tsv?sig=new', { fetcher });
    expect(fetched).toBe(1);
    expect(second).toBe(first);
  });

  it('fails with the parse message, and evicts so a retry fetches again', async () => {
    let fetched = 0;
    const fetcher = async () => {
      fetched += 1;
      return new Response('1 2 3\n4 5 6\n');
    };
    await expect(loadPaeMatrix('https://s3/bucket/bad.pae.tsv', { fetcher })).rejects.toThrow(/square/);
    await expect(loadPaeMatrix('https://s3/bucket/bad.pae.tsv', { fetcher })).rejects.toThrow(/square/);
    expect(fetched).toBe(2);
  });

  it('names the file kind in a refused download', async () => {
    await expect(
      loadPaeMatrix('https://s3/bucket/gone.pae.tsv', {
        fetcher: async () => new Response('', { status: 404 }),
      }),
    ).rejects.toThrow('PAE file unavailable (404)');
  });
});
