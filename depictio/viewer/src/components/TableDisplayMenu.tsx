import React from 'react';
import {
  ActionIcon,
  Box,
  Center,
  Checkbox,
  Divider,
  Group,
  Menu,
  SegmentedControl,
  Text,
  Tooltip,
} from '@mantine/core';
import { Eye, Lock, RotateCcw, Rows3, Rows4, TableProperties } from 'lucide-react';

import type { UseTableColumnsResult } from '../lib/useTableColumns';
import { useListingAccents } from '../lib/useListingAccents';

export type TableDensity = 'cozy' | 'compact';

export interface TableDisplayMenuProps<K extends string> {
  /** Whose accent the trigger wears once the view is customised. */
  section: 'dashboards' | 'projects';
  density: TableDensity;
  /** The density a fresh browser gets, so Reset can return to it. */
  defaultDensity: TableDensity;
  onDensityChange: (density: TableDensity) => void;
  columns: UseTableColumnsResult<K>;
}

const DENSITY_DATA = [
  {
    value: 'cozy',
    label: (
      <Center style={{ gap: 6 }}>
        <Rows3 size={14} />
        <span>Comfortable</span>
      </Center>
    ),
  },
  {
    value: 'compact',
    label: (
      <Center style={{ gap: 6 }}>
        <Rows4 size={14} />
        <span>Compact</span>
      </Center>
    ),
  },
];

/**
 * Table view options, in the toolbar slot the thumbnails' Card display menu
 * uses: row density, and which columns the table shows.
 *
 * The menu stays open across clicks so several columns can be toggled while
 * the table reflows behind it. Columns the user cannot hide stay listed with a
 * lock, so it is clear why they have no box.
 */
function TableDisplayMenu<K extends string>({
  section,
  density,
  defaultDensity,
  onDensityChange,
  columns,
}: TableDisplayMenuProps<K>) {
  const accent = useListingAccents(section);
  const { allColumns, visibleColumns, isVisible, toggle, reset, showAll, isCustomized } =
    columns;
  const customised = isCustomized || density !== defaultDensity;
  const allShown = visibleColumns.length === allColumns.length;

  return (
    <Menu
      shadow="md"
      width={280}
      closeOnItemClick={false}
      withinPortal
      position="bottom-end"
    >
      <Menu.Target>
        <Tooltip label="Table display" withinPortal>
          <ActionIcon
            variant={customised ? 'light' : 'default'}
            color={customised ? accent.tertiary : undefined}
            size="lg"
            radius="md"
            aria-label="Table display"
            data-testid="table-display-menu"
          >
            <TableProperties size={18} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown className="table-display-menu">
        <Menu.Label>Rows</Menu.Label>
        <Box px="sm" pb="xs">
          <SegmentedControl
            size="xs"
            fullWidth
            value={density}
            onChange={(v) => onDensityChange(v === 'compact' ? 'compact' : 'cozy')}
            data={DENSITY_DATA}
            aria-label="Row density"
          />
        </Box>
        <Divider my={4} />
        <Menu.Label>
          <Group justify="space-between" wrap="nowrap">
            <span>Columns</span>
            <Text span size="xs" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {visibleColumns.length} of {allColumns.length} shown
            </Text>
          </Group>
        </Menu.Label>
        <div style={{ maxHeight: 320, overflowY: 'auto' }}>
          {allColumns.map((col) => {
            const shown = isVisible(col.key);
            // The header text leads; the longer name follows only when it
            // says more than the header ("DC" → "Data collections").
            const hint =
              col.description &&
              !col.description.toLowerCase().includes(col.label.toLowerCase())
                ? col.description
                : null;
            return (
              <Menu.Item
                key={col.key}
                disabled={col.alwaysVisible}
                onClick={() => toggle(col.key)}
                leftSection={
                  col.alwaysVisible ? (
                    <Center w={16}>
                      <Lock size={13} />
                    </Center>
                  ) : (
                    // Presentational: the row owns the toggle, and without
                    // pointer events a click on the box itself reaches it too.
                    <Checkbox
                      size="xs"
                      checked={shown}
                      readOnly
                      tabIndex={-1}
                      style={{ pointerEvents: 'none' }}
                    />
                  )
                }
                rightSection={
                  col.alwaysVisible ? (
                    <Text span size="xs" c="dimmed">
                      Always
                    </Text>
                  ) : null
                }
              >
                <Text span size="sm" display="block" lh={1.3}>
                  {col.label}
                </Text>
                {hint && (
                  <Text span size="xs" c="dimmed" display="block" lh={1.3}>
                    {hint}
                  </Text>
                )}
              </Menu.Item>
            );
          })}
        </div>
        <Divider my={4} />
        {/* Menu items rather than buttons: a disabled one stays flat instead
            of turning into a grey slab. */}
        <Group grow gap={4} wrap="nowrap">
          <Menu.Item leftSection={<Eye size={14} />} disabled={allShown} onClick={showAll}>
            Show all
          </Menu.Item>
          <Menu.Item
            leftSection={<RotateCcw size={14} />}
            disabled={!customised}
            onClick={() => {
              reset();
              onDensityChange(defaultDensity);
            }}
          >
            Reset
          </Menu.Item>
        </Group>
      </Menu.Dropdown>
    </Menu>
  );
}

export default TableDisplayMenu;
