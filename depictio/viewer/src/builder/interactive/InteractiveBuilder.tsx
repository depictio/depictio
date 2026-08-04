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
import React, { useEffect, useMemo, useState } from 'react';
import {
  Autocomplete,
  Card,
  Center,
  ColorInput,
  Fieldset,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  CheckboxSwitchRenderer,
  DatePickerRenderer,
  fetchDashboard,
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

interface InteractiveConfig {
  interactive_component_type?: string;
  column_name?: string;
  column_type?: string;
  title?: string;
  color?: string;
  icon_name?: string;
  // Left-panel placement — consumed by FilterPanel in depictio-react-core.
  section?: string;
  group?: string;
  placement?: string;
  show_marks?: boolean;
}

/** Variants whose renderers read `show_marks`. */
const MARKS_VARIANTS = ['Slider', 'RangeSlider', 'Timeline'];
/** Mirrors TOP_PANEL_INTERACTIVE_TYPES in depictio/models/components/constants.py. */
const TOP_PLACEMENT_VARIANTS = ['Timeline'];

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
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const componentId = useBuilderStore((s) => s.componentId);

  // The dashboard's other interactive components, used only to suggest the
  // section and group names already in use. Both fields stay free text, so a
  // failed fetch degrades to "no suggestions" rather than blocking authoring.
  const [siblings, setSiblings] = useState<StoredMetadata[]>([]);
  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchDashboard(dashboardId)
      .then((dash) => {
        if (cancelled) return;
        setSiblings(
          (dash.stored_metadata || []).filter(
            (m) =>
              m.component_type === 'interactive' &&
              String(m.index) !== String(componentId),
          ),
        );
      })
      .catch((err) => {
        console.warn('[InteractiveBuilder] section/group suggestions unavailable:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, componentId]);

  const sectionOptions = useMemo(
    () =>
      [
        ...new Set(
          siblings.map((m) => m.section).filter((s): s is string => Boolean(s)),
        ),
      ].sort(),
    [siblings],
  );

  // Groups are scoped to the chosen section: a group may not span two sections
  // (validate_interactive_groups in depictio/models/models/dashboards.py), so
  // offering another section's groups here would only produce invalid YAML.
  const groupOptions = useMemo(() => {
    const scope = config.section
      ? siblings.filter((m) => m.section === config.section)
      : siblings.filter((m) => !m.section);
    return [
      ...new Set(scope.map((m) => m.group).filter((g): g is string => Boolean(g))),
    ].sort();
  }, [siblings, config.section]);

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
  // (Icon='bx:slider-alt'). No title size: interactive titles render at one
  // fixed size so the Filters panel stays uniform — see
  // `components/interactive/frame.tsx` in depictio-react-core.
  useEffect(() => {
    patchConfig({
      icon_name: config.icon_name ?? 'bx:slider-alt',
      color: config.color ?? '',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = config.interactive_component_type;
  const supportsTop = TOP_PLACEMENT_VARIANTS.includes(selected ?? '');
  const supportsMarks = MARKS_VARIANTS.includes(selected ?? '');

  // Switching an existing top-placed Timeline to another variant would leave
  // `placement: 'top'` on a type the model rejects, so drop it here as well as
  // in buildInteractive — the user sees the control revert instead of hitting
  // a save error.
  useEffect(() => {
    if (config.placement === 'top' && !supportsTop) {
      patchConfig({ placement: 'left' });
    }
  }, [config.placement, supportsTop, patchConfig]);

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

        <Fieldset legend="Panel placement" variant="filled" radius="md">
          <Stack gap="sm">
            <Text size="xs" c="dimmed">
              Sections are the filter panel&apos;s collapsible outer level; groups stack
              a few related controls inside one compact card. Leave both empty to
              render this control on its own.
            </Text>

            <Autocomplete
              label="Section"
              description="Existing sections are suggested — type a new name to create one"
              placeholder="No section"
              data={sectionOptions}
              value={config.section ?? ''}
              onChange={(val) => patchConfig({ section: val })}
              leftSection={<Icon icon="mdi:format-list-group" width={14} />}
              clearable
            />

            <Autocomplete
              label="Group"
              description="Controls sharing a group render together in one collapsible card"
              placeholder="No group"
              data={groupOptions}
              value={config.group ?? ''}
              onChange={(val) => patchConfig({ group: val })}
              leftSection={<Icon icon="mdi:card-multiple-outline" width={14} />}
              clearable
            />

            <div>
              <Text size="sm" fw={500} mb={4}>
                Placement
              </Text>
              <SegmentedControl
                fullWidth
                size="xs"
                value={config.placement === 'top' ? 'top' : 'left'}
                onChange={(val) => patchConfig({ placement: val })}
                data={[
                  { value: 'left', label: 'Left panel' },
                  { value: 'top', label: 'Bottom strip', disabled: !supportsTop },
                ]}
              />
              {!supportsTop && (
                <Text size="xs" c="dimmed" mt={4}>
                  The full-width strip is reserved for the Timeline control.
                </Text>
              )}
            </div>

            {supportsMarks && (
              <Switch
                label="Show tick marks"
                description="Leave off inside a group for a denser panel"
                checked={config.show_marks === true}
                onChange={(e) => patchConfig({ show_marks: e.currentTarget.checked })}
              />
            )}
          </Stack>
        </Fieldset>
      </Stack>
    </Card>
  );

  return <DesignShell formSlot={form} previewSlot={<InteractivePreview />} />;
};

export default InteractiveBuilder;
