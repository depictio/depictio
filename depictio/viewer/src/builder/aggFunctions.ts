/**
 * Per-column-type capabilities for the React component builder.
 * Mirrors the two Dash source-of-truth dicts:
 *  - depictio/api/v1/utils.py:agg_functions      (card_methods)
 *  - depictio/dash/modules/interactive_component/utils.py:agg_functions
 *    (input_methods — interactive variants per type)
 *
 * Keep the two TS maps in sync with those files. Both `cardMethods` and
 * `inputMethods` are filtered by the column type the user picked in the form.
 */

export interface AggMethodMeta {
  description: string;
  /** Human-friendly label for the dropdown (defaults to the key). */
  label?: string;
}

interface ColumnTypeMeta {
  title: string;
  cardMethods: Record<string, AggMethodMeta>;
  inputMethods: Record<string, AggMethodMeta>;
}

const NUMERIC_CARD: Record<string, AggMethodMeta> = {
  count: { description: 'Counts the number of non-NA cells', label: 'Count' },
  unique: { description: 'Number of distinct elements', label: 'Distinct count' },
  sum: { description: 'Sum of non-NA values', label: 'Sum' },
  average: { description: 'Mean of non-NA values', label: 'Average' },
  median: { description: 'Arithmetic median of non-NA values', label: 'Median' },
  min: { description: 'Minimum of non-NA values', label: 'Min' },
  max: { description: 'Maximum of non-NA values', label: 'Max' },
  range: { description: 'Range of non-NA values', label: 'Range' },
  variance: { description: 'Variance of non-NA values', label: 'Variance' },
  std_dev: { description: 'Standard deviation of non-NA values', label: 'Std deviation' },
  percentile: { description: 'Percentiles of non-NA values', label: 'Percentile' },
  skewness: { description: 'Skewness of non-NA values', label: 'Skewness' },
  kurtosis: { description: 'Kurtosis of non-NA values', label: 'Kurtosis' },
};

const NUMERIC_INPUT: Record<string, AggMethodMeta> = {
  Slider: { description: 'Single value slider', label: 'Slider' },
  RangeSlider: { description: 'Two values slider', label: 'Range slider' },
};

const TEXT_INPUT: Record<string, AggMethodMeta> = {
  Select: { description: 'Single-value dropdown', label: 'Select' },
  MultiSelect: { description: 'Multi-value dropdown', label: 'Multi-select' },
  SegmentedControl: {
    description: 'Button bar (best for ≤5 options)',
    label: 'Segmented control',
  },
};

const AGG_BY_TYPE: Record<string, ColumnTypeMeta> = {
  int64: {
    title: 'Integer',
    cardMethods: NUMERIC_CARD,
    inputMethods: NUMERIC_INPUT,
  },
  float64: {
    title: 'Floating Point',
    cardMethods: NUMERIC_CARD,
    inputMethods: NUMERIC_INPUT,
  },
  bool: {
    title: 'Boolean',
    cardMethods: {
      count: { description: 'Counts the number of non-NA cells', label: 'Count' },
      sum: { description: 'Sum of non-NA values (true=1)', label: 'Sum' },
      min: { description: 'Minimum of non-NA values', label: 'Min' },
      max: { description: 'Maximum of non-NA values', label: 'Max' },
    },
    inputMethods: {
      Checkbox: { description: 'Checkbox: True or False', label: 'Checkbox' },
      Switch: { description: 'Switch toggle', label: 'Switch' },
    },
  },
  datetime: {
    title: 'Datetime',
    cardMethods: {
      count: { description: 'Counts the number of non-NA cells', label: 'Count' },
      min: { description: 'Minimum of non-NA values', label: 'Min' },
      max: { description: 'Maximum of non-NA values', label: 'Max' },
    },
    inputMethods: {
      DateRangePicker: {
        description: 'Date range picker',
        label: 'Date range picker',
      },
    },
  },
  timedelta: {
    title: 'Timedelta',
    cardMethods: {
      count: { description: 'Counts the number of non-NA cells', label: 'Count' },
      sum: { description: 'Sum of non-NA values', label: 'Sum' },
      min: { description: 'Minimum of non-NA values', label: 'Min' },
      max: { description: 'Maximum of non-NA values', label: 'Max' },
    },
    inputMethods: {},
  },
  category: {
    title: 'Category',
    cardMethods: {
      count: { description: 'Counts the number of non-NA cells', label: 'Count' },
      mode: { description: 'Most common value', label: 'Mode' },
    },
    inputMethods: TEXT_INPUT,
  },
  object: {
    title: 'Object',
    cardMethods: {
      count: { description: 'Counts the number of non-NA cells', label: 'Count' },
      mode: { description: 'Most common value', label: 'Mode' },
      nunique: { description: 'Number of distinct elements', label: 'Distinct count' },
    },
    inputMethods: TEXT_INPUT,
  },
  utf8: {
    title: 'Object',
    cardMethods: {
      count: { description: 'Counts the number of non-NA cells', label: 'Count' },
      mode: { description: 'Most common value', label: 'Mode' },
      nunique: { description: 'Number of distinct elements', label: 'Distinct count' },
    },
    inputMethods: TEXT_INPUT,
  },
};

/** Normalize raw column-type strings (polars/pandas/precompute outputs) to
 *  the canonical keys used by AGG_BY_TYPE. The precompute step in
 *  depictio/api/v1/endpoints/deltatables_endpoints/utils.py already coerces
 *  most of these, but the API may surface raw polars types in some edge
 *  cases — keep the mapping defensive. */
function normalizeType(raw: string): string {
  if (!raw) return '';
  const t = raw.toLowerCase();
  if (t.startsWith('datetime')) return 'datetime';
  if (t.startsWith('timedelta') || t === 'time' || t === 'duration') return 'timedelta';
  if (['int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64'].includes(t)) {
    return 'int64';
  }
  if (['float16', 'float32', 'float64'].includes(t)) return 'float64';
  if (t === 'boolean') return 'bool';
  if (t === 'string') return 'utf8';
  return t;
}

/** Aggregations available on a column of the given type, ordered by the
 *  Dash dict order (preserved by JS object iteration since ES2020). */
export function cardMethodsForType(
  rawType: string | undefined | null,
): Array<{ value: string; label: string; description: string }> {
  if (!rawType) return [];
  const meta = AGG_BY_TYPE[normalizeType(rawType)];
  if (!meta) return [];
  return Object.entries(meta.cardMethods).map(([key, m]) => ({
    value: key,
    label: m.label || key,
    description: m.description,
  }));
}

/** Interactive variants available on a column of the given type, ordered as
 *  in the Dash dict. Pass `nunique` to drop SegmentedControl on
 *  high-cardinality columns (mirrors the >5 filter in design.py:476). */
export function inputMethodsForType(
  rawType: string | undefined | null,
  nunique?: number,
): Array<{ value: string; label: string; description: string }> {
  if (!rawType) return [];
  const meta = AGG_BY_TYPE[normalizeType(rawType)];
  if (!meta) return [];
  let entries = Object.entries(meta.inputMethods);
  if (typeof nunique === 'number' && nunique > 5) {
    entries = entries.filter(([k]) => k !== 'SegmentedControl');
  }
  return entries.map(([key, m]) => ({
    value: key,
    label: m.label || key,
    description: m.description,
  }));
}

/** Whether a column type is supported by the interactive component at all. */
export function hasInputMethods(rawType: string | undefined | null): boolean {
  if (!rawType) return false;
  const meta = AGG_BY_TYPE[normalizeType(rawType)];
  return !!meta && Object.keys(meta.inputMethods).length > 0;
}

/** Whether a column type is supported by the card component at all. */
export function hasCardMethods(rawType: string | undefined | null): boolean {
  if (!rawType) return false;
  const meta = AGG_BY_TYPE[normalizeType(rawType)];
  return !!meta && Object.keys(meta.cardMethods).length > 0;
}
