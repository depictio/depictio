import { describe, expect, it } from 'vitest';

import { levelIndex, matchSelectionsAcrossLevels } from './pyramid';

function level(shape: number[], seen: Record<string, number>[]) {
  return {
    shape,
    labels: ['z', 'y', 'x'],
    tileSize: 128,
    async getRaster({ selection }: { selection: Record<string, number> }) {
      seen.push(selection);
      return { data: [] };
    },
    async getTile({ selection }: { selection: Record<string, number>; x: number; y: number }) {
      seen.push(selection);
      return { data: [], width: 1, height: 1 };
    },
  };
}

describe('levelIndex', () => {
  it('maps a level-0 plane to the plane holding the same depth', () => {
    expect(levelIndex(3185, 6368, 398)).toBe(199);
    expect(levelIndex(6367, 6368, 398)).toBe(397);
    expect(levelIndex(0, 6368, 398)).toBe(0);
  });
  it('leaves an axis that does not shrink alone', () => {
    expect(levelIndex(12, 40, 40)).toBe(12);
  });
});

describe('matchSelectionsAcrossLevels', () => {
  it('scales Z on levels downsampled in Z, and keeps their other fields', async () => {
    const seen: Record<string, number>[] = [];
    const pyramid = matchSelectionsAcrossLevels([
      level([6368, 1600, 12000], seen),
      level([398, 100, 750], seen),
    ]);
    await pyramid[1].getTile({ x: 0, y: 0, selection: { z: 3185, t: 0 } });
    await pyramid[1].getRaster({ selection: { z: 6367 } });
    expect(seen).toEqual([{ z: 199, t: 0 }, { z: 397 }]);
    expect(pyramid[1].shape).toEqual([398, 100, 750]);
    expect(pyramid[1].tileSize).toBe(128);
  });

  it('returns 2D pyramids untouched', () => {
    const seen: Record<string, number>[] = [];
    const levels = [level([40, 512, 512], seen), level([40, 256, 256], seen)];
    const pyramid = matchSelectionsAcrossLevels(levels);
    expect(pyramid[1]).toBe(levels[1]);
  });
});
