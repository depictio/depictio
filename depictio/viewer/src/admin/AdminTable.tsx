import React, { useCallback, useMemo, useState } from 'react';
import { ActionIcon, Group, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import SortHeader, { type SortDir } from '../components/SortHeader';
import TableDisplayMenu from '../components/TableDisplayMenu';
import { type ColumnDef, useTableColumns } from '../lib/useTableColumns';
import { useGlassPages } from '../chrome/variants/glass/pages';

/** One column of an admin table: the picker metadata plus how to sort and draw it. */
export interface AdminTableColumn<T, K extends string> extends ColumnDef<K> {
  /** Value the column sorts by. Dates as epoch ms; null/undefined sort last. Omit for an unsortable column. */
  sortValue?: (row: T) => string | number | null | undefined;
  render: (row: T) => React.ReactNode;
}

export interface AdminTableProps<T, K extends string> {
  rows: T[];
  rowKey: (row: T) => string;
  /** Must be referentially stable (module constant or useMemo). */
  columns: AdminTableColumn<T, K>[];
  /** localStorage key for the visible columns, e.g. 'depictio.admin.projects.columns.v1'. */
  storageKey: string;
  defaultSort: { key: K; dir?: SortDir };
  /** Everything a row can be found by; matched case-insensitively. */
  searchText: (row: T) => string;
  searchPlaceholder: string;
  /** The expandable body shown under a row. */
  renderDetail: (row: T) => React.ReactNode;
  /** Extra toolbar content, placed before the column menu (e.g. an "Add user" button). */
  toolbarExtra?: React.ReactNode;
  emptyLabel?: string;
}

function compareValues(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
  dir: SortDir,
): number {
  const aNull = a === null || a === undefined || a === '' || (typeof a === 'number' && Number.isNaN(a));
  const bNull = b === null || b === undefined || b === '' || (typeof b === 'number' && Number.isNaN(b));
  // Nulls last whatever the direction, so empty cells do not hop to the top on desc.
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  const mul = dir === 'asc' ? 1 : -1;
  if (typeof a === 'number' && typeof b === 'number') return mul * (a - b);
  return (
    mul *
    String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
  );
}

/** Interactive controls inside a row keep their own click: they must not toggle the detail. */
function isInteractive(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest('a, button, input, select, textarea, [role="button"], [role="radio"], label') !==
      null
  );
}

/**
 * Searchable, sortable table with a column picker and an expandable detail
 * row, shared by the admin Projects, Dashboards and Users panels.
 */
function AdminTable<T, K extends string>({
  rows,
  rowKey,
  columns,
  storageKey,
  defaultSort,
  searchText,
  searchPlaceholder,
  renderDetail,
  toolbarExtra,
  emptyLabel = 'No match',
}: AdminTableProps<T, K>) {
  const glass = useGlassPages();
  const columnState = useTableColumns<K>(storageKey, columns);
  const { isVisible } = columnState;
  // `columnState.visibleColumns` only carries the picker metadata; keep the full column.
  const visibleColumns = useMemo(
    () => columns.filter((c) => isVisible(c.key)),
    [columns, isVisible],
  );

  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 200);
  const [sortKey, setSortKey] = useState<K>(defaultSort.key);
  const [sortDir, setSortDir] = useState<SortDir>(defaultSort.dir ?? 'asc');
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  // A hidden column cannot stay the sort key: fall back to the default.
  const activeKey = isVisible(sortKey) ? sortKey : defaultSort.key;
  const activeDir = isVisible(sortKey) ? sortDir : (defaultSort.dir ?? 'asc');

  const toggleSort = useCallback(
    (key: K) => {
      if (key === activeKey) {
        setSortDir(activeDir === 'asc' ? 'desc' : 'asc');
      } else {
        setSortKey(key);
        setSortDir('asc');
      }
    },
    [activeKey, activeDir],
  );

  const toggleRow = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const shown = useMemo(() => {
    const q = debouncedSearch.trim().toLowerCase();
    const filtered = q ? rows.filter((r) => searchText(r).toLowerCase().includes(q)) : rows;
    const col = columns.find((c) => c.key === activeKey);
    const value = col?.sortValue;
    if (!value) return filtered;
    return [...filtered].sort((a, b) => compareValues(value(a), value(b), activeDir));
  }, [rows, debouncedSearch, searchText, columns, activeKey, activeDir]);

  return (
    <div className="ga-table">
      <Group gap="xs" wrap="nowrap" mb="sm" className="ga-table-toolbar">
        <TextInput
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          leftSection={<Icon icon="mdi:magnify" width={16} />}
          rightSection={
            search ? (
              <ActionIcon
                variant="subtle"
                color="gray"
                onClick={() => setSearch('')}
                aria-label="Clear search"
              >
                <Icon icon="mdi:close" width={14} />
              </ActionIcon>
            ) : null
          }
          style={{ flex: 1, minWidth: 0 }}
        />
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {shown.length === rows.length ? rows.length : `${shown.length} of ${rows.length}`}
        </Text>
        {toolbarExtra}
        <TableDisplayMenu section="admin" columns={columnState} />
      </Group>
      <div
        className="ga-table-frame"
        style={
          glass
            ? undefined
            : { border: '1px solid var(--mantine-color-default-border)', borderRadius: 8 }
        }
      >
        <div style={{ overflowX: 'auto' }}>
          <Table verticalSpacing="sm" highlightOnHover miw={Math.max(600, visibleColumns.length * 150)}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: 36 }} aria-label="Details" />
                {visibleColumns.map((col) => (
                  <Table.Th key={col.key} data-col={col.key}>
                    {col.sortValue ? (
                      <SortHeader
                        label={col.label}
                        tooltip={col.description}
                        active={activeKey === col.key}
                        dir={activeDir}
                        onClick={() => toggleSort(col.key)}
                      />
                    ) : (
                      <Text span fw={600} size="sm">
                        {col.label}
                      </Text>
                    )}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={visibleColumns.length + 1}>
                    <Text c="dimmed" ta="center" py="md">
                      {emptyLabel}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {shown.map((row) => {
                const key = rowKey(row);
                const open = expanded.has(key);
                return (
                  <React.Fragment key={key}>
                    <Table.Tr
                      className="ga-table-row"
                      data-open={open || undefined}
                      style={{ cursor: 'pointer' }}
                      onClick={(e) => {
                        if (!isInteractive(e.target)) toggleRow(key);
                      }}
                    >
                      <Table.Td>
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-expanded={open}
                          aria-label={open ? 'Hide details' : 'Show details'}
                          onClick={() => toggleRow(key)}
                        >
                          <Icon
                            icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                            width={16}
                          />
                        </ActionIcon>
                      </Table.Td>
                      {visibleColumns.map((col) => (
                        <Table.Td key={col.key} data-col={col.key}>
                          {col.render(row)}
                        </Table.Td>
                      ))}
                    </Table.Tr>
                    {open && (
                      <Table.Tr className="ga-table-detail">
                        <Table.Td colSpan={visibleColumns.length + 1}>{renderDetail(row)}</Table.Td>
                      </Table.Tr>
                    )}
                  </React.Fragment>
                );
              })}
            </Table.Tbody>
          </Table>
        </div>
      </div>
    </div>
  );
}

export default AdminTable;
