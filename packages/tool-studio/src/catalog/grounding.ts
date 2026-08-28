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
import { cardLayoutProblem } from './cardRules';

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
/** Roles that bind an ordered LIST of columns instead of one, and roles that
 *  pick a setting rather than a column. Mirrors `_LIST_ROLES` /
 *  `_NON_COLUMN_ROLES` in `models/components/advanced_viz/catalog.py`: the kind
 *  descriptors only describe the column roles, so these have to be named. */
const LIST_ROLES: Record<string, string[]> = {
  sankey: ['steps'],
  sunburst: ['ranks'],
  complex_heatmap: ['value_columns', 'row_annotation_cols'],
};

const SETTING_ROLES: Record<string, string[]> = {
  embedding: ['compute_method'],
};

export function boundColumns(render: RenderSpec): string[] {
  const cols = new Set<string>();
  if (render.component === 'advanced_viz') {
    for (const [role, value] of Object.entries(render.roles)) {
      if (SETTING_ROLES[render.kind]?.includes(role)) continue;
      if (Array.isArray(value)) value.forEach((c) => c && cols.add(c));
      else if (value) cols.add(value);
    }
  } else if (render.component === 'figure') {
    // Code-mode figures bind columns inside the snippet — nothing to ground here.
    for (const k of FIGURE_COLUMN_KWARGS) {
      const v = render.dict_kwargs?.[k];
      if (v) cols.add(v);
    }
  } else if (render.component === 'card') {
    // Mirrors Render.bound_columns() in the catalog model — trend/attrition
    // layouts bind extra columns and must be grounded like the rest.
    if (render.column) cols.add(render.column);
    if (render.breakdown_col) cols.add(render.breakdown_col);
    if (render.trend_col) cols.add(render.trend_col);
    render.attrition_cols?.forEach((c) => c && cols.add(c));
  } else if (render.component === 'interactive') {
    if (render.column_name) cols.add(render.column_name);
  } else if (render.component === 'table') {
    render.columns?.forEach((c) => c && cols.add(c));
    if (render.row_selection_column) cols.add(render.row_selection_column);
  }
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

  // Each secondary_layout has a companion field the catalog model requires;
  // surface it here rather than letting the contributor find it in CI.
  if (render.component === 'card') {
    const problem = cardLayoutProblem(render);
    if (problem) {
      issues.push({ renderUid: render.uid, severity: 'error', message: problem });
    }
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
    // Unknown role names. The kind descriptor carries the column roles; the
    // list and setting roles a few kinds bind are named here because they are
    // config fields rather than entries in the role/dtype table.
    const extraRoles = [
      ...(LIST_ROLES[render.kind] ?? []),
      ...(SETTING_ROLES[render.kind] ?? []),
    ];
    for (const role of Object.keys(render.roles)) {
      if (render.roles[role] && !desc.roles[role] && !extraRoles.includes(role)) {
        issues.push({
          renderUid: render.uid,
          severity: 'error',
          message: `Role "${role}" is not valid for ${render.kind}. Valid: ${[...Object.keys(desc.roles), ...extraRoles].join(', ') || 'none'}.`,
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
    // A sankey with fewer than 2 steps cannot be built — `SankeyConfig` needs
    // them and nothing downstream can infer them (the catalog model rejects it
    // too, so this is the same check, made while the render is authored).
    if (render.kind === 'sankey') {
      const steps = render.roles.steps;
      if (!Array.isArray(steps) || steps.length < 2) {
        issues.push({
          renderUid: render.uid,
          severity: 'error',
          message: 'sankey needs at least 2 step columns.',
        });
      }
    }
    // Dtype compatibility per bound role.
    for (const [role, value] of Object.entries(render.roles)) {
      const accepted = desc.roles[role];
      if (!accepted) continue;
      for (const col of Array.isArray(value) ? value : [value]) {
        const column = colByName.get(col);
        if (column && !accepted.includes(column.dtype)) {
          issues.push({
            renderUid: render.uid,
            severity: 'warning',
            message: `Role "${role}" expects ${accepted.join('/')}, but "${col}" is ${column.dtype}.`,
          });
        }
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
