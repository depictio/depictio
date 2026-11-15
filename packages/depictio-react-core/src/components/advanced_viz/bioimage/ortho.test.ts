import { describe, expect, it } from 'vitest';

import { reslice, zAspect, type ZarrLevel } from './ortho';

type Sel = Array<number | { start: number; stop: number; step: null }>;

function level(shape: number[], reads: Sel[], labels = ['z', 'y', 'x']): ZarrLevel {
  return {
    shape,
    labels,
    dtype: 'Uint8',
    tileSize: 128,
    async _getRaw(selection: Sel) {
      reads.push(selection);
      const kept = selection.filter((s) => typeof s !== 'number') as Array<{
        start: number;
        stop: number;
      }>;
      const out = kept.map((s) => s.stop - s.start);
      return { data: new Uint8Array(out[0] * out[1]), shape: out };
    },
  };
}

describe('reslice', () => {
  it('reads XZ with Y fixed, Z as rows and X as columns, per level', async () => {
    const reads: Sel[] = [];
    const xz = reslice(
      [level([6368, 1600, 12000], reads), level([3184, 800, 6000], reads)],
      'xz',
    )!;
    expect(xz.map((s) => s.shape)).toEqual([
      [6368, 12000],
      [3184, 6000],
    ]);
    expect(xz[0].labels).toEqual(['y', 'x']);
    const tile = await xz[1].getTile({ x: 2, y: 1, selection: { at: 800 } });
    // Level 1 halves Y: level-0 row 800 is row 400 there.
    expect(reads[0]).toEqual([
      { start: 128, stop: 256, step: null },
      400,
      { start: 256, stop: 384, step: null },
    ]);
    expect([tile.height, tile.width]).toEqual([128, 128]);
  });

  it('reads YZ with X fixed, keeping channel and time', async () => {
    const reads: Sel[] = [];
    const [yz] = reslice([level([2, 40, 512, 256], reads, ['c', 'z', 'y', 'x'])], 'yz')!;
    expect(yz.shape).toEqual([2, 40, 512]);
    expect(yz.labels).toEqual(['c', 'y', 'x']);
    await yz.getTile({ x: 3, y: 0, selection: { c: 1, at: 300 } });
    expect(reads[0]).toEqual([
      1,
      { start: 0, stop: 40, step: null },
      { start: 384, stop: 512, step: null },
      255,
    ]);
  });

  it('keeps only level 0 when Z does not shrink with the plane', () => {
    const reads: Sel[] = [];
    const xz = reslice([level([40, 1024, 1024], reads), level([40, 512, 512], reads)], 'xz')!;
    expect(xz).toHaveLength(1);
  });

  it('refuses a plane image', () => {
    expect(reslice([level([1, 64, 64], [])], 'xz')).toBeNull();
    expect(reslice([level([64, 64], [], ['y', 'x'])], 'xz')).toBeNull();
  });

  it('says a tile past the edge is out of bounds', async () => {
    const [xz] = reslice([level([100, 50, 200], [])], 'xz')!;
    await expect(xz.getTile({ x: 5, y: 0, selection: { at: 0 } })).rejects.toThrow(/Tile slice/);
  });
});

describe('zAspect', () => {
  it('is the Z step over the X step, in the same unit', () => {
    expect(zAspect({ value: 5.24, unit: 'nm' }, { value: 4, unit: 'nm' })).toBeCloseTo(1.31);
    expect(zAspect({ value: 2, unit: 'µm' }, { value: 4, unit: 'nm' })).toBe(1);
    expect(zAspect(null, { value: 4, unit: 'nm' })).toBe(1);
  });
});

describe('ScaleMatrix', () => {
  it('answers the Matrix4 calls viv makes', async () => {
    const { ScaleMatrix } = await import('./matrix');
    const m = ScaleMatrix.of2d(1, 1.31);
    expect(m).toHaveLength(16);
    expect(m.getScale()).toEqual([1, 1.31, 1]);
    const backdrop = m.clone().scale(4);
    expect(backdrop.getScale()).toEqual([4, 5.24, 4]);
    expect(m.getScale()).toEqual([1, 1.31, 1]);
  });
});
