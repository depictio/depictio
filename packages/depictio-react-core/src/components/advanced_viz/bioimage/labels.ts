// Segmentation-mask (labels) helpers for the bioimage viewer, kept free of
// deck.gl and viv so they unit-test in node and stay out of the lazy chunk's
// critical path. A label store is a multiscale integer image: each pixel holds
// a cell id (0 = background) equal to the points table's `cell_id_col`, which
// is how a cell's colour, filter state and selection reach its pixels.

import { sampleColorscale } from '../../../utils/colorScale';
import { looksContinuous } from '../colourScales';
import type { Rgb } from './channels';

/** A labels / image store as the stores listing returns it (subset). */
export interface PairableStore {
  name: string;
  sample: string;
}

/**
 * The labels store to draw over `image`: the one naming the same sample.
 * With no sample match, a DC holding a single labels store pairs with a DC
 * holding a single image (the one-image dashboard, whatever the file names).
 */
export function pairLabelsStore<T extends PairableStore>(
  labels: readonly T[] | null | undefined,
  image: PairableStore | null | undefined,
  imageCount: number,
): T | null {
  if (!labels || labels.length === 0 || !image) return null;
  const bySample = labels.find((s) => s.sample === image.sample);
  if (bySample) return bySample;
  if (labels.length === 1 && imageCount === 1) return labels[0];
  return null;
}

/** How one cell is drawn. */
export interface LabelStyle {
  color: Rgb;
  /** Excluded by the dashboard filters: drawn faint. */
  faded: boolean;
  /** In the viewer's own selection: drawn with the accent outline. */
  selected: boolean;
}

/** Cell id to style, plus the style of labels the table does not list. */
export interface LabelLut {
  styles: Map<number, LabelStyle>;
  /** The table's id for each label (its original spelling, for the filter). */
  ids: Map<number, string>;
  /** Labels absent from `styles`; null leaves them undrawn. */
  unknown: LabelStyle | null;
}

/** A cell as the points overlay describes it. */
export interface LabelCell {
  /** The id the selection filters on. */
  id: string;
  /** The mask value, when it differs from `id` (a cell id unique per sample
   *  while `id` is a sample:cell key). */
  label?: string;
  color: Rgb;
  faded: boolean;
}

/** The integer a cell id names in the mask, or null when it names none. */
export function labelOf(id: unknown): number | null {
  if (id === null || id === undefined || id === '') return null;
  const n = Number(id);
  return Number.isInteger(n) && n > 0 && n <= 0xffffffff ? n : null;
}

export function buildLabelLut(
  cells: readonly LabelCell[],
  selected: ReadonlySet<string>,
  unknown: LabelStyle | null,
): LabelLut {
  const styles = new Map<number, LabelStyle>();
  const ids = new Map<number, string>();
  for (const cell of cells) {
    const label = labelOf(cell.label ?? cell.id);
    if (label === null || styles.has(label)) continue;
    styles.set(label, { color: cell.color, faded: cell.faded, selected: selected.has(cell.id) });
    ids.set(label, cell.id);
  }
  return { styles, ids, unknown };
}

export interface LabelPaint {
  /** Fill opacity, 0..1 (`labels_opacity`). */
  opacity: number;
  /** Draw each cell's boundary at full opacity. */
  outline: boolean;
  /** Outline colour of selected cells (the theme's primary colour). */
  accent: Rgb;
}

/** Share of the fill / outline alpha a faded cell keeps. */
const FADED_FILL = 0.2;
const FADED_EDGE = 0.3;

/**
 * RGBA pixels of one label tile (`width` x `height`, row-major).
 *
 * Background (0) and unstyled labels stay transparent. A pixel is on a cell's
 * edge when a 4-neighbour inside the tile holds another label; edges are drawn
 * opaque when `outline` is on, and in the accent for a selected cell whatever
 * `outline` says, so a selection always shows. Consecutive pixels mostly share
 * a label, so the last lookup is reused.
 */
export function colorizeLabels(
  data: ArrayLike<number>,
  width: number,
  height: number,
  lut: LabelLut,
  paint: LabelPaint,
  out: Uint8ClampedArray = new Uint8ClampedArray(width * height * 4),
): Uint8ClampedArray {
  const fill = Math.max(0, Math.min(1, paint.opacity)) * 255;
  let lastLabel = -1;
  let lastStyle: LabelStyle | null = null;
  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    for (let x = 0; x < width; x += 1) {
      const i = row + x;
      const o = i * 4;
      const label = data[i];
      if (label !== lastLabel) {
        lastLabel = label;
        lastStyle = label === 0 ? null : (lut.styles.get(label) ?? lut.unknown);
      }
      const style = lastStyle;
      if (!style) {
        out[o + 3] = 0;
        continue;
      }
      const edge =
        (paint.outline || style.selected) &&
        ((x > 0 && data[i - 1] !== label) ||
          (x < width - 1 && data[i + 1] !== label) ||
          (y > 0 && data[i - width] !== label) ||
          (y < height - 1 && data[i + width] !== label));
      const [r, g, b] = edge && style.selected ? paint.accent : style.color;
      out[o] = r;
      out[o + 1] = g;
      out[o + 2] = b;
      if (edge) {
        out[o + 3] = style.faded && !style.selected ? 255 * FADED_EDGE : 255;
      } else {
        const a = style.selected ? Math.max(fill, 255 * 0.6) : fill;
        out[o + 3] = style.faded && !style.selected ? a * FADED_FILL : a;
      }
    }
  }
  return out;
}

/** One loaded tile of a label pyramid. */
export interface LabelTile {
  data: ArrayLike<number>;
  width: number;
  height: number;
}

/** Cache key of the tile at pyramid `level` (0 = full resolution), column `x`, row `y`. */
export function labelTileKey(level: number, x: number, y: number): string {
  return `${level}/${x}/${y}`;
}

/**
 * The label under level-0 pixel (`px`, `py`), read from the finest loaded
 * tile that covers it, or null when no loaded tile does. Coarser levels keep
 * every second pixel of the finer one, so they name the same cell except
 * along its edges.
 */
export function labelAt(
  tiles: ReadonlyMap<string, LabelTile>,
  px: number,
  py: number,
  tileSize: number,
  levels: number,
): number | null {
  if (!(px >= 0 && py >= 0)) return null;
  for (let level = 0; level < levels; level += 1) {
    const scale = 2 ** level;
    const lx = Math.floor(px / scale);
    const ly = Math.floor(py / scale);
    const tx = Math.floor(lx / tileSize);
    const ty = Math.floor(ly / tileSize);
    const tile = tiles.get(labelTileKey(level, tx, ty));
    if (!tile) continue;
    const ix = lx - tx * tileSize;
    const iy = ly - ty * tileSize;
    if (ix >= tile.width || iy >= tile.height) return null;
    return Number(tile.data[iy * tile.width + ix]);
  }
  return null;
}

/** How a `color_col` colours cells: swatches per value, or a ramp over a range. */
export type CellColouring =
  | { kind: 'categorical' }
  | { kind: 'continuous'; min: number; max: number; scale: string };

/** The continuous colour scale cells use for a numeric `color_col`. */
export const CELL_COLOUR_SCALE = 'Viridis';

/** Continuous when the values look like a measurement (see `looksContinuous`). */
export function cellColouring(values: readonly unknown[]): CellColouring {
  if (!looksContinuous(values as unknown[])) return { kind: 'categorical' };
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v === null || v === undefined || v === '') continue;
    const n = Number(v);
    if (n < min) min = n;
    if (n > max) max = n;
  }
  return { kind: 'continuous', min, max, scale: CELL_COLOUR_SCALE };
}

/** The ramp colour of `value`, or null for a missing / non-numeric value. */
export function rampColor(
  colouring: Extract<CellColouring, { kind: 'continuous' }>,
  value: unknown,
): Rgb | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const span = colouring.max - colouring.min;
  const t = span > 0 ? (n - colouring.min) / span : 0.5;
  return sampleColorscale(colouring.scale, t) as Rgb;
}

/** CSS gradient of a ramp, for its legend bar. */
export function rampGradient(scale: string, steps = 6): string {
  const stops = Array.from({ length: steps }, (_, i) => {
    const [r, g, b] = sampleColorscale(scale, i / (steps - 1));
    return `rgb(${r}, ${g}, ${b}) ${Math.round((i / (steps - 1)) * 100)}%`;
  });
  return `linear-gradient(to right, ${stops.join(', ')})`;
}
