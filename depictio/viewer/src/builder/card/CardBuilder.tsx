/**
 * Card builder form. Mirrors design_card() in
 * depictio/dash/modules/card_component/design_ui.py — title, column,
 * aggregation, colors, icon, font size, with a live preview on the right.
 */
import React, { useEffect, useMemo } from 'react';
import {
  ColorInput,
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
  | 'donut';
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
  if (layout === 'top_n') return 'top_n';
  if (layout === 'coverage') return 'coverage';
  if (layout === 'concentration') return 'concentration';
  if (layout === 'composition') return 'composition';
  if (layout === 'donut') return 'donut';
  if (!aggs || aggs.length === 0) return 'single';
  if (layout === 'box_plot' || (aggs.length === 1 && aggs[0] === 'box_plot_stats')) {
    return 'box_plot';
  }
  if (layout === 'compact') return 'compact';
  return 'vertical';
}

/** Apply a Select token onto config: writes back the (aggregations,
 *  secondary_layout, breakdown_col, coverage_max, top_n_count) bundle the
 *  dashboard renderer + server reads. Switching between styles clears the
 *  irrelevant fields so stale values don't pollute the saved metadata. */
function multiMetricStyleToConfig(style: MultiMetricStyle): {
  aggregations: string[] | null;
  secondary_layout:
    | 'vertical'
    | 'compact'
    | 'box_plot'
    | 'top_n'
    | 'coverage'
    | 'concentration'
    | 'composition'
    | 'donut';
  breakdown_col: string | null;
  coverage_max: number | null;
  top_n_count: number;
} {
  const base = { breakdown_col: null, coverage_max: null, top_n_count: 3 } as const;
  switch (style) {
    case 'box_plot':
      return { ...base, aggregations: ['box_plot_stats'], secondary_layout: 'box_plot' };
    case 'compact':
      return { ...base, aggregations: ['median', 'min', 'max'], secondary_layout: 'compact' };
    case 'vertical':
      return { ...base, aggregations: ['median', 'min', 'max'], secondary_layout: 'vertical' };
    case 'top_n':
      // Cardinality strips don't use the ``aggregations`` array — the
      // breakdown is computed server-side via ``breakdown_col`` instead.
      return { ...base, aggregations: null, secondary_layout: 'top_n' };
    case 'coverage':
      return { ...base, aggregations: null, secondary_layout: 'coverage' };
    case 'concentration':
      return { ...base, aggregations: null, secondary_layout: 'concentration' };
    case 'composition':
      return { ...base, aggregations: null, secondary_layout: 'composition' };
    case 'donut':
      return { ...base, aggregations: null, secondary_layout: 'donut' };
    case 'single':
    default:
      return { ...base, aggregations: null, secondary_layout: 'vertical' };
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
      | 'donut';
    breakdown_col?: string | null;
    coverage_max?: number | null;
    top_n_count?: number;
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
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    config.secondary_layout,
    config.breakdown_col,
    config.coverage_max,
    defaultBreakdownCol,
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
        description="Pick a secondary strip layout. Distribution group (vertical / compact / box-plot) targets numeric columns; cardinality group (top-N / composition / donut / coverage / concentration) targets count / distinct-count cards. The field each layout needs is pre-filled from your data."
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
