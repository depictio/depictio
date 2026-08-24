/**
 * The fields of one section's presentation — no chrome, no buttons.
 *
 * Add and edit are the same form, so it lives in one place and `SectionModal`
 * supplies the surface, the title and the actions. It keeps its own field state
 * and reports the spec upwards on every change (`null` while the name is empty
 * or already taken), which is what lets the modal's submit button reflect
 * validity without reaching into the form.
 */
import React, { useEffect, useState } from 'react';
import {
  ColorSwatch,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { SectionIcon } from 'depictio-react-core';
import type { FilterSectionSpec } from 'depictio-react-core';

import { SECTION_COLOR_OPTIONS, iconOptionsWith } from './sectionIcons';
import type { SectionKind } from './sectionMutations';

export interface SectionFormProps {
  /** null = a new section. */
  initial: FilterSectionSpec | null;
  /** Which list the section belongs to. Offered as a field only while
   *  creating: moving a section between the panel and the grid is not an
   *  operation the reducer has, and its components would have to move with it. */
  kind: SectionKind;
  onKindChange?: (kind: SectionKind) => void;
  /** Lower-cased names already used in `kind`'s namespace, excluding this
   *  section. Recomputed by the modal when the namespace changes. */
  taken: string[];
  /** The spec as it currently stands, or null while it cannot be submitted. */
  onChange: (spec: FilterSectionSpec | null) => void;
}

const SectionForm: React.FC<SectionFormProps> = ({
  initial,
  kind,
  onKindChange,
  taken,
  onChange,
}) => {
  const [name, setName] = useState(initial?.name ?? '');
  const [icon, setIcon] = useState(initial?.icon ?? '');
  const [color, setColor] = useState(initial?.color ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [collapsed, setCollapsed] = useState(initial?.collapsed ?? false);
  const [persistent, setPersistent] = useState(initial?.persistent ?? false);
  const [pin, setPin] = useState<'top' | 'bottom'>(
    initial?.pin === 'bottom' ? 'bottom' : 'top',
  );

  const trimmed = name.trim();
  const duplicate = taken.includes(trimmed.toLowerCase());
  const valid = trimmed.length > 0 && !duplicate;

  useEffect(() => {
    onChange(
      valid
        ? {
            name: trimmed,
            // Empty strings are dropped rather than persisted: the models treat
            // an absent icon/colour/description as "no override", and an empty
            // string would round-trip into the YAML as a key that means nothing.
            icon: icon || undefined,
            color: color || undefined,
            description: description.trim() || undefined,
            collapsed,
            persistent,
            // Meaningless on a section that shows on one tab only — left out so
            // it does not round-trip into the YAML as a setting that does
            // nothing.
            pin: persistent ? pin : undefined,
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valid, trimmed, icon, color, description, collapsed, persistent, pin]);

  return (
    <Stack gap="md">
      {onKindChange && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Where it lives
          </Text>
          <SegmentedControl
            fullWidth
            color="grape"
            value={kind}
            onChange={(v) => onKindChange(v as SectionKind)}
            data={[
              {
                value: 'grid',
                label: (
                  <Group gap={6} justify="center" wrap="nowrap">
                    <Icon icon="mdi:view-grid-outline" width={14} />
                    <span>Dashboard grid</span>
                  </Group>
                ),
              },
              {
                value: 'filter',
                label: (
                  <Group gap={6} justify="center" wrap="nowrap">
                    <Icon icon="mdi:filter-variant" width={14} />
                    <span>Filter panel</span>
                  </Group>
                ),
              },
            ]}
          />
          <Text size="xs" c="dimmed">
            The two keep separate lists, so the same name can mean a different
            section in each.
          </Text>
        </Stack>
      )}

      <Group align="flex-end" gap="sm" wrap="nowrap">
        {/* Live preview of exactly what the section header will draw. */}
        <SectionIcon spec={{ icon, color }} size={20} fallbackIcon="mdi:shape-outline" />
        <TextInput
          label="Name"
          description="Components join a section by this name"
          placeholder="e.g. Quality"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          error={duplicate ? 'A section with this name already exists here' : undefined}
          style={{ flex: 1 }}
          data-autofocus
        />
      </Group>

      <Group grow align="flex-start">
        <Select
          label="Icon"
          placeholder="No icon"
          data={iconOptionsWith(initial?.icon)}
          value={icon || null}
          onChange={(v) => setIcon(v ?? '')}
          searchable
          clearable
          comboboxProps={{ withinPortal: false }}
          leftSection={
            icon ? <Icon icon={icon} width={16} /> : <Icon icon="mdi:shape-outline" width={16} />
          }
          renderOption={({ option }) => (
            <Group gap="xs" wrap="nowrap">
              <Icon icon={option.value} width={16} />
              <Text size="sm">{option.label}</Text>
            </Group>
          )}
        />
        <Select
          label="Colour"
          data={SECTION_COLOR_OPTIONS}
          value={color}
          onChange={(v) => setColor(v ?? '')}
          allowDeselect={false}
          comboboxProps={{ withinPortal: false }}
          leftSection={<Icon icon="mdi:palette" width={16} />}
          renderOption={({ option }) => (
            <Group gap="xs" wrap="nowrap">
              <ColorSwatch
                size={14}
                color={
                  option.value ? `var(--mantine-color-${option.value}-6)` : 'transparent'
                }
                withShadow={false}
              />
              <Text size="sm">{option.label}</Text>
            </Group>
          )}
        />
      </Group>

      <TextInput
        label="Description"
        description="Optional one-liner shown under the section title"
        placeholder="What this section covers"
        value={description}
        onChange={(e) => setDescription(e.currentTarget.value)}
      />

      <Switch
        label="Start collapsed"
        description="Applies to first-time visitors. Anyone who has already opened this dashboard keeps the state they left it in."
        checked={collapsed}
        onChange={(e) => setCollapsed(e.currentTarget.checked)}
      />

      <Switch
        label="Show on every tab"
        description="Renders this section on all of this dashboard's tabs; filter values set in it survive tab switches. Only affects dashboards with tabs."
        checked={persistent}
        onChange={(e) => setPersistent(e.currentTarget.checked)}
      />

      {persistent && (
        <Select
          label="Position on every tab"
          description="Where the section sits relative to each tab's own content, this one included."
          data={[
            { value: 'top', label: 'Before the tab’s own sections' },
            { value: 'bottom', label: 'After the tab’s own sections' },
          ]}
          value={pin}
          onChange={(v) => setPin(v === 'bottom' ? 'bottom' : 'top')}
          allowDeselect={false}
          comboboxProps={{ withinPortal: false }}
        />
      )}
    </Stack>
  );
};

export default SectionForm;
