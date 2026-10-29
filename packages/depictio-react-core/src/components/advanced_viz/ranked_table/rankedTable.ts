/**
 * The arithmetic of a ranked table, kept out of the renderer so it is tested
 * without a DOM: ordering with ties, dense ranks, the medal a rank earns, how
 * far a bar is filled, which colour a badge wears, how a cell reads as text and
 * where a popover sits.
 *
 * Mirrors `RankedTableConfig` in
 * depictio/models/components/advanced_viz/configs.py.
 */
import { NEUTRAL_CATEGORY_COLOR, categoryColorMap, type CategoryColorSource } from '../../../categoryColors';

export type CellDisplay = 'text' | 'mono' | 'badge' | 'bar' | 'number';

/** One extra column, as the config states it (`RankedTableColumn`). */
export interface RankedTableColumnSpec {
  column: string;
  label?: string | null;
  display?: CellDisplay;
  decimals?: number | null;
  min?: number | null;
  max?: number | null;
}

/** The columns the ranking itself reads (the bound roles). */
export interface RankedTableBindings {
  title: string;
  score: string;
  subtitle?: string | null;
  rank?: string | null;
}

/** Column-oriented rows, as `fetchAdvancedVizData` returns them. */
export type ColumnarRows = Record<string, unknown[]>;

export interface RankedRow {
  /** Position of the row in the fetched frame; the key to every other column. */
  source: number;
  /** The score the row is ordered by. */
  score: number;
  /** The rank shown in the medal: the rank column's value, else the dense rank. */
  rank: number | string;
  /** The medal tier 1 to 3, or null; read off `rank` when it is a number. */
  tier: RankTier | null;
}

export type RankTier = 1 | 2 | 3;

export interface RankedList {
  /** The rows drawn, best first, at most `topN`. */
  rows: RankedRow[];
  /** Rows with a score, i.e. everything that was ranked. */
  ranked: number;
  /** Rows left out because their score is missing or not a number. */
  unscored: number;
}

/** A finite number from a cell, or null: numeric strings read, blanks do not. */
export function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'bigint') return Number(value);
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** The medal a rank earns: 1, 2 or 3 for those ranks, else none. */
export function rankTier(rank: number | string | null | undefined): RankTier | null {
  const n = typeof rank === 'number' ? rank : toNumber(rank);
  return n === 1 || n === 2 || n === 3 ? n : null;
}

/**
 * Dense ranks of already-ordered scores: 1, 1, 2, 3, 3, 4. Rows that tie share
 * a rank and the next distinct score follows without a gap, so the medals go to
 * the three best scores rather than to however many rows tie at the top.
 */
export function denseRanks(orderedScores: readonly number[]): number[] {
  const out: number[] = [];
  let rank = 0;
  let previous: number | undefined;
  for (const score of orderedScores) {
    if (previous === undefined || score !== previous) rank += 1;
    out.push(rank);
    previous = score;
  }
  return out;
}

/** The rank cell of a row: the precomputed rank when one is bound and holds a
 *  value, else the dense rank. */
function shownRank(raw: unknown, dense: number): number | string {
  const numeric = toNumber(raw);
  if (numeric !== null) return numeric;
  if (typeof raw === 'string' && raw.trim() !== '') return raw.trim();
  return dense;
}

/**
 * Order the frame by score and keep the best `topN`.
 *
 * The sort is stable, so rows that tie keep the order they arrived in. A row
 * with no usable score is not ranked (it would sort anywhere) and is counted
 * in `unscored` instead.
 */
export function rankRows(
  rows: ColumnarRows,
  bindings: Pick<RankedTableBindings, 'score' | 'rank'>,
  options: { descending: boolean; topN: number },
): RankedList {
  const scores = rows[bindings.score] ?? [];
  const n = Math.max(...Object.values(rows).map((c) => c.length), 0);
  const scored: { source: number; score: number }[] = [];
  for (let i = 0; i < n; i += 1) {
    const score = toNumber(scores[i]);
    if (score !== null) scored.push({ source: i, score });
  }
  const direction = options.descending ? -1 : 1;
  scored.sort((a, b) => direction * (a.score - b.score) || a.source - b.source);

  const dense = denseRanks(scored.map((r) => r.score));
  const rankColumn = bindings.rank ? rows[bindings.rank] : undefined;
  const limit = Math.max(0, Math.floor(options.topN));
  const kept = scored.slice(0, limit).map(({ source, score }, i): RankedRow => {
    const rank = rankColumn ? shownRank(rankColumn[source], dense[i]) : dense[i];
    return { source, score, rank, tier: rankTier(rank) };
  });
  return { rows: kept, ranked: scored.length, unscored: n - scored.length };
}

/** The `top_n` a stored config or a control can hand over, kept in 1..max. */
export function clampTopN(value: unknown, fallback: number, max = 1000): number {
  const n = toNumber(value);
  if (n === null) return fallback;
  return Math.min(Math.max(1, Math.round(n)), max);
}

// ---------------------------------------------------------------------------
// Bars
// ---------------------------------------------------------------------------

/** The scale of a bar column: where it starts and where it is full. */
export interface BarRange {
  lo: number;
  hi: number;
}

/**
 * The range a bar column is drawn on. A bound the config states wins. A bar
 * starts at 0 (a score of 12 is half of a score of 24) unless a value shown is
 * negative, when it starts at the smallest; it is full at the largest shown.
 * A degenerate range (one value, or all equal) is widened so every bar is
 * full rather than undefined.
 */
export function barRange(
  values: readonly (number | null)[],
  spec: Pick<RankedTableColumnSpec, 'min' | 'max'> = {},
): BarRange {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  const dataMin = finite.length ? Math.min(...finite) : 0;
  const dataMax = finite.length ? Math.max(...finite) : 0;
  const lo = spec.min ?? Math.min(0, dataMin);
  let hi = spec.max ?? dataMax;
  if (hi <= lo) hi = lo + 1;
  return { lo, hi };
}

/** How much of the track a value fills, 0 to 1; a missing value fills none. */
export function barFraction(value: number | null, range: BarRange): number {
  if (value === null || !Number.isFinite(value)) return 0;
  const f = (value - range.lo) / (range.hi - range.lo);
  return Math.min(1, Math.max(0, f));
}

// ---------------------------------------------------------------------------
// Cells as text
// ---------------------------------------------------------------------------

/** What an empty cell reads. */
export const EMPTY_CELL = '–';

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || value === '' || (typeof value === 'number' && Number.isNaN(value));
}

/**
 * A cell as text. A number with `decimals` is fixed to them; without, it is
 * shortened to four significant digits so a score of 23.000001 reads 23. Text
 * (including a number written as text, like "absent" or "0.0004") is untouched.
 */
export function formatCell(value: unknown, decimals?: number | null): string {
  if (isBlank(value)) return EMPTY_CELL;
  if (typeof value === 'number' || typeof value === 'bigint') {
    const n = Number(value);
    if (!Number.isFinite(n)) return EMPTY_CELL;
    if (decimals !== null && decimals !== undefined) return n.toFixed(decimals);
    return Number.isInteger(n) ? String(n) : String(Number(n.toPrecision(4)));
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

/** The label a column carries: its own, else the config's `labels`, else its name. */
export function columnLabel(
  column: string,
  own?: string | null,
  labels?: Record<string, string> | null,
): string {
  return own || labels?.[column] || column;
}

/** The columns a spec names that the frame does not carry, in first-seen order. */
export function missingColumns(rows: ColumnarRows, wanted: readonly (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const column of wanted) {
    if (column && !(column in rows) && !out.includes(column)) out.push(column);
  }
  return out;
}

/** Every distinct column a table reads, once, in first-seen order. */
export function columnsToFetch(
  bindings: RankedTableBindings,
  columns: readonly RankedTableColumnSpec[],
  popover: readonly string[],
  grid: readonly string[],
  selection?: string | null,
): string[] {
  const all = [
    bindings.title,
    bindings.score,
    bindings.subtitle,
    bindings.rank,
    ...columns.map((c) => c.column),
    ...popover,
    ...grid,
    selection,
  ];
  return all.filter((c, i): c is string => Boolean(c) && all.indexOf(c) === i);
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

/**
 * The colour of each value of a badge column: the dashboard's pin for it
 * (`category_colors`, own or inherited), else the palette's hue for its place
 * in the sorted universe, else a neutral grey. The universe is every value the
 * frame holds, not the top N drawn, so a value keeps its hue when the cut moves.
 */
export function badgeColourOf(
  source: CategoryColorSource | null | undefined,
  column: string,
  universe: readonly unknown[],
  palette: readonly string[] | null | undefined,
): (value: unknown) => string {
  const map = categoryColorMap(source, column, universe, palette);
  return (value) => (isBlank(value) ? NEUTRAL_CATEGORY_COLOR : (map.get(String(value)) ?? NEUTRAL_CATEGORY_COLOR));
}

// ---------------------------------------------------------------------------
// Popover
// ---------------------------------------------------------------------------

export interface PopoverPlacement {
  left: number;
  top: number;
}

/**
 * Where a popover of `width` x `height` sits for a pointer at (x, y): to the
 * right and below, flipped to the other side when it would leave the viewport,
 * and held inside it with `margin` to spare.
 */
export function placePopover(
  pointer: { x: number; y: number },
  size: { width: number; height: number },
  viewport: { width: number; height: number },
  options: { offset?: number; margin?: number } = {},
): PopoverPlacement {
  const offset = options.offset ?? 14;
  const margin = options.margin ?? 8;
  let left = pointer.x + offset;
  if (left + size.width > viewport.width - margin) left = pointer.x - offset - size.width;
  let top = pointer.y + offset;
  if (top + size.height > viewport.height - margin) top = pointer.y - offset - size.height;
  const maxLeft = Math.max(margin, viewport.width - size.width - margin);
  const maxTop = Math.max(margin, viewport.height - size.height - margin);
  return {
    left: Math.min(Math.max(margin, left), maxLeft),
    top: Math.min(Math.max(margin, top), maxTop),
  };
}

/** The echo under the title: what is drawn of what was ranked, and by which end. */
export function rankedEcho(args: {
  shown: number;
  ranked: number;
  scoreLabel: string;
  descending: boolean;
}): string {
  const of = args.ranked > args.shown ? ` of ${args.ranked.toLocaleString('en-US')}` : '';
  return `top ${args.shown.toLocaleString('en-US')}${of} by ${args.scoreLabel} (${args.descending ? 'highest' : 'lowest'} first)`;
}
