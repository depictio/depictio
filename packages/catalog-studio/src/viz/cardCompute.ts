/**
 * Client-side card aggregations. depictio computes these server-side (bulk
 * compute endpoint); we recompute in JS purely for the preview. Aggregation
 * NAMES match the catalog schema enum (note: `average`, not `mean`).
 */
import type { Aggregation } from '../types';

function toNumbers(rows: Record<string, unknown>[], column: string): number[] {
  const out: number[] = [];
  for (const row of rows) {
    const v = row[column];
    if (v === null || v === undefined || v === '') continue;
    const n = typeof v === 'number' ? v : Number(v);
    if (Number.isFinite(n)) out.push(n);
  }
  return out;
}

function median(sorted: number[]): number {
  const n = sorted.length;
  if (n === 0) return NaN;
  const mid = Math.floor(n / 2);
  return n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function computeCard(
  rows: Record<string, unknown>[],
  column: string,
  aggregation: Aggregation,
): number | string {
  // count / nunique / mode work on any column; the rest are numeric.
  if (aggregation === 'count') return rows.filter((r) => r[column] !== '' && r[column] != null).length;
  if (aggregation === 'nunique') {
    return new Set(rows.map((r) => r[column]).filter((v) => v !== '' && v != null)).size;
  }
  if (aggregation === 'mode') {
    const freq = new Map<unknown, number>();
    for (const r of rows) {
      const v = r[column];
      if (v === '' || v == null) continue;
      freq.set(v, (freq.get(v) ?? 0) + 1);
    }
    let best: unknown = '—';
    let bestN = -1;
    for (const [v, n] of freq) {
      if (n > bestN) {
        best = v;
        bestN = n;
      }
    }
    return String(best);
  }

  const nums = toNumbers(rows, column);
  if (nums.length === 0) return NaN;
  const sum = nums.reduce((a, b) => a + b, 0);
  switch (aggregation) {
    case 'sum':
      return round(sum);
    case 'average':
      return round(sum / nums.length);
    case 'min':
      return Math.min(...nums);
    case 'max':
      return Math.max(...nums);
    case 'range':
      return round(Math.max(...nums) - Math.min(...nums));
    case 'median':
      return round(median([...nums].sort((a, b) => a - b)));
    case 'variance': {
      const mean = sum / nums.length;
      return round(nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length);
    }
    case 'std_dev': {
      const mean = sum / nums.length;
      return round(Math.sqrt(nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length));
    }
    default:
      return NaN;
  }
}

function round(n: number): number {
  if (Number.isInteger(n)) return n;
  return Math.round(n * 1e4) / 1e4;
}

/** Aggregations Catalog Studio can preview client-side (subset of the schema). */
export const CLIENT_AGGREGATIONS: Aggregation[] = [
  'count',
  'sum',
  'average',
  'median',
  'min',
  'max',
  'range',
  'variance',
  'std_dev',
  'nunique',
  'mode',
];
