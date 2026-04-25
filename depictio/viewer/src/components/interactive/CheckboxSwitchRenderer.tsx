import React from 'react';
import { Paper, Stack, Group, Text, Checkbox, Switch } from '@mantine/core';
import { Icon } from '@iconify/react';

import { InteractiveFilter, StoredMetadata } from '../../api';

interface CheckboxSwitchRendererProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
}

/**
 * Renders a boolean interactive component (Checkbox or Switch). Mirrors
 * `_build_boolean_component` in
 * `depictio/dash/modules/interactive_component/utils.py` for visual parity:
 * title + optional Iconify icon above a Mantine Checkbox or Switch.
 *
 * No data fetch — pure boolean state. Reads default value from
 * `metadata.default_state.default_value` (string-coerced via the same rules
 * as the Dash backend: true / "1" / "yes" / "on" → true).
 *
 * Filter state lives in the parent App's filter array; we read the entry
 * matching `metadata.index`. On toggle we emit the boolean back via
 * `onChange` so the parent can update its filter state and re-run
 * `bulk_compute_cards` / re-render dependent components.
 */
const CheckboxSwitchRenderer: React.FC<CheckboxSwitchRendererProps> = ({
  metadata,
  filters,
  onChange,
}) => {
  const subType = metadata.interactive_component_type;
  if (subType !== 'Checkbox' && subType !== 'Switch') {
    throw new Error(
      `CheckboxSwitchRenderer received unsupported interactive_component_type: ${subType}`,
    );
  }

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const defaultBool = coerceBool(metadata.default_state?.default_value);
  const checked =
    typeof filterEntry?.value === 'boolean'
      ? (filterEntry.value as boolean)
      : defaultBool;

  const displayTitle =
    metadata.title ||
    (metadata.column_name ? `Filter on ${metadata.column_name}` : '');
  const iconCol = metadata.icon_color || 'var(--mantine-color-blue-6)';

  const emit = (next: boolean) => {
    onChange?.({
      index: metadata.index,
      value: next,
      column_name: metadata.column_name,
      interactive_component_type: subType,
    });
  };

  return (
    <Paper
      p="md"
      radius="md"
      shadow="xs"
      className="dashboard-component-hover"
      style={{
        backgroundColor: 'var(--app-surface-color, #ffffff)',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
      }}
    >
      <Stack gap="xs" style={{ flex: 1 }}>
        {displayTitle && (
          <Group gap="xs" align="center" wrap="nowrap">
            {metadata.icon_name && (
              <Icon
                icon={metadata.icon_name}
                width={18}
                height={18}
                style={{ color: iconCol, flexShrink: 0 }}
              />
            )}
            <Text
              fw={600}
              size="sm"
              style={{ color: 'var(--app-text-color, #1a1b1e)' }}
            >
              {displayTitle}
            </Text>
          </Group>
        )}
        {subType === 'Checkbox' ? (
          <Checkbox
            checked={checked}
            onChange={(event) => emit(event.currentTarget.checked)}
            color={metadata.icon_color || undefined}
            label={metadata.column_name || undefined}
          />
        ) : (
          <Switch
            checked={checked}
            onChange={(event) => emit(event.currentTarget.checked)}
            color={metadata.icon_color || undefined}
            label={metadata.column_name || undefined}
          />
        )}
      </Stack>
    </Paper>
  );
};

/**
 * Mirror the Dash backend's coercion (utils.py `_build_boolean_component`):
 *   string -> lower() in {"true", "1", "yes", "on"}
 *   bool   -> as-is
 *   None   -> false
 *   else   -> bool(value)
 */
function coerceBool(raw: unknown): boolean {
  if (raw === null || raw === undefined) return false;
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'string') {
    return ['true', '1', 'yes', 'on'].includes(raw.toLowerCase());
  }
  return Boolean(raw);
}

export default CheckboxSwitchRenderer;
