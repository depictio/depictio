/**
 * Which extra field each card `secondary_layout` requires.
 *
 * Mirrors `Render._check_component` in
 * `depictio/models/components/advanced_viz/catalog.py` — the authority. A card
 * that omits its layout's companion field is rejected by `dev catalog validate`,
 * so we check it client-side too rather than letting the contributor discover it
 * in CI.
 *
 * The Record is deliberately exhaustive over the generated `SecondaryLayout`
 * union: when depictio adds a layout, `genkinds` picks it up in
 * `generated/cardSpec.ts` and this file stops compiling until someone says what
 * the new layout needs. That is the drift guard — the previous hand-copied
 * union just silently lagged behind.
 */
import type { CardRender } from '../types';
import type { SecondaryLayout } from './generated/cardSpec';

/** Card fields that exist only to satisfy a particular layout. */
export type CardCompanionField =
  | 'breakdown_col'
  | 'coverage_max'
  | 'threshold_value'
  | 'attrition_cols'
  | 'trend_col';

export const LAYOUT_REQUIRES: Record<SecondaryLayout, CardCompanionField | null> = {
  vertical: null,
  compact: null,
  grid: null,
  box_plot: null,
  histogram: null,
  completeness: null,
  uniqueness: null,
  top_n: 'breakdown_col',
  concentration: 'breakdown_col',
  composition: 'breakdown_col',
  donut: 'breakdown_col',
  coverage: 'coverage_max',
  gauge: 'coverage_max',
  threshold: 'threshold_value',
  attrition: 'attrition_cols',
  trend: 'trend_col',
};

/** Human-readable label for the field a layout is missing. */
const FIELD_LABEL: Record<CardCompanionField, string> = {
  breakdown_col: 'a breakdown column',
  coverage_max: 'a coverage maximum',
  threshold_value: 'a threshold value',
  attrition_cols: 'at least one attrition stage',
  trend_col: 'a trend column',
};

function isSet(render: CardRender, field: CardCompanionField): boolean {
  const value = render[field];
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'number') return Number.isFinite(value);
  return Boolean(value);
}

/**
 * The companion field this card still needs, or null when it is complete.
 * Cards with no `secondary_layout` are plain single-metric cards — nothing extra.
 */
export function missingCardField(render: CardRender): CardCompanionField | null {
  if (!render.secondary_layout) return null;
  const required = LAYOUT_REQUIRES[render.secondary_layout];
  if (!required) return null;
  return isSet(render, required) ? null : required;
}

/** `missingCardField` as a sentence, for the render list / export blockers. */
export function cardLayoutProblem(render: CardRender): string | null {
  const missing = missingCardField(render);
  if (!missing) return null;
  return `Layout '${render.secondary_layout}' needs ${FIELD_LABEL[missing]} (\`${missing}\`).`;
}
