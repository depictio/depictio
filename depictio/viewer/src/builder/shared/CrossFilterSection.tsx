/**
 * Shared "Cross-filtering" Accordion section used by figure, table, and map
 * builders to expose the toggle that controls whether selections on this
 * component emit a dashboard-wide filter, and which column drives the filter.
 *
 * Wraps a single `BuilderSection` (caller owns the surrounding `BuilderSections`)
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
import { Stack } from '@mantine/core';
import ColumnSelect from './ColumnSelect';
import { BuilderSection, SwitchField } from './BuilderSections';

export interface CrossFilterSectionProps {
  /** Section value — caller lists it in `required` if it wants the section
   *  expanded by default. */
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
    <BuilderSection
      value={itemValue}
      icon="mdi:filter-cog"
      title="Cross-filtering"
      subtitle="Selections here filter the rest of the dashboard"
    >
      <Stack gap="sm">
        <SwitchField
          label="Enable cross-filtering selection"
          description="When on, selections on this component filter the rest of the dashboard."
          checked={enabled}
          onChange={onEnabledChange}
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
    </BuilderSection>
  );
};

export default CrossFilterSection;
