/**
 * Interactive component builder. Mirrors design_interactive() at
 * depictio/dash/modules/interactive_component/design_ui.py:22-317 verbatim:
 *
 *   1. Title (TextInput)
 *   2. Column (Select)
 *   3. Variant (Select — interactive component type)
 *   4. Color (ColorInput, with theme-auto placeholder)
 *   5. Icon (Select with searchable icon list)
 *   6. Title Size (Select)
 *
 * No min/max/marks/default-range fields — those are computed at render time
 * from the column's precomputed specs, mirroring Dash's stepper. Variant
 * subforms intentionally not rendered here.
 *
 * The right pane shows the live preview (`InteractivePreview`) of the chosen
 * control, identical to the Dash "Resulting interactive component" panel.
 */
import React, { useEffect, useMemo } from 'react';
import {
  Card,
  Center,
  ColorInput,
  Select,
  Stack,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  CheckboxSwitchRenderer,
  DatePickerRenderer,
  MultiSelectRenderer,
  RangeSliderRenderer,
  SegmentedControlRenderer,
  SliderRenderer,
} from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import DesignShell from '../shared/DesignShell';
import PreviewPanel from '../shared/PreviewPanel';
import { inputMethodsForType } from '../aggFunctions';

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

// Mirrors design_ui.py:111-159 icon list verbatim.
const ICON_OPTIONS: { value: string; label: string }[] = [
  { value: 'bx:slider-alt', label: 'Slider Alt' },
  { value: 'mdi:chart-line', label: 'Chart Line' },
  { value: 'mdi:counter', label: 'Counter' },
  { value: 'mdi:thermometer', label: 'Thermometer' },
  { value: 'mdi:water', label: 'Water' },
  { value: 'mdi:flask', label: 'Flask' },
  { value: 'mdi:air-filter', label: 'Air Filter' },
  { value: 'mdi:flash', label: 'Flash' },
  { value: 'mdi:gauge', label: 'Gauge' },
  { value: 'mdi:water-percent', label: 'Water Percent' },
  { value: 'mdi:ruler', label: 'Ruler' },
  { value: 'mdi:blur', label: 'Blur' },
  { value: 'mdi:leaf', label: 'Leaf' },
  { value: 'mdi:check-circle', label: 'Check Circle' },
  { value: 'mdi:target', label: 'Target' },
  { value: 'mdi:bullseye-arrow', label: 'Bullseye Arrow' },
  { value: 'mdi:flask-empty', label: 'Flask Empty' },
  { value: 'mdi:shield-check', label: 'Shield Check' },
  { value: 'mdi:chart-bell-curve', label: 'Chart Bell Curve' },
  { value: 'mdi:scatter-plot', label: 'Scatter Plot' },
  { value: 'mdi:alert-circle', label: 'Alert Circle' },
  { value: 'mdi:sine-wave', label: 'Sine Wave' },
  { value: 'mdi:beaker', label: 'Beaker' },
  { value: 'mdi:speedometer', label: 'Speedometer' },
  { value: 'mdi:flash-outline', label: 'Flash Outline' },
  { value: 'mdi:trending-up', label: 'Trending Up' },
  { value: 'mdi:dna', label: 'DNA' },
  { value: 'mdi:map-marker-path', label: 'Map Marker Path' },
  { value: 'mdi:content-copy', label: 'Content Copy' },
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

interface InteractiveConfig {
  interactive_component_type?: string;
  column_name?: string;
  column_type?: string;
  title?: string;
  title_size?: string;
  color?: string;
  icon_name?: string;
}

/**
 * Live preview that mounts the SAME renderer the dashboard grid uses
 * (SliderRenderer, RangeSliderRenderer, MultiSelectRenderer, …) with a
 * synthetic metadata pointing at the user's chosen column. So the preview is
 * pixel-identical to the final rendered component, including slider mark
 * values, icon coloring, and the dimmed current-value readout.
 *
 * Sized to ~320px (a typical interactive cell in the dashboard), so it
 * doesn't dominate the right pane.
 */
const InteractivePreview: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as InteractiveConfig;
  const dcId = useBuilderStore((s) => s.dcId);
  const wfId = useBuilderStore((s) => s.wfId);

  const { interactive_component_type, column_name, column_type, title, color, icon_name } =
    config;

  if (!column_name || !interactive_component_type || !dcId) {
    return (
      <PreviewPanel
        empty
        emptyMessage="Pick a column and control type to see a live preview."
        minHeight={180}
      />
    );
  }

  // Synthesize the same StoredMetadata shape the live dashboard would feed
  // into the renderer. `index` is a stable preview key so renderer-internal
  // caches dedupe correctly across rerenders. Sliders need scale + marks
  // inside default_state — that's where the renderer reads them, mirroring
  // the seeded defaults.
  const metadata: StoredMetadata = {
    index: `__preview__:${dcId}:${column_name}:${interactive_component_type}`,
    component_type: 'interactive',
    interactive_component_type,
    column_name,
    column_type,
    wf_id: wfId || undefined,
    dc_id: dcId,
    title: title?.trim() || `${interactive_component_type} on ${column_name}`,
    icon_name: icon_name || 'bx:slider-alt',
    icon_color: color && color.length > 0 ? color : undefined,
    color: color || '',
    default_state: {
      scale: 'linear',
      marks_number: 5,
    } as StoredMetadata['default_state'],
  };

  let renderer: React.ReactNode;
  switch (interactive_component_type) {
    case 'MultiSelect':
    case 'Select':
      renderer = <MultiSelectRenderer metadata={metadata} filters={[]} />;
      break;
    case 'RangeSlider':
      renderer = <RangeSliderRenderer metadata={metadata} filters={[]} />;
      break;
    case 'Slider':
      renderer = <SliderRenderer metadata={metadata} filters={[]} />;
      break;
    case 'DateRangePicker':
    case 'DatePicker':
      renderer = <DatePickerRenderer metadata={metadata} filters={[]} />;
      break;
    case 'SegmentedControl':
      renderer = <SegmentedControlRenderer metadata={metadata} filters={[]} />;
      break;
    case 'Switch':
    case 'Checkbox':
      renderer = <CheckboxSwitchRenderer metadata={metadata} filters={[]} />;
      break;
    default:
      renderer = null;
  }

  return (
    <PreviewPanel minHeight={180}>
      <Center style={{ width: '100%', padding: '0.5rem' }}>
        <div style={{ width: 320, maxWidth: '100%' }}>{renderer}</div>
      </Center>
    </PreviewPanel>
  );
};

const InteractiveBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as InteractiveConfig;
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const cols = useBuilderStore((s) => s.cols);

  const nunique = useMemo<number | undefined>(() => {
    if (!config.column_name) return undefined;
    const c = cols.find((c) => c.name === config.column_name);
    const v = c?.specs?.nunique;
    return typeof v === 'number' ? v : undefined;
  }, [cols, config.column_name]);

  const variants = useMemo(
    () => inputMethodsForType(config.column_type, nunique),
    [config.column_type, nunique],
  );

  // Auto-pick a sensible default variant when the column type changes and
  // the current selection is no longer valid.
  useEffect(() => {
    if (!config.interactive_component_type && variants.length) {
      patchConfig({ interactive_component_type: variants[0].value });
    } else if (
      config.interactive_component_type &&
      !variants.some((v) => v.value === config.interactive_component_type)
    ) {
      patchConfig({ interactive_component_type: variants[0]?.value ?? null });
    }
  }, [config.column_type, variants, config.interactive_component_type, patchConfig]);

  // Defaults applied once on first mount, mirroring Dash design_ui defaults
  // (Icon='bx:slider-alt', Title Size='md').
  useEffect(() => {
    patchConfig({
      icon_name: config.icon_name ?? 'bx:slider-alt',
      title_size: config.title_size ?? 'md',
      color: config.color ?? '',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          onChange={(name, type) =>
            patchConfig({ column_name: name, column_type: type })
          }
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
          onChange={(val) => patchConfig({ interactive_component_type: val })}
          leftSection={
            <Icon
              icon={VARIANT_ICONS[selected ?? ''] || 'bx:slider-alt'}
              width={14}
            />
          }
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
          swatches={[
            '#9966cc', // purple
            '#228be6', // blue
            '#15aabf', // teal
            '#40c057', // green
            '#fab005', // yellow
            '#fd7e14', // orange
            '#e6779f', // pink
            '#fa5252', // red
            '#7950f2', // violet
            '#000000', // black
          ]}
        />

        <Select
          label="Icon"
          description="Select an icon for your component"
          data={ICON_OPTIONS}
          value={config.icon_name ?? 'bx:slider-alt'}
          onChange={(val) =>
            patchConfig({ icon_name: val ?? 'bx:slider-alt' })
          }
          searchable
          clearable={false}
          leftSection={
            <Icon
              icon={config.icon_name || 'bx:slider-alt'}
              width={14}
            />
          }
        />

        <Select
          label="Title Size"
          description="Choose the size of the component title"
          data={TITLE_SIZES}
          value={config.title_size ?? 'md'}
          onChange={(val) => patchConfig({ title_size: val ?? 'md' })}
          allowDeselect={false}
        />
      </Stack>
    </Card>
  );

  return <DesignShell formSlot={form} previewSlot={<InteractivePreview />} />;
};

export default InteractiveBuilder;
