/**
 * A committed catalog render (raw dict out of `public/catalog.json`) → the
 * Studio's own `RenderSpec`, so an output's existing renders can be previewed
 * with the same component the Studio uses for the ones you are authoring.
 *
 * The manifest is untyped on purpose — it is whatever the catalog YAML said —
 * so every field is narrowed here rather than trusted. An entry this cannot
 * narrow returns null and is listed without a preview, which is the honest
 * outcome for a render written against a model this build does not know.
 */
import type { ManifestRender } from './catalog';
import type {
  Aggregation,
  FigureVisuType,
  InteractiveVariant,
  RenderSpec,
  SecondaryLayout,
  ThresholdDirection,
} from '../types';
import { AGGREGATIONS, SECONDARY_LAYOUTS, THRESHOLD_DIRECTIONS } from './generated/cardSpec';

const str = (v: unknown): string | undefined =>
  typeof v === 'string' && v ? v : undefined;
const num = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? v : undefined;
const strList = (v: unknown): string[] | undefined =>
  Array.isArray(v) && v.every((x) => typeof x === 'string') && v.length
    ? (v as string[])
    : undefined;
const oneOf = <T extends string>(v: unknown, allowed: readonly string[]): T | undefined =>
  typeof v === 'string' && allowed.includes(v) ? (v as T) : undefined;

const INTERACTIVE_VARIANTS = [
  'Select',
  'MultiSelect',
  'SegmentedControl',
  'Slider',
  'RangeSlider',
  'DateRangePicker',
  'Timeline',
  'Switch',
] as const;

const VISU_TYPES = ['scatter', 'line', 'bar', 'box', 'histogram', 'heatmap'] as const;

export function renderSpecFromManifest(
  raw: ManifestRender,
  uid: string,
): RenderSpec | null {
  const id = str(raw.id);
  const base = { uid, ...(id ? { id } : {}) };

  switch (raw.component) {
    case 'figure': {
      const code = str(raw.code);
      if (code) return { ...base, component: 'figure', code };
      const visu_type = oneOf<FigureVisuType>(raw.visu_type, VISU_TYPES);
      if (!visu_type) return null;
      const kwargs = raw.dict_kwargs;
      return {
        ...base,
        component: 'figure',
        visu_type,
        dict_kwargs:
          kwargs && typeof kwargs === 'object'
            ? Object.fromEntries(
                Object.entries(kwargs as Record<string, unknown>).map(([k, v]) => [
                  k,
                  String(v),
                ]),
              )
            : {},
      };
    }
    case 'card': {
      const column = str(raw.column);
      const aggregation = oneOf<Aggregation>(raw.aggregation, AGGREGATIONS);
      if (!column || !aggregation) return null;
      const aggregations = strList(raw.aggregations)?.filter((a) =>
        (AGGREGATIONS as readonly string[]).includes(a),
      ) as Aggregation[] | undefined;
      return {
        ...base,
        component: 'card',
        column,
        aggregation,
        ...(aggregations?.length ? { aggregations } : {}),
        ...(oneOf<SecondaryLayout>(raw.secondary_layout, SECONDARY_LAYOUTS)
          ? { secondary_layout: raw.secondary_layout as SecondaryLayout }
          : {}),
        ...(str(raw.breakdown_col) ? { breakdown_col: str(raw.breakdown_col) } : {}),
        ...(num(raw.top_n_count) != null ? { top_n_count: num(raw.top_n_count) } : {}),
        ...(num(raw.coverage_max) != null ? { coverage_max: num(raw.coverage_max) } : {}),
        ...(num(raw.threshold_value) != null
          ? { threshold_value: num(raw.threshold_value) }
          : {}),
        ...(oneOf<ThresholdDirection>(raw.threshold_direction, THRESHOLD_DIRECTIONS)
          ? { threshold_direction: raw.threshold_direction as ThresholdDirection }
          : {}),
        ...(num(raw.threshold_warn) != null ? { threshold_warn: num(raw.threshold_warn) } : {}),
        ...(strList(raw.attrition_cols) ? { attrition_cols: strList(raw.attrition_cols) } : {}),
        ...(str(raw.trend_col) ? { trend_col: str(raw.trend_col) } : {}),
        ...(str(raw.filter_expr) ? { filter_expr: str(raw.filter_expr) } : {}),
      };
    }
    case 'table':
      return {
        ...base,
        component: 'table',
        ...(strList(raw.columns) ? { columns: strList(raw.columns) } : {}),
        ...(num(raw.page_size) != null ? { page_size: num(raw.page_size) } : {}),
        ...(typeof raw.row_selection_enabled === 'boolean'
          ? { row_selection_enabled: raw.row_selection_enabled }
          : {}),
        ...(str(raw.row_selection_column)
          ? { row_selection_column: str(raw.row_selection_column) }
          : {}),
      };
    case 'interactive': {
      const interactive_type = oneOf<InteractiveVariant>(
        raw.interactive_type,
        INTERACTIVE_VARIANTS,
      );
      const column_name = str(raw.column_name);
      if (!interactive_type || !column_name) return null;
      return { ...base, component: 'interactive', interactive_type, column_name };
    }
    case 'advanced_viz': {
      const kind = str(raw.kind);
      if (!kind) return null;
      const roles = raw.roles;
      return {
        ...base,
        component: 'advanced_viz',
        kind,
        roles:
          roles && typeof roles === 'object'
            ? Object.fromEntries(
                Object.entries(roles as Record<string, unknown>)
                  .filter(
                    ([, v]) =>
                      typeof v === 'string' ||
                      (Array.isArray(v) && v.every((c) => typeof c === 'string')),
                  )
                  .map(([k, v]) => [k, v as string | string[]]),
              )
            : {},
      };
    }
    default:
      // multiqc / image / text / map: no Studio authoring path, no preview.
      return null;
  }
}
