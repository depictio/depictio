import React from 'react';
import { Badge, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import {
  activeFiltersFor,
  filterDisplayLabel,
  formatFilterValue,
} from '../../activeFilters';

interface FilterChipsProps {
  filters: InteractiveFilter[];
  /** Full stored_metadata — chart/table selections resolve their label from
   *  their source component, which is not an interactive component. */
  components: StoredMetadata[];
  /** Emits `{ index, value: null, source }`, which mergeFiltersBySource
   *  interprets as "drop the entry for this (index, source) pair". */
  onClear: (filter: InteractiveFilter) => void;
}

/**
 * Removable summary of everything currently narrowing the dashboard.
 *
 * Without this the only way to see which filters are on is to scroll the whole
 * panel, and the only way to undo one is to find its control. Selections made
 * on a chart, table or map appear here too, with a distinct icon, so the single
 * "clear this one" gesture works the same regardless of where a filter came from.
 */
const FilterChips: React.FC<FilterChipsProps> = ({ filters, components, onClear }) => {
  const active = activeFiltersFor(filters);
  if (active.length === 0) return null;

  return (
    <Group gap={4} wrap="wrap">
      {active.map((f) => {
        const label = filterDisplayLabel(f, components);
        const value = formatFilterValue(f);
        const fromSelection = f.source !== undefined;
        return (
          <Tooltip
            key={`${f.index}:${f.source ?? ''}`}
            label={
              fromSelection
                ? `Selection on ${label}${value ? ` — ${value}` : ''}`
                : `${label}${value ? ` — ${value}` : ''}`
            }
            withArrow
            openDelay={400}
          >
            <Badge
              variant="light"
              color={fromSelection ? 'grape' : 'blue'}
              size="sm"
              radius="sm"
              style={{ cursor: 'default', textTransform: 'none' }}
              leftSection={
                fromSelection ? (
                  <Icon icon="mdi:selection-drag" width={11} height={11} />
                ) : undefined
              }
              rightSection={
                <Icon
                  icon="mdi:close"
                  width={12}
                  height={12}
                  role="button"
                  aria-label={`Clear filter ${label}`}
                  style={{ cursor: 'pointer', display: 'block' }}
                  onClick={() => onClear({ ...f, value: null })}
                />
              }
            >
              <Text span size="xs" fw={500}>
                {label}
              </Text>
              {value && (
                <Text span size="xs" c="dimmed">
                  {` ${value}`}
                </Text>
              )}
            </Badge>
          </Tooltip>
        );
      })}
    </Group>
  );
};

export default FilterChips;
