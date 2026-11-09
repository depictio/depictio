import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  FileButton,
  Group,
  Loader,
  LoadingOverlay,
  Stack,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { CellClassParams, ColDef, GridApi, ValueSetterParams } from 'ag-grid-community';
import {
  fetchTableForEdit,
  mergeTableFile,
  patchTableCells,
  TableEditError,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  TableCellEdit,
  TableEditData,
  TableMergeMode,
  TableMergeReport,
} from 'depictio-react-core';

import { useGlassPages } from '../../chrome/variants/glass/pages';
import TableMergePanel from './TableMergePanel';
import './TableEditor.css';

/** One grid row: `idx` is the row's position in the table version that was read,
 *  which is how the server addresses it whatever the grid's sort or filter. */
interface GridRow {
  idx: number;
  values: Record<string, unknown>;
}

interface PendingCell {
  idx: number;
  column: string;
  value: string | null;
}

type SaveProblem =
  | { kind: 'stale'; message: string }
  | { kind: 'invalid'; message: string }
  | { kind: 'other'; message: string };

const cellKey = (idx: number, column: string) => `${idx}\u0001${column}`;
const asText = (v: unknown) => (v == null ? '' : String(v));

const MERGE_ACCEPT = '.csv,.tsv,.tab,.parquet,.pq,.xlsx,.xls';

/** Only a drag carrying files is ours: not a selection of text, not a column. */
const carriesFiles = (event: React.DragEvent) =>
  Array.from(event.dataTransfer.types).includes('Files');

/**
 * Spreadsheet-style editing of a table a user added (a sample sheet, say).
 *
 * Loads the whole table with the Delta version it was read at, collects cell
 * edits locally (highlighted until saved), and sends them in one PATCH. The
 * server casts each value to its column's type: a value that does not fit is
 * marked on its cell and nothing is saved; a table someone else changed in the
 * meantime answers 409 and offers a reload.
 *
 * A file dropped on it (or chosen with "Update from file") previews in the grid:
 * replace the table, fill its empty cells, or add columns. Nothing is written
 * before Apply.
 */
const TableEditor: React.FC<{
  dcId: string;
  /** Called after a successful save, so the read-only views can refresh. */
  onSaved: () => void;
  /** Leave for the read-only view, which holds the past versions. */
  onShowReadOnly: () => void;
}> = ({ dcId, onSaved, onShowReadOnly }) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  const { colorScheme } = useMantineColorScheme();

  const [data, setData] = useState<TableEditData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<SaveProblem | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  // Bumped by Discard to rebuild the rows from the table as it was read.
  const [resetCount, setResetCount] = useState(0);
  // A dropped file being previewed: the grid shows `report`, read-only, until Apply.
  const [merge, setMerge] = useState<{ file: File; report: TableMergeReport } | null>(null);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [dragging, setDragging] = useState(false);

  // Read by the grid's callbacks, which must not capture a stale render.
  const dataRef = useRef<TableEditData | null>(null);
  const pending = useRef(new Map<string, PendingCell>());
  const cellErrors = useRef(new Map<string, string>());
  const gridApi = useRef<GridApi | null>(null);
  const resetFileInput = useRef<() => void>(null);

  const showReadOnlyRef = useRef(onShowReadOnly);
  showReadOnlyRef.current = onShowReadOnly;

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const table = await fetchTableForEdit(dcId);
      pending.current.clear();
      cellErrors.current.clear();
      dataRef.current = table;
      setPendingCount(0);
      setProblem(null);
      setMerge(null);
      setData(table);
    } catch (err) {
      // Too big for the grid, not broken: the read-only view pages through it.
      if (err instanceof TableEditError && err.code === 'table_too_large') {
        notifications.show({ color: 'yellow', message: err.message });
        showReadOnlyRef.current();
        return;
      }
      setLoadError((err as Error).message || 'Failed to load the table.');
    } finally {
      setLoading(false);
    }
  }, [dcId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Unsaved edits are lost on a reload or a tab close.
  useEffect(() => {
    if (pendingCount === 0) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [pendingCount]);

  const shownRows = merge ? merge.report.rows : data?.rows;
  const rows = useMemo<GridRow[]>(
    () => (shownRows ?? []).map((values, idx) => ({ idx, values: { ...values } })),
    // `resetCount` rebuilds the copies the grid mutated.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shownRows, resetCount],
  );

  const mergedCells = useMemo(
    () => new Set((merge?.report.changed ?? []).map((c) => cellKey(c.row, c.column))),
    [merge],
  );

  const recordEdit = useCallback((idx: number, column: string, typed: unknown) => {
    const table = dataRef.current;
    if (!table) return;
    const key = cellKey(idx, column);
    cellErrors.current.delete(key);
    if (asText(typed) === asText(table.rows[idx]?.[column])) {
      pending.current.delete(key);
    } else {
      pending.current.set(key, { idx, column, value: typed == null ? null : String(typed) });
    }
    setPendingCount(pending.current.size);
  }, []);

  const colDefs = useMemo<ColDef<GridRow>[]>(() => {
    if (merge) {
      return merge.report.columns.map((col) => ({
        colId: col.name,
        headerName: col.is_new ? `${col.name} (new)` : col.name,
        headerClass: col.is_new ? 'dc-col-new' : undefined,
        editable: false,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (p) => (p.data ? p.data.values[col.name] : undefined),
        valueFormatter: (p) => asText(p.value),
        cellClassRules: {
          'dc-cell-merged': (p: CellClassParams<GridRow>) =>
            !!p.data && mergedCells.has(cellKey(p.data.idx, col.name)),
          'dc-cell-new': () => col.is_new,
        },
      }));
    }
    return (data?.columns ?? []).map((col) => ({
        // `field` would split a dotted column name into a path.
        colId: col.name,
        headerName: col.name,
        headerTooltip: col.editable
          ? `${col.kind} column`
          : `${col.dtype} column: shown here, not editable`,
        editable: col.editable,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (p) => (p.data ? p.data.values[col.name] : undefined),
        valueSetter: (p: ValueSetterParams<GridRow>) => {
          recordEdit(p.data.idx, col.name, p.newValue);
          p.data.values[col.name] = p.newValue === '' ? null : p.newValue;
          return true;
        },
        valueFormatter: (p) => asText(p.value),
        cellClassRules: {
          'dc-cell-edited': (p: CellClassParams<GridRow>) =>
            !!p.data && pending.current.has(cellKey(p.data.idx, col.name)),
          'dc-cell-error': (p: CellClassParams<GridRow>) =>
            !!p.data && cellErrors.current.has(cellKey(p.data.idx, col.name)),
        },
        tooltipValueGetter: (p) =>
        p.data ? cellErrors.current.get(cellKey(p.data.idx, col.name)) : undefined,
    }));
  }, [data, merge, mergedCells, recordEdit]);

  const refreshCells = () => gridApi.current?.refreshCells({ force: true });

  const discard = () => {
    pending.current.clear();
    cellErrors.current.clear();
    setPendingCount(0);
    setProblem(null);
    setResetCount((n) => n + 1);
  };

  const previewFile = async (
    file: File,
    mode: TableMergeMode | 'auto' = 'auto',
    key: string | null = null,
  ) => {
    const table = dataRef.current;
    if (!table) return;
    if (pending.current.size > 0) {
      notifications.show({
        color: 'yellow',
        message: 'Save or discard your changes before updating the table from a file.',
      });
      return;
    }
    setMergeBusy(true);
    setProblem(null);
    try {
      const report = await mergeTableFile(dcId, file, {
        mode,
        key,
        baseVersion: table.delta_version,
      });
      setMerge({ file, report });
    } catch (err) {
      const stale = err instanceof TableEditError && err.code === 'stale_version';
      setProblem({
        kind: stale ? 'stale' : 'other',
        message: (err as Error).message || 'Failed to read the file.',
      });
    } finally {
      setMergeBusy(false);
      resetFileInput.current?.();
    }
  };

  const applyMerge = async () => {
    if (!merge) return;
    setApplying(true);
    setProblem(null);
    try {
      const { report, file } = merge;
      await mergeTableFile(dcId, file, {
        mode: report.mode,
        key: report.key,
        baseVersion: report.delta_version,
        dryRun: false,
      });
      notifications.show({ color: 'green', message: `Table updated from ${file.name}.` });
      await load();
      onSaved();
    } catch (err) {
      const stale = err instanceof TableEditError && err.code === 'stale_version';
      setProblem({
        kind: stale ? 'stale' : 'other',
        message: (err as Error).message || 'Failed to update the table.',
      });
    } finally {
      setApplying(false);
    }
  };

  const onDragOver = (event: React.DragEvent) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    setDragging(true);
  };

  const onDragLeave = (event: React.DragEvent) => {
    // Moving between children of the editor also fires this.
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
  };

  const onDrop = (event: React.DragEvent) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length !== 1) {
      notifications.show({ color: 'yellow', message: 'Drop one file at a time on a table.' });
      return;
    }
    void previewFile(files[0]);
  };

  const showReadOnly = () => {
    if (
      pending.current.size > 0 &&
      !window.confirm(`Discard ${pending.current.size} unsaved change(s)?`)
    ) {
      return;
    }
    onShowReadOnly();
  };

  const save = async () => {
    const table = dataRef.current;
    if (!table || pending.current.size === 0) return;
    setSaving(true);
    setProblem(null);
    cellErrors.current.clear();
    const edits: TableCellEdit[] = [...pending.current.values()].map((cell) => ({
      row: cell.idx,
      column: cell.column,
      value: cell.value,
    }));
    try {
      const result = await patchTableCells(dcId, table.delta_version, edits);
      notifications.show({
        color: 'green',
        message:
          result.changed_cells === 0
            ? 'Nothing changed.'
            : `Saved ${result.changed_cells} cell${result.changed_cells === 1 ? '' : 's'}.`,
      });
      await load();
      onSaved();
    } catch (err) {
      if (err instanceof TableEditError && err.code === 'stale_version') {
        setProblem({ kind: 'stale', message: err.message });
      } else if (err instanceof TableEditError && err.code === 'invalid_cells') {
        for (const bad of err.cellErrors) {
          cellErrors.current.set(cellKey(bad.row, bad.column), bad.message);
        }
        setProblem({ kind: 'invalid', message: err.message });
        refreshCells();
        const first = err.cellErrors[0];
        const node = first ? gridApi.current?.getRowNode(String(first.row)) : null;
        if (node) gridApi.current?.ensureNodeVisible(node, 'middle');
      } else {
        setProblem({ kind: 'other', message: (err as Error).message || 'Failed to save.' });
      }
    } finally {
      setSaving(false);
    }
  };

  if (!data) {
    if (loading) {
      return (
        <Center py="md">
          <Loader size="sm" />
        </Center>
      );
    }
    return (
      <Stack gap="xs">
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
          {loadError ?? 'Failed to load the table.'}
        </Alert>
        <Group gap="xs">
          <Button size="xs" variant="light" onClick={() => void load()}>
            Retry
          </Button>
          <Button size="xs" variant="subtle" onClick={onShowReadOnly}>
            Read-only view
          </Button>
        </Group>
      </Stack>
    );
  }

  const stale = problem?.kind === 'stale';

  return (
    <Stack
      gap="xs"
      className="dc-table-editor"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      data-testid="table-drop-zone"
    >
      {dragging && (
        <Box className="dc-table-drop-overlay" data-testid="table-drop-overlay">
          <Stack gap={4} align="center">
            <Icon icon="mdi:file-table-outline" width={32} />
            <Text fw={600}>Drop to update this table</Text>
            <Text size="sm" c="dimmed">
              Add columns, fill missing values or replace it. You will see the result first.
            </Text>
          </Stack>
        </Box>
      )}

      {merge ? (
        <TableMergePanel
          report={merge.report}
          fileName={merge.file.name}
          busy={mergeBusy}
          applying={applying}
          onMode={(mode) => void previewFile(merge.file, mode, merge.report.key)}
          onKey={(key) => void previewFile(merge.file, merge.report.mode, key)}
          onApply={() => void applyMerge()}
          onCancel={() => setMerge(null)}
        />
      ) : (
      <Group justify="space-between" gap="sm" wrap="wrap">
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            {data.row_count} rows · {data.columns.length} columns. Click a cell to edit it, or drop a
            file to update the table.
          </Text>
          {pendingCount > 0 ? (
            <Badge color="yellow" variant="light">
              {pendingCount} unsaved change{pendingCount === 1 ? '' : 's'}
            </Badge>
          ) : (
            <Badge color="gray" variant="light">
              No changes
            </Badge>
          )}
        </Group>
        <Group gap="xs">
          <FileButton
            onChange={(file) => file && void previewFile(file)}
            accept={MERGE_ACCEPT}
            resetRef={resetFileInput}
            inputProps={{ 'data-testid': 'table-merge-input' } as React.ComponentProps<'input'>}
          >
            {(props) => (
              <Button
                {...props}
                size="xs"
                variant="default"
                loading={mergeBusy}
                disabled={saving || pendingCount > 0}
                leftSection={<Icon icon="mdi:file-upload-outline" width={16} />}
              >
                Update from file
              </Button>
            )}
          </FileButton>
          <Button
            size="xs"
            variant="default"
            onClick={discard}
            disabled={pendingCount === 0 || saving}
          >
            Discard
          </Button>
          <Button
            size="xs"
            color={glass ? undefined : accent.secondary}
            onClick={() => void save()}
            loading={saving}
            disabled={pendingCount === 0 || stale}
            leftSection={<Icon icon="mdi:content-save-outline" width={16} />}
          >
            Save changes
          </Button>
          <Button size="xs" variant="subtle" onClick={showReadOnly} disabled={saving}>
            Past versions
          </Button>
        </Group>
      </Group>
      )}

      {problem && (
        <Alert
          color={problem.kind === 'stale' ? 'orange' : 'red'}
          variant="light"
          icon={
            <Icon
              icon={problem.kind === 'stale' ? 'mdi:account-sync-outline' : 'mdi:alert-circle-outline'}
              width={16}
            />
          }
          py={6}
        >
          <Group justify="space-between" gap="sm" wrap="wrap">
            <Text size="sm">
              {problem.message}
              {problem.kind === 'invalid' && ' Fix the highlighted cells and save again.'}
            </Text>
            {problem.kind === 'stale' && (
              <Button size="xs" color="orange" variant="light" onClick={() => void load()}>
                Reload table (discard my changes)
              </Button>
            )}
          </Group>
        </Alert>
      )}

      <Box
        className={colorScheme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={{ height: 480, width: '100%', position: 'relative' }}
      >
        <LoadingOverlay visible={loading || saving || mergeBusy || applying} zIndex={1} />
        <AgGridReact<GridRow>
          rowData={rows}
          columnDefs={colDefs}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          getRowId={(p) => String(p.data.idx)}
          onGridReady={(e) => {
            gridApi.current = e.api;
          }}
          singleClickEdit
          stopEditingWhenCellsLoseFocus
          tooltipShowDelay={200}
          suppressCellFocus={false}
        />
      </Box>
    </Stack>
  );
};

export default TableEditor;
