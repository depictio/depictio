/**
 * Interactive filter builder. Replicates depictio's real `InteractiveBuilder`
 * FORM (title, ColumnSelect, variant, color, icon, title-size) — the form is
 * pure Mantine with no backend calls, so it's copied faithfully — but swaps
 * depictio's backend-fetching `InteractivePreview` for a client-side control
 * fed from the fixture's precomputed specs.
 *
 * IMPORTANT: the catalog `Render` model carries NOTHING for interactive beyond
 * `component` (it rejects even `column`), so everything here is authoring
 * preview only — `fromBuilderStore` emits a bare `{ component: interactive }`.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Card,
  Checkbox,
  ColorInput,
  MultiSelect,
  RangeSlider,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import ColumnSelect from 'depictio-builder/shared/ColumnSelect';
import DesignShell from 'depictio-builder/shared/DesignShell';
import PreviewPanel from 'depictio-builder/shared/PreviewPanel';
import { inputMethodsForType } from 'depictio-builder/aggFunctions';
import type { ParsedFixture } from '../types';

// Mirrors depictio InteractiveBuilder.tsx (VARIANT_ICONS / ICON_OPTIONS /
// TITLE_SIZES) so the form looks native.
const VARIANT_ICONS: Record<string, string> = {
  Select: 'mdi:menu-down',
  MultiSelect: 'mdi:filter-variant',
  SegmentedControl: 'mdi:button-cursor',
  Slider: 'bx:slider',
  RangeSlider: 'bx:slider-alt',
  DateRangePicker: 'mdi:calendar',
  Switch: 'mdi:toggle-switch',
  Checkbox: 'mdi:checkbox-marked-outline',
};

const ICON_OPTIONS: { value: string; label: string }[] = [
  { value: 'bx:slider-alt', label: 'Slider Alt' },
  { value: 'mdi:chart-line', label: 'Chart Line' },
  { value: 'mdi:counter', label: 'Counter' },
  { value: 'mdi:thermometer', label: 'Thermometer' },
  { value: 'mdi:water', label: 'Water' },
  { value: 'mdi:flask', label: 'Flask' },
  { value: 'mdi:gauge', label: 'Gauge' },
  { value: 'mdi:ruler', label: 'Ruler' },
  { value: 'mdi:leaf', label: 'Leaf' },
  { value: 'mdi:check-circle', label: 'Check Circle' },
  { value: 'mdi:target', label: 'Target' },
  { value: 'mdi:dna', label: 'DNA' },
  { value: 'mdi:form-select', label: 'Select' },
  { value: 'mdi:radiobox-marked', label: 'Radio' },
  { value: 'mdi:checkbox-marked', label: 'Checkbox' },
  { value: 'mdi:toggle-switch', label: 'Switch' },
  { value: 'mdi:calendar-range', label: 'Calendar' },
];

const TITLE_SIZES: { value: string; label: string }[] = [
  { value: 'xs', label: 'Extra Small' },
  { value: 'sm', label: 'Small' },
  { value: 'md', label: 'Medium' },
  { value: 'lg', label: 'Large' },
  { value: 'xl', label: 'Extra Large' },
];

const COLOR_SWATCHES = ['#9966cc', '#228be6', '#15aabf', '#40c057', '#fab005', '#fd7e14', '#e6779f', '#fa5252', '#7950f2', '#000000'];

interface InteractiveConfig {
  interactive_component_type?: string;
  column_name?: string;
  column_type?: string;
  title?: string;
  title_size?: string;
  color?: string;
  icon_name?: string;
}

function pickNum(specs: Record<string, unknown> | undefined, key: string): number | undefined {
  const v = specs?.[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

// ── client-side control preview, fed from the fixture's precomputed specs ────
function ControlPreview() {
  const config = useBuilderStore((s) => s.config) as InteractiveConfig;
  const cols = useBuilderStore((s) => s.cols);
  const [single, setSingle] = useState<string | null>(null);
  const [multi, setMulti] = useState<string[]>([]);
  const [range, setRange] = useState<[number, number] | null>(null);

  const specs = cols.find((c) => c.name === config.column_name)?.specs as Record<string, unknown> | undefined;
  const variant = config.interactive_component_type;
  const { color, icon_name, title, title_size } = config;

  const options = useMemo(() => {
    const raw = specs?.unique_values;
    return Array.isArray(raw) ? raw.map((v) => String(v)) : [];
  }, [specs]);
  const min = pickNum(specs, 'min') ?? 0;
  const max = pickNum(specs, 'max') ?? 100;

  useEffect(() => {
    setSingle(null);
    setMulti([]);
    setRange([min, max]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.column_name, variant]);

  if (!config.column_name || !variant) {
    return <PreviewPanel empty emptyMessage="Pick a column and control to preview…" minHeight={200} />;
  }

  let control: React.ReactNode;
  switch (variant) {
    case 'Slider':
      control = <Slider min={min} max={max} defaultValue={min} color={color || undefined} />;
      break;
    case 'RangeSlider':
      control = <RangeSlider min={min} max={max} value={range ?? [min, max]} onChange={setRange} color={color || undefined} />;
      break;
    case 'Select':
      control = <Select data={options} value={single} onChange={setSingle} placeholder="Select a value…" searchable clearable />;
      break;
    case 'MultiSelect':
      control = <MultiSelect data={options} value={multi} onChange={setMulti} placeholder="Select values…" searchable clearable />;
      break;
    case 'SegmentedControl':
      control =
        options.length > 0 ? (
          <SegmentedControl fullWidth data={options.slice(0, 5)} value={single ?? options[0]} onChange={setSingle} color={color || undefined} />
        ) : (
          <Text size="sm" c="dimmed">No values to show.</Text>
        );
      break;
    case 'Checkbox':
      control = <Checkbox label={config.column_name} defaultChecked color={color || undefined} />;
      break;
    case 'Switch':
      control = <Switch label={config.column_name} defaultChecked color={color || undefined} />;
      break;
    case 'DateRangePicker':
      control = (
        <Alert color="gray" variant="light" icon={<Icon icon="mdi:calendar-range" />}>
          Date-range control — previewed in depictio with the live date bounds.
        </Alert>
      );
      break;
    default:
      control = <Text size="sm" c="dimmed">Unsupported control.</Text>;
  }

  return (
    <PreviewPanel minHeight={200}>
      <Stack gap="xs" p="md" style={{ width: '100%' }}>
        <Text size={(title_size as never) ?? 'sm'} fw={600} c={color || undefined}>
          <Icon icon={icon_name || 'bx:slider-alt'} width={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          {title?.trim() || config.column_name}
        </Text>
        {control}
        {(variant === 'Select' || variant === 'MultiSelect' || variant === 'SegmentedControl') && (
          <Text c="dimmed" style={{ fontSize: 10 }}>
            Showing {options.length} sampled value{options.length === 1 ? '' : 's'} from the fixture; depictio loads the
            full set at render time.
          </Text>
        )}
      </Stack>
    </PreviewPanel>
  );
}

export default function InteractiveDesign({ fixture }: { fixture: ParsedFixture }) {
  const config = useBuilderStore((s) => s.config) as InteractiveConfig;
  const cols = useBuilderStore((s) => s.cols);
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const nunique = pickNum(cols.find((c) => c.name === config.column_name)?.specs as Record<string, unknown> | undefined, 'nunique');
  const variants = useMemo(
    () => inputMethodsForType(config.column_type, nunique),
    [config.column_type, nunique],
  );

  // Apply sane defaults once on mount (mirrors depictio InteractiveBuilder).
  useEffect(() => {
    patchConfig({
      title: config.title ?? '',
      icon_name: config.icon_name ?? 'bx:slider-alt',
      title_size: config.title_size ?? 'md',
      color: config.color ?? '',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Default the control to the first valid one when the column changes.
  useEffect(() => {
    if (!config.column_type) return;
    if (!variants.some((v) => v.value === config.interactive_component_type)) {
      patchConfig({ interactive_component_type: variants[0]?.value });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.column_type, variants]);

  const selected = config.interactive_component_type;

  const form = (
    <Card withBorder shadow="sm" p="md" radius="md">
      <Stack gap="sm">
        <TextInput
          label="Interactive component title"
          value={config.title ?? ''}
          onChange={(e) => patchConfig({ title: e.currentTarget.value })}
          leftSection={<Icon icon="mdi:format-title" width={14} />}
        />

        <ColumnSelect
          label="Select your column"
          value={config.column_name}
          onChange={(name, type) => patchConfig({ column_name: name ?? undefined, column_type: type })}
          required
        />

        <Select
          label="Select your interactive component"
          placeholder={
            !config.column_type
              ? 'Pick a column first'
              : variants.length === 0
                ? 'No interactive controls for this column type'
                : 'Pick a control type'
          }
          data={variants.map((v) => ({ value: v.value, label: v.label }))}
          value={selected ?? null}
          onChange={(val) => patchConfig({ interactive_component_type: val ?? undefined })}
          leftSection={<Icon icon={VARIANT_ICONS[selected ?? ''] || 'bx:slider-alt'} width={14} />}
          disabled={!config.column_type || variants.length === 0}
          allowDeselect={false}
        />

        <ColorInput
          label="Color"
          description="Component color (leave empty for auto theme)"
          value={config.color ?? ''}
          onChange={(val) => patchConfig({ color: val })}
          format="hex"
          placeholder="Auto (follows theme)"
          swatches={COLOR_SWATCHES}
        />

        <Select
          label="Icon"
          description="Select an icon for your component"
          data={ICON_OPTIONS}
          value={config.icon_name ?? 'bx:slider-alt'}
          onChange={(val) => patchConfig({ icon_name: val ?? 'bx:slider-alt' })}
          searchable
          clearable={false}
          leftSection={<Icon icon={config.icon_name || 'bx:slider-alt'} width={14} />}
        />

        <Select
          label="Title Size"
          description="Choose the size of the component title"
          data={TITLE_SIZES}
          value={config.title_size ?? 'md'}
          onChange={(val) => patchConfig({ title_size: val ?? 'md' })}
          allowDeselect={false}
        />

        <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
          Grounded against <strong>{fixture.fileName}</strong>. Preview only — the catalog entry is a bare{' '}
          <code>{'{ component: interactive }'}</code>; the column, control type and styling aren't persisted yet.
        </Alert>
      </Stack>
    </Card>
  );

  return <DesignShell hideColumns formSlot={form} previewSlot={<ControlPreview />} />;
}
