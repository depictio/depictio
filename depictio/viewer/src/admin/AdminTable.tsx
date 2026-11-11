import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActionIcon, Button, Checkbox, Group, Table, Text, TextInput, Tooltip } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import SortHeader, { type SortDir } from '../components/SortHeader';
import TableDisplayMenu, { type TableDensity } from '../components/TableDisplayMenu';
import { type ColumnDef, useTableColumns } from '../lib/useTableColumns';
import { useGlassPages } from '../chrome/variants/glass/pages';
import './adminTableDensity.css';

/** One density for all admin tables, shared across Projects, Dashboards and Users. */
const DENSITY_STORAGE_KEY = 'depictio.admin.tableDensity.v1';
const DEFAULT_DENSITY: TableDensity = 'cozy';

function loadDensity(): TableDensity {
  try {
    return localStorage.getItem(DENSITY_STORAGE_KEY) === 'compact' ? 'compact' : DEFAULT_DENSITY;
  } catch {
    return DEFAULT_DENSITY;
  }
}

/** Compact cells are clipped to one line: hovering a clipped one shows its full text. */
function titleIfClipped(e: React.MouseEvent<HTMLElement>) {
  const el = e.currentTarget;
  if (el.scrollWidth > el.clientWidth + 1) {
    const text = (el.innerText || el.textContent || '').replace(/\s*\n+\s*/g, ', ').trim();
    if (text) el.title = text;
  } else if (el.title) {
    el.removeAttribute('title');
  }
}

/** One column of an admin table: the picker metadata plus how to sort and draw it. */
export interface AdminTableColumn<T, K extends string> extends ColumnDef<K> {
  /** Value the column sorts by. Dates as epoch ms; null/undefined sort last. Omit for an unsortable column. */
  sortValue?: (row: T) => string | number | null | undefined;
  render: (row: T) => React.ReactNode;
}

/** Optional multi-select with a bulk-action bar. */
export interface AdminTableSelection<T> {
  getId: (row: T) => string;
  /** Rows for which this returns false get a disabled checkbox. Default: all selectable. */
  isSelectable?: (row: T) => boolean;
  /** Tooltip on the disabled checkbox of a row that is not selectable. */
  disabledReason?: (row: T) => string | undefined;
  /** Bulk actions, drawn in the bar that shows while at least one row is selected. */
  actions: (selected: T[], clear: () => void) => React.ReactNode;
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
  /** Per-row actions (e.g. an actions menu), drawn in a narrow last column that
   *  is outside the column picker. Clicks in it do not toggle the detail row. */
  rowActions?: (row: T) => React.ReactNode;
  /** Multi-select column + bulk-action bar. Omit for a plain table. */
  selection?: AdminTableSelection<T>;
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
  rowActions,
  selection,
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

  const [density, setDensityState] = useState<TableDensity>(loadDensity);
  const setDensity = useCallback((d: TableDensity) => {
    setDensityState(d);
    try {
      localStorage.setItem(DENSITY_STORAGE_KEY, d);
    } catch {
      // Storage blocked: the choice simply does not persist.
    }
  }, []);
  const compact = density === 'compact';

  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 200);
  const [sortKey, setSortKey] = useState<K>(defaultSort.key);
  const [sortDir, setSortDir] = useState<SortDir>(defaultSort.dir ?? 'asc');
  // Detail toggle column, the visible columns, and the optional actions column.
  const totalColumns = visibleColumns.length + (rowActions ? 2 : 1) + (selection ? 1 : 0);
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

  // Selected ids. Pruned below so it only ever holds ids of rows currently
  // shown (a delete, a reload or a new search drops the ones that left).
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const selectableRows = useMemo(
    () =>
      selection ? shown.filter((r) => (selection.isSelectable ? selection.isSelectable(r) : true)) : [],
    [shown, selection],
  );
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const ids = new Set(selectableRows.map((r) => selection!.getId(r)));
      const next = new Set<string>();
      for (const id of prev) if (ids.has(id)) next.add(id);
      return next.size === prev.size ? prev : next;
    });
  }, [selectableRows, selection]);

  const selectedRows = useMemo(
    () => (selection ? selectableRows.filter((r) => selected.has(selection.getId(r))) : []),
    [selectableRows, selected, selection],
  );
  const allSelected = selectableRows.length > 0 && selectedRows.length === selectableRows.length;
  const someSelected = selectedRows.length > 0 && !allSelected;
  const clearSelection = useCallback(() => setSelected(new Set()), []);
  const toggleAll = useCallback(() => {
    if (!selection) return;
    setSelected(
      allSelected ? new Set() : new Set(selectableRows.map((r) => selection.getId(r))),
    );
  }, [selection, allSelected, selectableRows]);
  const toggleOne = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="ga-table" data-density={density}>
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
        <TableDisplayMenu
          section="admin"
          columns={columnState}
          density={density}
          defaultDensity={DEFAULT_DENSITY}
          onDensityChange={setDensity}
        />
      </Group>
      {selection && selectedRows.length > 0 && (
        <Group
          className="ga-table-bulk"
          p="sm"
          mb="sm"
          gap="md"
          justify="space-between"
          style={{
            border: '1px solid var(--mantine-color-default-border)',
            borderRadius: 8,
            background: 'var(--mantine-color-default-hover)',
          }}
        >
          <Text size="sm" fw={500}>
            {selectedRows.length} selected
          </Text>
          <Group gap="xs">
            {selection.actions(selectedRows, clearSelection)}
            <Button variant="subtle" size="xs" onClick={clearSelection}>
              Clear
            </Button>
          </Group>
        </Group>
      )}
      <div
        className="ga-table-frame"
        style={
          glass
            ? undefined
            : { border: '1px solid var(--mantine-color-default-border)', borderRadius: 8 }
        }
      >
        <div style={{ overflowX: 'auto' }}>
          <Table verticalSpacing={compact ? 4 : 'sm'} highlightOnHover miw={Math.max(600, visibleColumns.length * 150)}>
            <Table.Thead>
              <Table.Tr>
                {selection && (
                  <Table.Th style={{ width: 36 }}>
                    <Checkbox
                      checked={allSelected}
                      indeterminate={someSelected}
                      disabled={selectableRows.length === 0}
                      onChange={toggleAll}
                      aria-label="Select all"
                    />
                  </Table.Th>
                )}
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
                {rowActions && <Table.Th style={{ width: 44 }} aria-label="Actions" />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={totalColumns}>
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
                      {selection && (
                        <Table.Td className="ga-table-fixed" onClick={(e) => e.stopPropagation()}>
                          {(() => {
                            const selectable = selection.isSelectable
                              ? selection.isSelectable(row)
                              : true;
                            const box = (
                              <Checkbox
                                checked={selectable && selected.has(selection.getId(row))}
                                disabled={!selectable}
                                onChange={() => toggleOne(selection.getId(row))}
                                aria-label={`Select ${key}`}
                              />
                            );
                            const reason = selectable ? undefined : selection.disabledReason?.(row);
                            return reason ? (
                              <Tooltip label={reason} withinPortal>
                                <span style={{ display: 'inline-flex' }}>{box}</span>
                              </Tooltip>
                            ) : (
                              box
                            );
                          })()}
                        </Table.Td>
                      )}
                      <Table.Td className="ga-table-fixed">
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
                      {visibleColumns.map((col, i) => (
                        <Table.Td
                          key={col.key}
                          data-col={col.key}
                          data-primary={i === 0 || undefined}
                          onMouseEnter={compact ? titleIfClipped : undefined}
                        >
                          {col.render(row)}
                        </Table.Td>
                      ))}
                      {rowActions && (
                        <Table.Td onClick={(e) => e.stopPropagation()} style={{ textAlign: 'right', width: 44, whiteSpace: 'nowrap' }}>
                          {rowActions(row)}
                        </Table.Td>
                      )}
                    </Table.Tr>
                    {open && (
                      <Table.Tr className="ga-table-detail">
                        <Table.Td colSpan={totalColumns}>{renderDetail(row)}</Table.Td>
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
