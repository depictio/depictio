/**
 * Pyramids downsampled along more than X and Y.
 *
 * viv reads every level of a pyramid with the same selection, so it assumes
 * only X and Y shrink from one level to the next. Volume EM pyramids
 * (OpenOrganelle, CellMap, many FIB-SEM stores) halve Z too: level 4 of a
 * 6368-plane volume has 398 planes, and asking it for plane 3185 throws an
 * index error, so the image never draws. Each level here maps the level-0
 * index of such an axis to its own (the plane that holds the same depth).
 */

interface LevelSource {
  shape: number[];
  labels: string[];
  getRaster(opts: { selection: Record<string, number> }): Promise<unknown>;
  getTile?(opts: { selection: Record<string, number> } & Record<string, unknown>): Promise<unknown>;
}

const PLANAR = new Set(['x', 'y']);

/** The level's index along `axis` for a level-0 index (nearest plane holding
 *  that depth, clamped to the level). */
export function levelIndex(index: number, baseSize: number, levelSize: number): number {
  if (levelSize >= baseSize || baseSize <= 0) return index;
  return Math.min(levelSize - 1, Math.max(0, Math.floor((index * levelSize) / baseSize)));
}

/** The pyramid with every level answering level-0 selections. Levels whose
 *  non-XY axes match level 0 (the usual 2D pyramid) are returned as they are. */
export function matchSelectionsAcrossLevels<T extends LevelSource>(pyramid: T[]): T[] {
  const base = pyramid[0];
  if (!base) return pyramid;
  return pyramid.map((level, i) => {
    if (i === 0) return level;
    const shrunk = level.labels
      .map((axis, k) => ({ axis, base: base.shape[base.labels.indexOf(axis)], size: level.shape[k] }))
      .filter((a) => !PLANAR.has(a.axis) && a.base != null && a.size < a.base);
    if (!shrunk.length) return level;
    const map = (selection: Record<string, number>): Record<string, number> => {
      const out = { ...selection };
      for (const a of shrunk) {
        if (typeof out[a.axis] === 'number') out[a.axis] = levelIndex(out[a.axis], a.base, a.size);
      }
      return out;
    };
    // The level's own fields (shape, dtype, tileSize, the zarr array) stay
    // reachable through the prototype; only the reads are wrapped.
    const wrapped = Object.create(level) as T;
    wrapped.getRaster = (opts) => level.getRaster({ ...opts, selection: map(opts.selection) });
    if (level.getTile) {
      const getTile = level.getTile.bind(level);
      wrapped.getTile = (opts) => getTile({ ...opts, selection: map(opts.selection) });
    }
    return wrapped;
  });
}
