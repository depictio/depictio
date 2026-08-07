/**
 * Create / edit one section's presentation. Rendered inline inside the list, so
 * the section being edited stays in place among its siblings.
 */
import React, { useState } from 'react';
import {
  Button,
  ColorSwatch,
  Group,
  Paper,
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

export interface SectionFormProps {
  /** null = create a new section. */
  initial: FilterSectionSpec | null;
  /** Lower-cased names already used in this namespace, excluding this section. */
  taken: string[];
  onSubmit: (spec: FilterSectionSpec) => void;
  onCancel: () => void;
}

const SectionForm: React.FC<SectionFormProps> = ({ initial, taken, onSubmit, onCancel }) => {
  const [name, setName] = useState(initial?.name ?? '');
  const [icon, setIcon] = useState(initial?.icon ?? '');
  const [color, setColor] = useState(initial?.color ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [collapsed, setCollapsed] = useState(initial?.collapsed ?? false);

  const trimmed = name.trim();
  const duplicate = taken.includes(trimmed.toLowerCase());
  const canSubmit = trimmed.length > 0 && !duplicate;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit({
      name: trimmed,
      // Empty strings are dropped rather than persisted: the models treat an
      // absent icon/colour/description as "no override", and an empty string
      // would round-trip into the YAML as a key that means nothing.
      icon: icon || undefined,
      color: color || undefined,
      description: description.trim() || undefined,
      collapsed,
    });
  };

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="sm">
        <Group align="flex-end" gap="sm" wrap="nowrap">
          {/* Live preview of exactly what the section header will draw. */}
          <SectionIcon
            spec={{ icon, color }}
            size={20}
            fallbackIcon="mdi:shape-outline"
          />
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
                    option.value
                      ? `var(--mantine-color-${option.value}-6)`
                      : 'transparent'
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

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {initial ? 'Save section' : 'Add section'}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
};

export default SectionForm;
