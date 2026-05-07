import React, { useCallback } from 'react';
import { Paper, Stack, Text, Group, MultiSelect } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * MultiSelect interactive filter component. Mirrors the DMC-based render in
 * `depictio/dash/modules/interactive_component/utils.py:_build_select_component`
 * when interactive_component_type === "MultiSelect".
 *
 * Emits selected values via Dash `setProps({ value })` (when consumed by Dash)
 * or via the React `onChange` callback (when consumed by React viewer).
 */
export interface MultiSelectOption {
  value: string;
  label: string;
}

export interface DepictioMultiSelectProps {
  id?: string | Record<string, string>;
  /** Heading shown above the select. */
  title?: string;
  /** Dataframe column this filter targets — included for label context. */
  column_name?: string;
  /** Interactive component subtype, used as the prefix in default titles. */
  interactive_component_type?: string;
  /** Selectable options. Each `value` is what flows to the interactive-values-store. */
  options?: MultiSelectOption[] | string[];
  /** Currently selected values. */
  value?: string[] | null;
  /** Placeholder text shown when empty. */
  placeholder?: string;
  /** Mantine color name or CSS color for the accent border. */
  color?: string;
  /** Iconify ID for the leading icon. */
  icon_name?: string;
  /** Mantine color token name (e.g. 'blue', 'orange') used as the icon tint. */
  icon_color?: string;
  /** CSS color string applied to the title text. */
  title_color?: string;
  /** Mantine size token for the title text ('xs', 'sm', 'md', 'lg', 'xl'). */
  title_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  /** Set to true to allow clearing all selected. */
  clearable?: boolean;
  /** Set to true to enable free-text search within options. */
  searchable?: boolean;
  /** Max options rendered in dropdown (virtualization hint). */
  limit?: number;
  /** Dash setProps — when present, changing the selection triggers Dash callbacks. */
  setProps?: (props: Partial<DepictioMultiSelectProps>) => void;
  /** Non-Dash React onChange handler for the React viewer use case. */
  onChange?: (value: string[]) => void;
}

const normalizeOptions = (
  options: MultiSelectOption[] | string[] | undefined,
): MultiSelectOption[] => {
  if (!options) return [];
  return options.map((o) =>
    typeof o === 'string' ? { value: o, label: o } : o,
  );
};

const DepictioMultiSelect: React.FC<DepictioMultiSelectProps> = ({
  title,
  column_name,
  interactive_component_type,
  options,
  value,
  placeholder,
  color,
  icon_name,
  icon_color,
  title_color,
  title_size = 'sm',
  clearable = true,
  searchable = true,
  limit = 100,
  setProps,
  onChange,
}) => {
  const handleChange = useCallback(
    (next: string[]) => {
      if (setProps) setProps({ value: next });
      if (onChange) onChange(next);
    },
    [setProps, onChange],
  );

  // Default title format mirrors depictio/dash/modules/interactive_component
  // /utils.py:_build_component_title — `{type} on {column}`.
  const displayTitle =
    title ||
    (column_name
      ? `${interactive_component_type || 'Filter'} on ${column_name}`
      : '');
  // Resolve a metadata "color" field that can be either a Mantine token
  // name ("blue", "orange", "green") or a raw CSS color (#hex, rgb(...)).
  const resolveColor = (c?: string): string | undefined => {
    if (!c) return undefined;
    if (c.startsWith('#') || c.startsWith('rgb') || c.startsWith('var(')) return c;
    return `var(--mantine-color-${c}-6)`;
  };
  const iconColResolved =
    resolveColor(icon_color) ||
    resolveColor(color) ||
    'var(--mantine-color-blue-6)';
  const titleColorResolved =
    resolveColor(title_color) ||
    resolveColor(color) ||
    'var(--mantine-color-text)';

  return (
    <Paper
      p="xs"
      radius="md"
      shadow="xs"
      withBorder
      className="dashboard-component-hover"
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
      }}
    >
      <Stack gap={4} style={{ flex: 1 }}>
        {displayTitle && (
          <Group gap="xs" align="center" wrap="nowrap">
            {icon_name && (
              <Icon
                icon={icon_name}
                width={18}
                height={18}
                style={{ color: iconColResolved, flexShrink: 0 }}
              />
            )}
            <Text fw={600} size={title_size} style={{ color: titleColorResolved }}>
              {displayTitle}
            </Text>
          </Group>
        )}
        <MultiSelect
          data={normalizeOptions(options)}
          value={value || []}
          onChange={handleChange}
          placeholder={placeholder || `Select ${column_name || 'values'}...`}
          searchable={searchable}
          clearable={clearable}
          limit={limit}
          maxDropdownHeight={220}
          comboboxProps={{ withinPortal: true }}
        />
      </Stack>
    </Paper>
  );
};

export default DepictioMultiSelect;
