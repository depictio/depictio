/**
 * Declared initial state of interactive filters.
 *
 * A dashboard YAML can give a filter a `default_value` (Select, MultiSelect,
 * SegmentedControl, Slider, Checkbox / Switch) or a `default_range`
 * (RangeSlider, DateRangePicker). Both reach the viewer as the stored
 * component's `default_state`. They used to be ignored: the viewer's filter
 * state started empty, so a tab meant to open on "Q10 reads" opened on
 * everything. `withInteractiveDefaults` turns them into filter entries, in the
 * value shape each renderer emits, so the first render is already filtered.
 */
import type { InteractiveFilter, StoredMetadata } from './api';

const RANGE_TYPES = new Set(['RangeSlider', 'DateRangePicker', 'DatePicker']);
const LIST_TYPES = new Set(['Select', 'MultiSelect']);

/** The filter value a renderer would emit for this component's declared
 *  default, or `undefined` when it declares none (or one that cannot apply). */
export function defaultFilterValue(m: StoredMetadata): unknown {
  const state = (m.default_state ?? {}) as { default_value?: unknown; default_range?: unknown };
  const kind = m.interactive_component_type ?? '';
  if (RANGE_TYPES.has(kind)) {
    const r = state.default_range;
    if (!Array.isArray(r) || r.length !== 2) return undefined;
    if (kind === 'RangeSlider') {
      const [lo, hi] = r.map(Number);
      return Number.isFinite(lo) && Number.isFinite(hi) ? [lo, hi] : undefined;
    }
    return [r[0] == null ? null : String(r[0]), r[1] == null ? null : String(r[1])];
  }
  const v = state.default_value;
  if (v === undefined || v === null) return undefined;
  // Select renders through the MultiSelect renderer, which emits string[].
  if (LIST_TYPES.has(kind)) {
    const list = (Array.isArray(v) ? v : [v]).map(String);
    return list.length ? list : undefined;
  }
  if (kind === 'Slider') {
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  }
  if (kind === 'Checkbox' || kind === 'Switch') {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') return v.toLowerCase() === 'true';
    return Boolean(v);
  }
  if (kind === 'SegmentedControl') return String(v);
  return undefined;
}

/** `filters` plus one entry per interactive component that declares a default
 *  and has no entry of its own yet. Existing entries (hydrated cross-tab values,
 *  a user's choice, an explicit reset) always win. */
export function withInteractiveDefaults(
  filters: InteractiveFilter[],
  metadataList: StoredMetadata[] | undefined,
): InteractiveFilter[] {
  const present = new Set(filters.filter((f) => f.source === undefined).map((f) => f.index));
  const added: InteractiveFilter[] = [];
  for (const m of metadataList ?? []) {
    if (m.component_type !== 'interactive' || present.has(m.index)) continue;
    const value = defaultFilterValue(m);
    if (value === undefined) continue;
    present.add(m.index);
    added.push({
      index: m.index,
      value,
      column_name: m.column_name,
      interactive_component_type: m.interactive_component_type,
      ...(m.filter_expr ? { filter_expr: m.filter_expr } : {}),
      metadata: {
        dc_id: m.dc_id,
        column_name: m.column_name,
        interactive_component_type: m.interactive_component_type,
        ...(m.slider_mode ? { slider_mode: m.slider_mode } : {}),
      },
    });
  }
  return added.length ? [...filters, ...added] : filters;
}
