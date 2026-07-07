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

/** Columns a render binds — the set that must be ⊆ the fixture columns. */
export function boundColumns(render: RenderSpec): string[] {
  const cols = new Set<string>();
  if (render.component === 'advanced_viz') {
    Object.values(render.roles).forEach((c) => c && cols.add(c));
  } else if (render.component === 'figure') {
    for (const k of FIGURE_COLUMN_KWARGS) {
      const v = render.dict_kwargs[k];
      if (v) cols.add(v);
    }
  } else if (render.component === 'card') {
    if (render.column) cols.add(render.column);
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

  if (render.component === 'figure') {
    // A figure needs at least an x (or a heatmap needs x+y+color, but keep the
    // client check lenient — CI is authoritative).
    if (!render.dict_kwargs.x && !render.dict_kwargs.names) {
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
