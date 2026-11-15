/**
 * Orthogonal slices of an OME-Zarr volume: XZ (one row of Y) and YZ (one
 * column of X), drawn by the same viv layers as the XY plane.
 *
 * viv only cuts the last two axes of an array (y, x) into tiles. A resliced
 * source reads the same zarr array with the cut axis fixed and Z as the
 * image's rows: XZ is Z down and X across, YZ is Z down and Y across. Zarr
 * returns the two kept axes in the array's own order (z before y before x),
 * which is already rows then columns, so nothing is transposed.
 *
 * Coordinates are level-0 voxels, like the XY plane: the cut position is a
 * level-0 index, mapped to each level's own. Only levels whose Z shrinks by
 * the same factor as the in-plane axis make up the resliced pyramid (viv
 * assumes each level halves both of a tile's axes): a pyramid downsampled in
 * Y and X only keeps its level 0 here.
 */

import { levelIndex } from './pyramid';

export type OrthoPlane = 'xz' | 'yz';

/** Where the three planes cross, in level-0 voxels. */
export interface OrthoCursor {
  x: number;
  y: number;
  z: number;
}

/** What `getTile` gets as `selection` on a resliced source. */
export interface OrthoSelection {
  c?: number;
  t?: number;
  /** The level-0 index of the cut axis (Y for XZ, X for YZ). */
  at: number;
}

/** The parts of viv's ZarrPixelSource a resliced source reads through. */
export interface ZarrLevel {
  shape: number[];
  labels: string[];
  dtype: string;
  tileSize?: number;
  _getRaw?(
    selection: Array<number | { start: number; stop: number; step: null }>,
    opts?: { storeOptions?: { signal?: AbortSignal } },
  ): Promise<{ data: ArrayLike<number>; shape: number[] }>;
}

interface Tile {
  data: ArrayLike<number>;
  width: number;
  height: number;
}

class OutOfBounds extends Error {
  constructor() {
    // isBoundsError in viewer.ts matches viv's own wording.
    super('Tile slice is out of bounds.');
  }
}

/** One level of a resliced pyramid, in viv's PixelSource terms. */
export class ReslicedSource {
  readonly labels: string[];
  readonly shape: number[];
  readonly dtype: string;
  readonly tileSize: number;
  private readonly cut: 'x' | 'y';
  private readonly across: 'x' | 'y';

  constructor(
    private readonly level: ZarrLevel,
    plane: OrthoPlane,
    /** Level-0 size of the cut axis. */
    private readonly baseCut: number,
  ) {
    this.cut = plane === 'xz' ? 'y' : 'x';
    this.across = plane === 'xz' ? 'x' : 'y';
    const size = (axis: string) => level.shape[level.labels.indexOf(axis)] ?? 1;
    const others = level.labels.filter((a) => a === 'c' || a === 't');
    // viv reads the last two entries as height then width.
    this.labels = [...others, 'y', 'x'];
    this.shape = [...others.map(size), size('z'), size(this.across)];
    this.dtype = level.dtype;
    this.tileSize = level.tileSize ?? 256;
  }

  private size(axis: string): number {
    return this.level.shape[this.level.labels.indexOf(axis)] ?? 1;
  }

  private async read(
    rows: [number, number],
    cols: [number, number],
    selection: OrthoSelection,
    signal?: AbortSignal,
  ): Promise<Tile> {
    if (!this.level._getRaw) throw new Error('Orthogonal slices need an OME-Zarr image');
    const at = levelIndex(selection.at, this.baseCut, this.size(this.cut));
    const sel = this.level.labels.map((axis) => {
      if (axis === 'z') return { start: rows[0], stop: rows[1], step: null };
      if (axis === this.across) return { start: cols[0], stop: cols[1], step: null };
      if (axis === this.cut) return Math.min(this.size(axis) - 1, Math.max(0, at));
      if (axis === 'c') return selection.c ?? 0;
      if (axis === 't') return selection.t ?? 0;
      return 0;
    });
    const { data, shape } = await this.level._getRaw(sel, { storeOptions: { signal } });
    return { data, height: shape[0], width: shape[1] };
  }

  async getTile({
    x,
    y,
    selection,
    signal,
  }: {
    x: number;
    y: number;
    selection: OrthoSelection;
    signal?: AbortSignal;
  }): Promise<Tile> {
    const ts = this.tileSize;
    const height = this.size('z');
    const width = this.size(this.across);
    const cols: [number, number] = [x * ts, Math.min((x + 1) * ts, width)];
    const rows: [number, number] = [y * ts, Math.min((y + 1) * ts, height)];
    if (cols[0] < 0 || rows[0] < 0 || cols[0] >= cols[1] || rows[0] >= rows[1]) {
      throw new OutOfBounds();
    }
    return this.read(rows, cols, selection, signal);
  }

  async getRaster({ selection, signal }: { selection: OrthoSelection; signal?: AbortSignal }) {
    return this.read([0, this.size('z')], [0, this.size(this.across)], selection, signal);
  }

  onTileError(err: unknown) {
    if (!(err instanceof OutOfBounds)) throw err;
  }
}

/** The resliced pyramid of `pyramid` for `plane`, or null when the image has
 *  no Z (or is not a zarr store). */
export function reslice(pyramid: readonly ZarrLevel[], plane: OrthoPlane): ReslicedSource[] | null {
  const base = pyramid[0];
  if (!base?._getRaw || !base.labels.includes('z')) return null;
  const size = (level: ZarrLevel, axis: string) => level.shape[level.labels.indexOf(axis)] ?? 1;
  const baseZ = size(base, 'z');
  if (baseZ <= 1) return null;
  const across = plane === 'xz' ? 'x' : 'y';
  const cut = plane === 'xz' ? 'y' : 'x';
  const levels = pyramid.filter((level, i) => {
    if (i === 0) return true;
    const zFactor = baseZ / size(level, 'z');
    const factor = size(base, across) / size(level, across);
    // Each kept level halves both axes of the slice from the one before.
    return Math.abs(zFactor - factor) / factor < 0.05 && Math.abs(factor - 2 ** i) / 2 ** i < 0.05;
  });
  return levels.map((level) => new ReslicedSource(level, plane, size(base, cut)));
}

/** How much taller than wide one voxel is in Z, from the axis steps, for
 *  drawing the slices to scale; 1 when the store does not say. */
export function zAspect(
  zStep: { value: number; unit: string } | null,
  xStep: { value: number; unit: string } | null,
): number {
  if (!zStep || !xStep || zStep.unit !== xStep.unit || !(xStep.value > 0)) return 1;
  const ratio = zStep.value / xStep.value;
  return Number.isFinite(ratio) && ratio > 0 ? ratio : 1;
}
