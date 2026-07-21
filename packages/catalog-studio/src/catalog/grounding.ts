/**
 * Client-side grounding + role validation — UX feedback ONLY. The authoritative
 * validator is the CI `depictio dev catalog lint`/`validate`, which grounds the
 * bound columns against the committed fixture. Here we mirror
 * `Render.bound_columns` (depictio/models/.../catalog.py) so the designer can
 * flag a binding that references a column the CSV doesn't have, or a role/dtype
 * the kind doesn't accept, before the user exports.
 */
import {
  FIGURE_COLUMN_KWARGS,
  type FixtureColumn,
  type KindsMap,
  type RenderSpec,
} from '../types';

export interface GroundingIssue {
  renderUid: string;
  severity: 'error' | 'warning';
  message: string;
}

// Aggregations that only make sense on a numeric column (min/max/count/nunique/
// mode work on any dtype). Kept in sync with `_NUMERIC_AGGREGATIONS` in
// depictio/models/.../catalog.py.
const NUMERIC_AGGREGATIONS = new Set([
  'sum',
  'average',
  'median',
  'range',
  'variance',
  'std_dev',
  'percentile',
  'skewness',
  'kurtosis',
]);
const NUMERIC_DTYPES = new Set([
  'Int8',
  'Int16',
  'Int32',
  'Int64',
  'UInt8',
  'UInt16',
  'UInt32',
  'UInt64',
  'Float32',
  'Float64',
]);

/** Columns a render binds — the set that must be ⊆ the fixture columns. */
export function boundColumns(render: RenderSpec): string[] {
  const cols = new Set<string>();
  if (render.component === 'advanced_viz') {
    Object.values(render.roles).forEach((c) => c && cols.add(c));
  } else if (render.component === 'figure') {
    // Code-mode figures bind columns inside the snippet — nothing to ground here.
    for (const k of FIGURE_COLUMN_KWARGS) {
      const v = render.dict_kwargs?.[k];
      if (v) cols.add(v);
    }
  } else if (render.component === 'card') {
    if (render.column) cols.add(render.column);
    if (render.breakdown_col) cols.add(render.breakdown_col);
  }
  // interactive + table bind no columns in the catalog (component-only renders).
  return [...cols];
}

/**
 * Validate one render against the fixture columns + (for advanced_viz) the
 * kinds map. Returns zero or more issues. An empty array means "looks bindable".
 */
export function validateRender(
  render: RenderSpec,
  columns: FixtureColumn[],
  kinds: KindsMap,
): GroundingIssue[] {
  const issues: GroundingIssue[] = [];
  const colByName = new Map(columns.map((c) => [c.name, c]));

  // Grounding: every bound column must exist in the fixture.
  for (const col of boundColumns(render)) {
    if (!colByName.has(col)) {
      issues.push({
        renderUid: render.uid,
        severity: 'error',
        message: `Column "${col}" is not in the fixture.`,
      });
    }
  }

  if (render.component === 'figure' && !render.code) {
    // A figure needs at least an x (or a heatmap needs x+y+color, but keep the
    // client check lenient — CI is authoritative). Code-mode figures are exempt.
    if (!render.dict_kwargs?.x && !render.dict_kwargs?.names) {
      issues.push({
        renderUid: render.uid,
        severity: 'warning',
        message: 'Figure has no x binding.',
      });
    }
  }

  if (render.component === 'card' && !render.aggregation) {
    issues.push({
      renderUid: render.uid,
      severity: 'error',
      message: 'Card needs an aggregation.',
    });
  }

  // Card numeric aggregations require a numeric column (mirrors CI's
  // `ground_render_dtypes`). count/nunique/min/max work on any dtype.
  if (render.component === 'card' && render.aggregation && render.column) {
    const col = colByName.get(render.column);
    const aggs = [render.aggregation, ...(render.aggregations ?? [])];
    for (const agg of aggs) {
      if (agg && NUMERIC_AGGREGATIONS.has(agg) && col && !NUMERIC_DTYPES.has(col.dtype)) {
        issues.push({
          renderUid: render.uid,
          severity: 'error',
          message: `Aggregation "${agg}" needs a numeric column, but "${render.column}" is ${col.dtype}.`,
        });
      }
    }
  }

  if (render.component === 'advanced_viz') {
    const desc = kinds[render.kind];
    if (!desc) {
      issues.push({
        renderUid: render.uid,
        severity: 'error',
        message: `Unknown viz kind "${render.kind}".`,
      });
      return issues;
    }
    // Unknown role names.
    for (const role of Object.keys(render.roles)) {
      if (render.roles[role] && !desc.roles[role]) {
        issues.push({
          renderUid: render.uid,
          severity: 'error',
          message: `Role "${role}" is not valid for ${render.kind}. Valid: ${Object.keys(desc.roles).join(', ') || '—'}.`,
        });
      }
    }
    // Missing required roles.
    for (const role of desc.required_roles) {
      if (!render.roles[role]) {
        issues.push({
          renderUid: render.uid,
          severity: 'error',
          message: `${render.kind} requires role "${role}".`,
        });
      }
    }
    // Dtype compatibility per bound role.
    for (const [role, col] of Object.entries(render.roles)) {
      const accepted = desc.roles[role];
      const column = colByName.get(col);
      if (accepted && column && !accepted.includes(column.dtype)) {
        issues.push({
          renderUid: render.uid,
          severity: 'warning',
          message: `Role "${role}" expects ${accepted.join('/')}, but "${col}" is ${column.dtype}.`,
        });
      }
    }
  }

  return issues;
}

/** All issues across all renders, flattened. */
export function validateAll(
  renders: RenderSpec[],
  columns: FixtureColumn[],
  kinds: KindsMap,
): GroundingIssue[] {
  return renders.flatMap((r) => validateRender(r, columns, kinds));
}
