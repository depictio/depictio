// @vitest-environment node
/**
 * Small review fixes with no UI of their own: gzipped raw samples are
 * decompressed for the recipe engine, and the fixture-hash cache shared by
 * every useDiagnostics instance is pruned to the current fixtures.
 */
import { describe, expect, it } from 'vitest';
import { gzipSync } from 'node:zlib';
import { readRawSample } from '../catalog/rawSample';
import { __shaCacheSize, fixtureShas } from '../hooks/useDiagnostics';
import { sha256Hex } from '../catalog/diagnostics';

describe('readRawSample', () => {
  it('decompresses a .gz sample and keeps its name for source globs', async () => {
    const f = new File([gzipSync('chrom\tstart\nchr1\t1\n')], 'x.per-base.bed.gz');
    expect(await readRawSample(f)).toEqual({ fileName: 'x.per-base.bed', text: 'chrom\tstart\nchr1\t1\n', sourcePath: 'x.per-base.bed.gz' });
  });
  it('reads a plain sample as text', async () => {
    expect(await readRawSample(new File(['a,b\n'], 'r.csv'))).toEqual({ fileName: 'r.csv', text: 'a,b\n' });
  });
});

describe('fixtureShas', () => {
  it('hashes each fixture once and forgets the ones no longer in the draft', async () => {
    const one = await fixtureShas(['a', 'b']);
    expect(one).toEqual({ a: await sha256Hex('a'), b: await sha256Hex('b') });
    expect(__shaCacheSize()).toBe(2);
    await fixtureShas(['b', 'c']);
    expect(__shaCacheSize()).toBe(2);
    expect(await fixtureShas([])).toEqual({});
    expect(__shaCacheSize()).toBe(0);
  });
});
