/**
 * Shared "Cross-filtering" Accordion section used by figure, table, and map
 * builders to expose the toggle that controls whether selections on this
 * component emit a dashboard-wide filter, and which column drives the filter.
 *
 * Wraps a single `Accordion.Item` (caller owns the surrounding `Accordion`)
 * so each builder can compose it alongside its own sections (table's
 * "Display options", figure's parameter accordions, map's settings) without
 * forcing the same outer accordion structure across all three.
 *
 * Per-component config keys differ (figure & map use `selection_enabled` /
 * `selection_column`; table uses `row_selection_enabled` /
 * `row_selection_column`). To keep the storage detail in the caller, the
 * section receives the values and onChange callbacks, not the keys.
 */
import React from 'react';
import { Accordion, Stack, Switch, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import ColumnSelect from './ColumnSelect';

export interface CrossFilterSectionProps {
  /** Accordion item value — caller must include in `defaultValue` if it
   *  wants the section expanded by default. */
  itemValue?: string;
  /** Current "enable cross-filtering" switch value. */
  enabled: boolean;
  onEnabledChange: (next: boolean) => void;
  /** Current selection column (column extracted from each selected element). */
  column: string | null | undefined;
  onColumnChange: (next: string | null) => void;
  /** Override the column picker's label — e.g. "Selection column" for figure /
   *  map, "Row column" for table. Defaults to "Selection Column". */
  columnLabel?: string;
  /** Override the column-picker description. */
  columnDescription?: string;
}

const CrossFilterSection: React.FC<CrossFilterSectionProps> = ({
  itemValue = 'cross-filter',
  enabled,
  onEnabledChange,
  column,
  onColumnChange,
  columnLabel = 'Selection Column',
  columnDescription = 'Column to extract from selected elements',
}) => {
  return (
    <Accordion.Item value={itemValue}>
      <Accordion.Control
        icon={<Icon icon="mdi:filter-cog" width={18} height={18} />}
      >
        <Text fw={700} size="sm">
          Cross-filtering
        </Text>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="sm">
          <Switch
            label="Enable cross-filtering selection"
            description="When on, selections on this component filter the rest of the dashboard."
            checked={enabled}
            onChange={(e) => onEnabledChange(e.currentTarget.checked)}
          />
          <ColumnSelect
            label={columnLabel}
            description={columnDescription}
            value={column}
            onChange={(name) => onColumnChange(name)}
            clearable
            disabled={!enabled}
          />
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
};

export default CrossFilterSection;
