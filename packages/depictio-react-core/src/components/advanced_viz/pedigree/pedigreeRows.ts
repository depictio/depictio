/**
 * Lay several families out as rows, so a tile that is wide and short and one
 * that is narrow and tall both fill their box.
 *
 * Side by side, three small families make a long strip: the drawing is scaled
 * to the tile's width and floats in the middle of its height with the symbols
 * small. Wrapped into two or three rows the same families are narrower and
 * taller, and the scale rises until the drawing fills both directions
 * (`min(w / W, h / H)`). The arrangement that earns the largest scale wins;
 * on a tie, the fewest rows (families keep their order, read left to right and
 * then down).
 *
 * Pure: the geometry is `layoutPedigree`'s, the scoring `fitScale`'s.
 */
import { DEFAULT_LAYOUT, layoutPedigree, type PedigreeFamily, type PedigreeLayout } from './pedigreeLayout';
import { fitScale } from './probands';

/** Beyond this many families every split is not tried: the families are cut
 *  into equal rows instead (2^(n-1) arrangements is the cost of trying them). */
const MAX_EXHAUSTIVE = 12;

export interface PackedRow {
  /** The families of the row, in order. */
  families: PedigreeFamily[];
  /** Their layout, from x = 0. */
  layout: PedigreeLayout;
  /** Top of the row in the drawing, units. */
  y: number;
}

export interface Packing {
  rows: PackedRow[];
  /** The whole drawing, units, margins included. */
  contentW: number;
  contentH: number;
  /** The scale the drawing is shown at (see `fitScale`). */
  scale: number;
}

export interface PackOptions {
  /** Room the tile gives the drawing, px; 0 while unmeasured. */
  availW: number;
  availH: number;
  /** Left of the trees (generation numerals), their side margins, and under the last row. */
  gutter: number;
  padX: number;
  padBottom: number;
  /** Extra space between two rows, units. */
  rowGap?: number;
  /** Space under a symbol for its label (0 without labels). */
  labelSpace: number;
}

interface FamilyBox {
  width: number;
  height: number;
}

/** Every way to cut `n` families, in order, into rows: a bit per gap says "new row here". */
function* splits(n: number): Generator<number[]> {
  if (n > MAX_EXHAUSTIVE) {
    for (let rows = 1; rows <= n; rows += 1) {
      const sizes: number[] = [];
      let left = n;
      for (let r = rows; r > 0; r -= 1) {
        const take = Math.ceil(left / r);
        sizes.push(take);
        left -= take;
      }
      yield sizes;
    }
    return;
  }
  for (let mask = 0; mask < 1 << (n - 1); mask += 1) {
    const sizes: number[] = [];
    let run = 1;
    for (let gap = 0; gap < n - 1; gap += 1) {
      if (mask & (1 << gap)) {
        sizes.push(run);
        run = 1;
      } else {
        run += 1;
      }
    }
    sizes.push(run);
    yield sizes;
  }
}

/** Arrange `families` in rows for a tile of `availW` x `availH` px. */
export function packFamilies(families: PedigreeFamily[], options: PackOptions): Packing {
  const rowGap = options.rowGap ?? 8;
  const empty: Packing = { rows: [], contentW: 0, contentH: 0, scale: 1 };
  if (families.length === 0) return empty;

  const lay = { labelSpace: options.labelSpace };
  const gap = DEFAULT_LAYOUT.familyGap * DEFAULT_LAYOUT.slot;
  // One family at a time: its own width and how many generations it needs.
  const boxes: FamilyBox[] = families.map((family) => {
    const one = layoutPedigree([family], lay);
    return { width: one.width, height: one.height };
  });

  const measure = (sizes: number[]) => {
    let w = 0;
    let h = 0;
    let at = 0;
    for (const size of sizes) {
      const slice = boxes.slice(at, at + size);
      at += size;
      const rowW = slice.reduce((sum, b) => sum + b.width, 0) + gap * (slice.length - 1);
      w = Math.max(w, rowW);
      h += Math.max(...slice.map((b) => b.height)) + rowGap;
    }
    return {
      contentW: options.gutter + options.padX * 2 + w,
      contentH: h - rowGap + options.padBottom,
    };
  };

  let best: { sizes: number[]; contentW: number; contentH: number; scale: number } | null = null;
  for (const sizes of splits(families.length)) {
    const { contentW, contentH } = measure(sizes);
    const scale = fitScale({
      contentW,
      contentH,
      availW: options.availW,
      availH: options.availH,
    });
    // Strictly better only: the first split of a tie has the fewest rows
    // (mask 0, one row, comes first; later ties are longer in rows or not).
    const better =
      best === null ||
      scale > best.scale + 1e-9 ||
      (Math.abs(scale - best.scale) <= 1e-9 && sizes.length < best.sizes.length);
    if (better) best = { sizes, contentW, contentH, scale };
  }
  const chosen = best!;

  const rows: PackedRow[] = [];
  let at = 0;
  let y = 0;
  for (const size of chosen.sizes) {
    const slice = families.slice(at, at + size);
    at += size;
    const layout = layoutPedigree(slice, lay);
    rows.push({ families: slice, layout, y });
    y += layout.height + rowGap;
  }
  return { rows, contentW: chosen.contentW, contentH: chosen.contentH, scale: chosen.scale };
}
