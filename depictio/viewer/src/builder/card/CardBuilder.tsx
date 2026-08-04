/**
 * Card builder form. Mirrors design_card() in
 * depictio/dash/modules/card_component/design_ui.py — title, column,
 * aggregation, colors, icon, font size, with a live preview on the right.
 */
import React, { useEffect, useMemo } from 'react';
import {
  ColorInput,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { isBreakdownLayout } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import DesignShell from '../shared/DesignShell';
import CardPreview from './CardPreview';
import { cardMethodsForType } from '../aggFunctions';
import { autoCardTitle } from './cardTitle';

const FONT_SIZES = [
  { value: 'xs', label: 'XS' },
  { value: 'sm', label: 'S' },
  { value: 'md', label: 'M' },
  { value: 'lg', label: 'L' },
  { value: 'xl', label: 'XL' },
];

const BACKGROUND_SWATCHES = [
  '#2e2e2e',
  '#868e96',
  '#fa5252',
  '#e64980',
  '#be4bdb',
  '#7950f2',
  '#4c6ef5',
  '#228be6',
  '#15aabf',
  '#12b886',
  '#40c057',
  '#82c91e',
  '#fab005',
  '#fd7e14',
  '',
];

const TITLE_COLOR_SWATCHES = [
  '#000000',
  '#fa5252',
  '#e64980',
  '#be4bdb',
  '#7950f2',
  '#4c6ef5',
  '#228be6',
  '#15aabf',
  '#12b886',
  '#40c057',
  '#fab005',
];

const ICON_OPTIONS: { value: string; label: string }[] = [
  { value: 'mdi:chart-line', label: 'Chart line' },
  { value: 'mdi:chart-bar', label: 'Chart bar' },
  { value: 'mdi:chart-pie', label: 'Chart pie' },
  { value: 'mdi:counter', label: 'Counter' },
  { value: 'mdi:sigma', label: 'Sigma (sum)' },
  { value: 'mdi:calculator', label: 'Calculator' },
  { value: 'mdi:database', label: 'Database' },
  { value: 'mdi:table', label: 'Table' },
  { value: 'mdi:account-multiple', label: 'People' },
  { value: 'mdi:dna', label: 'DNA' },
  { value: 'mdi:flask', label: 'Flask' },
  { value: 'mdi:microscope', label: 'Microscope' },
  { value: 'mdi:test-tube', label: 'Test tube' },
  { value: 'mdi:percent', label: 'Percent' },
  { value: 'mdi:check-circle', label: 'Check circle' },
];

/** Multi-metric style options. The Select carries a single token that maps
 *  to a ``(aggregations, secondary_layout, …)`` config bundle on save.
 *
 *  Distribution-style layouts (vertical / compact / box_plot) target numeric
 *  columns and surface scalar aggregations. The cardinality-style layouts
 *  (top_n / composition / donut / coverage / concentration) target ``count`` /
 *  ``nunique`` aggregations and need an extra config field — the builder
 *  exposes those fields conditionally below the Select, and pre-fills them
 *  with a sensible guess so switching layout shows a strip immediately. */
type MultiMetricStyle =
  | 'single'
  | 'vertical'
  | 'compact'
  | 'box_plot'
  | 'top_n'
  | 'coverage'
  | 'concentration'
  | 'composition'
  | 'donut'
  | 'histogram'
  | 'threshold'
  | 'completeness'
  | 'attrition';
// Mantine 7 ``Select`` expects nested groups in the shape
// ``{ group, items: [...] }`` — the flat ``{value, label, group}`` format we
// inherited from Mantine 6 crashes the option normalizer with
// ``Cannot read properties of undefined (reading 'map')`` (it sees ``group``
// and tries to ``.map`` the missing ``items`` array). See:
// https://mantine.dev/core/select/#grouping-options
const MULTI_METRIC_OPTIONS: Array<
  | { value: MultiMetricStyle; label: string }
  | { group: string; items: Array<{ value: MultiMetricStyle; label: string }> }
> = [
  { value: 'single', label: 'Single metric (no extras)' },
  {
    group: 'Distribution',
    items: [
      { value: 'vertical', label: 'Vertical list (median / min / max)' },
      { value: 'compact', label: 'Compact strip (median / min / max)' },
      { value: 'box_plot', label: 'Box-plot (Tukey: IQR + whiskers + outliers)' },
      { value: 'histogram', label: 'Histogram sparkline (shows shape / modality)' },
    ],
  },
  {
    group: 'Quality control',
    items: [
      { value: 'threshold', label: 'Threshold (pass / warn / fail against a cut-off)' },
      { value: 'completeness', label: 'Completeness (filled vs missing values)' },
      { value: 'attrition', label: 'Attrition funnel (retention across stages)' },
    ],
  },
  {
    group: 'Cardinality',
    items: [
      { value: 'top_n', label: 'Top-N bars (most frequent values of a column)' },
      { value: 'composition', label: 'Composition bar (shares + "Other", with evenness)' },
      { value: 'donut', label: 'Donut (ring of shares, hero value in the middle)' },
      { value: 'coverage', label: 'Coverage gauge (current / theoretical max)' },
      { value: 'concentration', label: 'Concentration (top-N share + names)' },
    ],
  },
];

/** Convert (aggregations, secondary_layout) saved on the metadata back into
 *  the Select token. Used on edit re-open. */
function inferMultiMetricStyle(
  aggs: string[] | null | undefined,
  layout: string | null | undefined,
): MultiMetricStyle {
  // Every layout that owns its own config bundle round-trips by name; only the
  // three ``aggregations``-driven ones need the fallbacks below.
  const selfDescribing: MultiMetricStyle[] = [
    'top_n',
    'coverage',
    'concentration',
    'composition',
    'donut',
    'histogram',
    'threshold',
    'completeness',
    'attrition',
  ];
  if (layout && selfDescribing.includes(layout as MultiMetricStyle)) {
    return layout as MultiMetricStyle;
  }
  if (!aggs || aggs.length === 0) return 'single';
  if (layout === 'box_plot' || (aggs.length === 1 && aggs[0] === 'box_plot_stats')) {
    return 'box_plot';
  }
  if (layout === 'compact') return 'compact';
  return 'vertical';
}

/** Apply a Select token onto config: writes back the whole layout-config bundle
 *  the dashboard renderer + server read.
 *
 *  Every layout-specific field is reset on every switch, so a stale threshold
 *  from a previous choice can never end up on a saved composition card. Only
 *  the distribution layouts populate ``aggregations``; the categorical and QC
 *  ones are computed server-side from their own config instead. */
function multiMetricStyleToConfig(style: MultiMetricStyle): Record<string, unknown> {
  const base = {
    aggregations: null as string[] | null,
    breakdown_col: null,
    coverage_max: null,
    top_n_count: 3,
    threshold_value: null,
    threshold_direction: 'min',
    threshold_warn: null,
    attrition_cols: [] as string[],
  };
  const SCALAR_AGGS = ['median', 'min', 'max'];
  switch (style) {
    case 'box_plot':
      return { ...base, aggregations: ['box_plot_stats'], secondary_layout: 'box_plot' };
    case 'compact':
      return { ...base, aggregations: SCALAR_AGGS, secondary_layout: 'compact' };
    case 'vertical':
      return { ...base, aggregations: SCALAR_AGGS, secondary_layout: 'vertical' };
    case 'single':
      return { ...base, secondary_layout: 'vertical' };
    default:
      // top_n / coverage / concentration / composition / donut / histogram /
      // threshold / completeness / attrition all round-trip by name.
      return { ...base, secondary_layout: style };
  }
}

const CardBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    column_name?: string;
    column_type?: string;
    aggregation?: string;
    aggregations?: string[] | null;
    secondary_layout?:
      | 'vertical'
      | 'compact'
      | 'box_plot'
      | 'top_n'
      | 'coverage'
      | 'concentration'
      | 'composition'
      | 'donut'
      | 'histogram'
      | 'threshold'
      | 'completeness'
      | 'attrition';
    breakdown_col?: string | null;
    coverage_max?: number | null;
    top_n_count?: number;
    threshold_value?: number | null;
    threshold_direction?: string;
    threshold_warn?: number | null;
    attrition_cols?: string[] | null;
    background_color?: string;
    title_color?: string;
    icon_name?: string;
    title_font_size?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const cols = useBuilderStore((s) => s.cols);

  // Apply sane defaults once after mount when creating fresh.
  useEffect(() => {
    patchConfig({
      title: config.title ?? '',
      aggregation: config.aggregation ?? 'count',
      icon_name: config.icon_name ?? 'mdi:chart-line',
      title_font_size: config.title_font_size ?? 'md',
      background_color: config.background_color ?? '',
      title_color: config.title_color ?? '',
      // Multi-metric defaults — preserve whatever was saved, otherwise
      // single-metric mode. Null `aggregations` is the "no extras" signal
      // the dashboard renderer checks before drawing SecondaryMetrics.
      aggregations: config.aggregations ?? null,
      secondary_layout: config.secondary_layout ?? 'vertical',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const multiMetricStyle: MultiMetricStyle = useMemo(
    () => inferMultiMetricStyle(config.aggregations, config.secondary_layout),
    [config.aggregations, config.secondary_layout],
  );

  /** Best guess at the column a breakdown should group by.
   *
   *  Preference order, and why: the card's own column when it is categorical
   *  (a "count of variety" card broken down by variety is the reading the user
   *  almost always means); otherwise the categorical column with the *fewest*
   *  distinct values, because a strip of 3 species is legible where a strip of
   *  10 000 sample IDs is noise. ``nunique`` comes from the precomputed specs,
   *  so this costs nothing. */
  const defaultBreakdownCol = useMemo(() => {
    const categorical = cols.filter((c) =>
      ['object', 'string', 'category', 'bool'].includes(c.type),
    );
    if (!categorical.length) return null;
    if (categorical.some((c) => c.name === config.column_name)) {
      return config.column_name ?? null;
    }
    const ranked = [...categorical].sort((a, b) => {
      const an = typeof a.specs?.nunique === 'number' ? (a.specs.nunique as number) : Infinity;
      const bn = typeof b.specs?.nunique === 'number' ? (b.specs.nunique as number) : Infinity;
      // Single-valued columns carry no information; push them behind the rest
      // rather than letting them win for having the lowest cardinality.
      const aScore = an <= 1 ? Infinity : an;
      const bScore = bn <= 1 ? Infinity : bn;
      return aScore - bScore;
    });
    return ranked[0]?.name ?? null;
  }, [cols, config.column_name]);

  /** Default denominator for the coverage gauge: the card's own unfiltered
   *  value. The gauge then reads "how much of the data survives the current
   *  filters", which is both the common intent and immediately meaningful —
   *  where a null max renders nothing at all and looks like a broken card. */
  const defaultCoverageMax = useMemo(() => {
    const raw = cols.find((c) => c.name === config.column_name)?.specs?.[
      config.aggregation as string
    ];
    return typeof raw === 'number' && Number.isFinite(raw) && raw > 0
      ? Math.ceil(raw)
      : null;
  }, [cols, config.column_name, config.aggregation]);

  /** Default QC cut-off: the column's median, from the precomputed specs.
   *
   *  Not a guess at the user's real threshold — that is lab policy this layer
   *  cannot know — but a value guaranteed to be inside the data's range, so the
   *  strip renders a meaningful split immediately and the user adjusts from
   *  something rather than from a blank field. */
  const defaultThreshold = useMemo(() => {
    const specs = cols.find((c) => c.name === config.column_name)?.specs;
    const median = specs?.median ?? specs?.average ?? specs?.mean;
    return typeof median === 'number' && Number.isFinite(median) ? median : null;
  }, [cols, config.column_name]);

  /** Numeric columns available as later attrition stages. The card's own column
   *  is the first stage and is excluded, so it cannot be listed twice. */
  const numericColumnNames = useMemo(
    () =>
      cols
        .filter(
          (c) =>
            ['int64', 'int32', 'float64', 'float32'].includes(c.type) &&
            c.name !== config.column_name,
        )
        .map((c) => c.name),
    [cols, config.column_name],
  );

  // Pre-fill the field the chosen layout requires. Without this, picking a
  // cardinality layout showed an empty form and no preview strip, so the
  // feature looked broken until the user guessed which field to fill. Only
  // ever fills a *blank* field, so an explicit choice is never overwritten.
  useEffect(() => {
    if (isBreakdownLayout(config.secondary_layout)) {
      if (!config.breakdown_col && defaultBreakdownCol) {
        patchConfig({ breakdown_col: defaultBreakdownCol });
      }
    } else if (config.secondary_layout === 'coverage') {
      if (config.coverage_max == null && defaultCoverageMax != null) {
        patchConfig({ coverage_max: defaultCoverageMax });
      }
    } else if (config.secondary_layout === 'threshold') {
      if (config.threshold_value == null && defaultThreshold != null) {
        patchConfig({ threshold_value: defaultThreshold });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    config.secondary_layout,
    config.breakdown_col,
    config.coverage_max,
    config.threshold_value,
    defaultBreakdownCol,
    defaultThreshold,
    defaultCoverageMax,
  ]);

  // Aggregation options follow the column's type, mirroring
  // depictio/api/v1/utils.py:agg_functions[type]['card_methods'].
  const aggOptions = useMemo(
    () => cardMethodsForType(config.column_type),
    [config.column_type],
  );

  // If the current aggregation isn't valid for the new column type, reset to
  // the first allowed one (or null if the type has no card methods).
  useEffect(() => {
    if (!config.column_type) return;
    if (!config.aggregation) return;
    if (!aggOptions.some((o) => o.value === config.aggregation)) {
      patchConfig({ aggregation: aggOptions[0]?.value ?? null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.column_type, aggOptions]);

  const form = (
    <Stack gap="md">
      <TextInput
        label="Card title"
        placeholder={
          autoCardTitle(
            config.aggregation,
            config.column_name,
            config.column_type,
          ) || 'Total samples'
        }
        description="Leave empty to auto-fill with “<Aggregation> on <column>”."
        value={config.title ?? ''}
        onChange={(e) => patchConfig({ title: e.currentTarget.value })}
        leftSection={<Icon icon="mdi:format-title" width={14} />}
      />

      <ColumnSelect
        label="Select your column"
        value={config.column_name}
        onChange={(name, type) =>
          patchConfig({ column_name: name, column_type: type })
        }
        required
      />

      <Select
        label="Select your aggregation method"
        placeholder={
          !config.column_type
            ? 'Pick a column first'
            : aggOptions.length === 0
              ? 'No aggregations for this column type'
              : 'Pick aggregation'
        }
        data={aggOptions}
        value={config.aggregation ?? null}
        onChange={(val) => patchConfig({ aggregation: val })}
        disabled={!config.column_type || aggOptions.length === 0}
        required
      />

      <Select
        label="Multi-metric style"
        description="Pick a secondary strip layout. Distribution targets numeric columns, cardinality targets count / distinct-count cards, quality control answers “how many rows pass”. The field each layout needs is pre-filled from your data."
        data={MULTI_METRIC_OPTIONS}
        value={multiMetricStyle}
        onChange={(val) => {
          if (!val) return;
          patchConfig(multiMetricStyleToConfig(val as MultiMetricStyle));
        }}
        allowDeselect={false}
        leftSection={<Icon icon="mdi:chart-box-outline" width={14} />}
      />

      {/* Conditional fields for the cardinality-style layouts. The breakdown
          layouts need a categorical column + a row count; ``coverage`` needs
          the theoretical max (denominator). Both are pre-filled above, so this
          block shows a working configuration rather than empty required
          fields. Hidden for the distribution-style layouts. */}
      {isBreakdownLayout(config.secondary_layout) && (
        <>
          <ColumnSelect
            label="Breakdown column"
            description="Categorical column to group by. The strip shows the top-N most-frequent values."
            value={config.breakdown_col ?? null}
            onChange={(name) => patchConfig({ breakdown_col: name })}
            categoricalOnly
            required
            clearable={false}
          />
          <NumberInput
            label="Top N"
            description="How many values to surface (1–5; past 5 the strip becomes illegibly cramped at typical card widths)."
            value={config.top_n_count ?? 3}
            onChange={(val) =>
              patchConfig({ top_n_count: Math.max(1, Math.min(5, Number(val) || 3)) })
            }
            min={1}
            max={5}
            step={1}
            leftSection={<Icon icon="mdi:format-list-numbered" width={14} />}
          />
        </>
      )}
      {multiMetricStyle === 'coverage' && (
        <NumberInput
          label="Coverage max"
          description="Theoretical maximum the hero value can reach (e.g. 44 samples / 11 ORFs / 99 amplicons). The strip renders ``value / max`` as a fill bar."
          value={config.coverage_max ?? undefined}
          onChange={(val) =>
            patchConfig({
              coverage_max: val === '' || val === undefined ? null : Number(val),
            })
          }
          min={1}
          step={1}
          leftSection={<Icon icon="mdi:gauge" width={14} />}
          required
        />
      )}

      {/* Quality-control layouts. ``threshold`` needs the cut-off (pre-filled
          with the column's median so the strip renders something meaningful
          immediately) and which side passes; ``attrition`` needs the ordered
          stage columns. ``completeness`` needs no config at all. */}
      {multiMetricStyle === 'threshold' && (
        <>
          <NumberInput
            label="Threshold value"
            description="QC cut-off the column is judged against. Pre-filled with the column's median — replace it with your actual criterion (e.g. 30 for ≥30× coverage, 80 for %Q30)."
            value={config.threshold_value ?? undefined}
            onChange={(val) =>
              patchConfig({
                threshold_value: val === '' || val === undefined ? null : Number(val),
              })
            }
            step={1}
            leftSection={<Icon icon="mdi:ruler" width={14} />}
            required
          />
          <Select
            label="Passing side"
            description="Which side of the cut-off counts as a pass. Getting this backwards inverts the QC verdict, so it is explicit rather than guessed."
            data={[
              { value: 'min', label: 'At least (≥) — higher is better, e.g. coverage, %Q30' },
              { value: 'max', label: 'At most (≤) — lower is better, e.g. duplication, error rate' },
            ]}
            value={config.threshold_direction ?? 'min'}
            onChange={(val) => patchConfig({ threshold_direction: val || 'min' })}
            allowDeselect={false}
            leftSection={<Icon icon="mdi:compare-horizontal" width={14} />}
          />
          <NumberInput
            label="Warning threshold (optional)"
            description="Softer cut-off between pass and fail. Must sit on the failing side of the main threshold, otherwise it is ignored."
            value={config.threshold_warn ?? undefined}
            onChange={(val) =>
              patchConfig({
                threshold_warn: val === '' || val === undefined ? null : Number(val),
              })
            }
            step={1}
            leftSection={<Icon icon="mdi:alert-outline" width={14} />}
          />
        </>
      )}
      {multiMetricStyle === 'attrition' && (
        <MultiSelect
          label="Later stage columns"
          description="Numeric columns for the stages after this card's own, in pipeline order (e.g. trimmed → mapped → deduplicated). Bars show each stage's share of the first."
          data={numericColumnNames}
          value={config.attrition_cols ?? []}
          onChange={(vals) => patchConfig({ attrition_cols: vals })}
          searchable
          clearable
          leftSection={<Icon icon="mdi:filter-variant" width={14} />}
        />
      )}

      <Title order={6} fw={700} mt="sm">
        Card Styling
      </Title>

      <ColorInput
        label="Background Color"
        value={config.background_color ?? ''}
        onChange={(val) => patchConfig({ background_color: val })}
        format="hex"
        swatchesPerRow={7}
        swatches={BACKGROUND_SWATCHES}
        placeholder="(default)"
      />

      <ColorInput
        label="Title Color"
        value={config.title_color ?? ''}
        onChange={(val) => patchConfig({ title_color: val })}
        format="hex"
        swatchesPerRow={7}
        swatches={TITLE_COLOR_SWATCHES}
        placeholder="(default)"
      />

      <Select
        label="Icon"
        placeholder="Pick an icon"
        data={ICON_OPTIONS}
        value={config.icon_name ?? null}
        onChange={(val) => patchConfig({ icon_name: val })}
        searchable
        leftSection={
          <Icon icon={config.icon_name || 'mdi:help-circle'} width={14} />
        }
      />

      <Select
        label="Title Font Size"
        data={FONT_SIZES}
        value={config.title_font_size ?? 'md'}
        onChange={(val) => patchConfig({ title_font_size: val })}
      />
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<CardPreview />} />;
};

export default CardBuilder;
