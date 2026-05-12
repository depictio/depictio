/**
 * Single global filter, rendered as a Mantine Badge with a Popover that opens
 * the actual interactive renderer (RangeSlider, MultiSelect, …) for editing
 * the value. Includes a remove (×) affordance that demotes the filter back to
 * the source tab.
 */

import React, { useMemo, useState } from 'react';
import { ActionIcon, Badge, Group, Popover, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { GlobalFilterDef, StoredMetadata } from '../../api';
import MultiSelectRenderer from '../interactive/MultiSelectRenderer';
import RangeSliderRenderer from '../interactive/RangeSliderRenderer';
import SliderRenderer from '../interactive/SliderRenderer';
import DatePickerRenderer from '../interactive/DatePickerRenderer';
import SegmentedControlRenderer from '../interactive/SegmentedControlRenderer';
import CheckboxSwitchRenderer from '../interactive/CheckboxSwitchRenderer';

export interface GlobalFilterPillProps {
  def: GlobalFilterDef;
  value: unknown;
  onChange: (value: unknown) => void;
  onRemove: () => void;
  /** Optional: where to navigate when the user clicks "Open source tab". */
  onGoToSource?: () => void;
}

function describeValue(v: unknown): string {
  if (v === null || v === undefined) return '·';
  if (Array.isArray(v)) {
    if (v.length === 0) return '·';
    if (v.length <= 2) return v.map(String).join(', ');
    return `${v.length} selected`;
  }
  if (typeof v === 'object') {
    return JSON.stringify(v);
  }
  return String(v);
}

/**
 * Build a minimal `StoredMetadata` to drive the existing per-component
 * renderers. The renderers were designed to be filter-array-driven; we hand
 * them an isolated single-filter array keyed on the synthetic pill index and
 * relay updates back via `onChange`.
 */
function pillIndex(def: GlobalFilterDef): string {
  return `__global_pill_${def.id}`;
}

const GlobalFilterPill: React.FC<GlobalFilterPillProps> = ({
  def,
  value,
  onChange,
  onRemove,
  onGoToSource,
}) => {
  const [opened, setOpened] = useState(false);

  // Reuse the first link to drive the renderer (column_name, wf_id, dc_id are
  // needed by some renderers for fetching options/specs).
  const primaryLink = def.links[0];

  const fakeMetadata: StoredMetadata = useMemo(
    () => ({
      index: pillIndex(def),
      component_type: 'interactive',
      interactive_component_type: def.interactive_component_type,
      column_name: primaryLink?.column_name,
      column_type: def.column_type,
      wf_id: primaryLink?.wf_id,
      dc_id: primaryLink?.dc_id,
      default_state: def.default_state,
    }) as StoredMetadata,
    [def, primaryLink],
  );

  const filtersForRenderer = useMemo(
    () =>
      value !== undefined && value !== null
        ? [
            {
              index: pillIndex(def),
              value,
              column_name: primaryLink?.column_name,
              interactive_component_type: def.interactive_component_type,
            },
          ]
        : [],
    [def, value, primaryLink],
  );

  const handleFilterChange = (next: { value: unknown }) => {
    onChange(next.value);
  };

  const renderer = useMemo(() => {
    const props = {
      metadata: fakeMetadata,
      filters: filtersForRenderer,
      onFilterChange: handleFilterChange,
      compact: true,
    };
    switch (def.interactive_component_type) {
      case 'MultiSelect':
      case 'Select':
        return <MultiSelectRenderer {...props} />;
      case 'RangeSlider':
        return <RangeSliderRenderer {...props} />;
      case 'Slider':
        return <SliderRenderer {...props} />;
      case 'DatePicker':
      case 'DateRangePicker':
        return <DatePickerRenderer {...props} />;
      case 'SegmentedControl':
        return <SegmentedControlRenderer {...props} />;
      case 'Checkbox':
      case 'Switch':
        return <CheckboxSwitchRenderer {...props} />;
      default:
        return (
          <Text size="xs" c="dimmed">
            Editing this filter type ({def.interactive_component_type}) is not
            supported in the pill view yet.
          </Text>
        );
    }
    // The renderers themselves are pure-prop driven, so leaving the deps as
    // the inputs is safe — switching renderers is a remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def.interactive_component_type, fakeMetadata, filtersForRenderer]);

  const valueLabel = describeValue(value);

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-start"
      withArrow
      shadow="md"
      width={320}
      trapFocus
    >
      <Popover.Target>
        <Badge
          size="lg"
          radius="sm"
          variant="light"
          color="blue"
          style={{ cursor: 'pointer', paddingRight: 4 }}
          onClick={() => setOpened((o) => !o)}
          rightSection={
            <ActionIcon
              size="xs"
              variant="transparent"
              color="blue"
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              aria-label={`Remove global filter ${def.label}`}
            >
              <Icon icon="tabler:x" width={12} />
            </ActionIcon>
          }
          leftSection={<Icon icon="tabler:world" width={12} />}
        >
          <Text component="span" size="xs" fw={600}>
            {def.label}
          </Text>
          <Text component="span" size="xs" c="dimmed" ml={6}>
            {valueLabel}
          </Text>
        </Badge>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Group justify="space-between" align="center">
            <Text size="sm" fw={600}>
              {def.label}
            </Text>
            {onGoToSource && (
              <ActionIcon
                size="sm"
                variant="subtle"
                onClick={onGoToSource}
                aria-label="Open source tab"
              >
                <Icon icon="tabler:external-link" width={14} />
              </ActionIcon>
            )}
          </Group>
          {renderer}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

export default GlobalFilterPill;
