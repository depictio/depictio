/**
 * Map the parsed fixture into depictio's builder `ColumnSpec[]` shape
 * ({ name, type, specs }). `type` is the fixture dtype string — depictio's
 * `aggFunctions.normalizeType` already maps 'Int64'→int64, 'String'→utf8, etc.
 * `specs` carries the precomputed per-column stats that `CardPreview` reads by
 * aggregation name (count/nunique/sum/average/median/min/max/range/variance/
 * std_dev/mode + a `unique_values` sample for breakdown previews) so the reused
 * depictio card builder shows real values with no backend.
 */
import type { ColumnSpec } from 'depictio-builder/store/useBuilderStore';
import type { FixtureColumn, ParsedFixture } from '../types';
import { computeCard } from '../viz/cardCompute';

const NUMERIC_KEYS = [
  'sum',
  'average',
  'median',
  'min',
  'max',
  'range',
  'variance',
  'std_dev',
] as const;

function computeSpecs(rows: Record<string, unknown>[], col: FixtureColumn): Record<string, unknown> {
  const specs: Record<string, unknown> = {};
  specs.count = computeCard(rows, col.name, 'count');
  const nunique = computeCard(rows, col.name, 'nunique');
  specs.nunique = nunique;
  specs.unique = nunique; // depictio card method key alias
  specs.mode = computeCard(rows, col.name, 'mode');

  // Sample of distinct values (for top_n / concentration breakdown previews).
  const seen = new Set<string>();
  for (const r of rows) {
    const v = r[col.name];
    if (v === '' || v == null) continue;
    seen.add(String(v));
    if (seen.size >= 25) break;
  }
  specs.unique_values = [...seen];

  if (col.dtype === 'Int64' || col.dtype === 'Float64') {
    for (const k of NUMERIC_KEYS) {
      const v = computeCard(rows, col.name, k);
      if (typeof v === 'number' && Number.isFinite(v)) specs[k] = v;
    }
  }
  return specs;
}

export function fixtureToColumnSpecs(fixture: ParsedFixture): ColumnSpec[] {
  return fixture.columns.map((c) => ({
    name: c.name,
    type: c.dtype,
    specs: computeSpecs(fixture.rows, c),
  }));
}
