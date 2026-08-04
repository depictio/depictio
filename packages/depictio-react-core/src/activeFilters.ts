/**
 * Shared "is this filter actually filtering anything" semantics.
 *
 * The filter array keeps entries around after a user clears a control (the
 * renderers emit `value: []` rather than removing the entry), so a plain
 * `filters.length` overstates how much is active. Every affordance that
 * counts, badges or lists active filters must agree on the same emptiness
 * rules, which is why they live here rather than being re-derived per caller.
 */

import type { InteractiveFilter, StoredMetadata } from './api';

/** True when the filter carries a value that actually narrows the data. */
export function isFilterActive(filter: InteractiveFilter): boolean {
  const v = filter.value;
  if (v == null) return false;
  if (Array.isArray(v)) {
    if (v.length === 0) return false;
    // A range control that was reset emits [null, null].
    return v.some((item) => item != null);
  }
  if (typeof v === 'string') return v.length > 0;
  return true;
}

/** Active filters, restricted to the given components when one is supplied. */
export function activeFiltersFor(
  filters: InteractiveFilter[],
  components?: StoredMetadata[],
): InteractiveFilter[] {
  const active = filters.filter(isFilterActive);
  if (!components) return active;
  const indexes = new Set(components.map((c) => c.index));
  return active.filter((f) => indexes.has(f.index));
}

/** Count of active filters, restricted to the given components when supplied. */
export function countActiveFilters(
  filters: InteractiveFilter[],
  components?: StoredMetadata[],
): number {
  return activeFiltersFor(filters, components).length;
}

const MAX_INLINE_VALUES = 2;
const MAX_LABEL_CHARS = 28;

/**
 * Human-readable summary of a filter's value, sized for a chip.
 *
 * Lists collapse to "n selected" past a couple of entries; two-element numeric
 * or date arrays read as a range, which covers RangeSlider and DateRangePicker.
 */
export function formatFilterValue(filter: InteractiveFilter): string {
  const v = filter.value;
  if (v == null) return '';

  if (Array.isArray(v)) {
    const present = v.filter((item) => item != null);
    if (present.length === 0) return '';
    const isRange =
      present.length === 2 &&
      v.length === 2 &&
      present.every((item) => typeof item === 'number' || typeof item === 'string');
    if (isRange && isRangeControl(filter)) {
      return `${formatScalar(present[0])} – ${formatScalar(present[1])}`;
    }
    if (present.length <= MAX_INLINE_VALUES) {
      return truncate(present.map(formatScalar).join(', '));
    }
    return `${present.length} selected`;
  }

  return truncate(formatScalar(v));
}

/** Range-shaped controls render [a, b] as a span rather than a two-item list. */
function isRangeControl(filter: InteractiveFilter): boolean {
  const t = filter.interactive_component_type;
  return t === 'RangeSlider' || t === 'DateRangePicker' || t === 'DatePicker' || t === 'Timeline';
}

function formatScalar(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(2).replace(/\.?0+$/, '');
  }
  return String(v);
}

function truncate(s: string): string {
  return s.length > MAX_LABEL_CHARS ? `${s.slice(0, MAX_LABEL_CHARS - 1)}…` : s;
}

/** Label shown on a chip: the source component's title, or its column. */
export function filterDisplayLabel(
  filter: InteractiveFilter,
  components: StoredMetadata[],
): string {
  const meta = components.find((c) => c.index === filter.index);
  return (
    meta?.title ||
    filter.column_name ||
    meta?.column_name ||
    filter.metadata?.selection_column ||
    'Filter'
  );
}
