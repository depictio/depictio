import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Box,
  Button,
  FileButton,
  Group,
  Loader,
  LoadingOverlay,
  Modal,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
  useComputedColorScheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef, GridApi, ValueSetterParams } from 'ag-grid-community';
import {
  annotationColumnBudget,
  asKey,
  emptyAnnotations,
  fetchDataCollectionPreview,
  fetchDataVersionStatus,
  fetchTableEditStatus,
  fetchTableForEdit,
  matchDroppedTable,
  MAX_ANNOTATION_COLUMNS,
  MAX_ANNOTATION_ROWS,
  MAX_DROP_BYTES,
  MAX_LABEL_LENGTH,
  mergeTableFile,
  newAnnotationId,
  parseDroppedTable,
  parsePastedBlock,
  patchTableCells,
  planAnnotationMerge,
  setLabel,
  suggestedMergeMode,
  TableEditError,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  AnnotationMergeMode,
  DashboardAnnotations,
  DataPinFields,
  DataVersionCollectionStatus,
  DropMatch,
  SelectionGroup,
  TableEditStatus,
  TableMergeMode,
  TableMergeReport,
} from 'depictio-react-core';

import TableMergePanel from '../../projects/detail/TableMergePanel';
// The drop overlay is the table editor's, so both drops look the same.
import '../../projects/detail/TableEditor.css';
import LabelColumnHeader, { type LabelColumnActions } from './LabelColumnHeader';
import './AnnotationPanel.css';
import type { DashboardAnnotationsState } from './useDashboardAnnotations';

/** One grid row: the key, its row in the table when it can be edited, the
 *  table's columns and one field per label column. */
type GridRow = Record<string, unknown> & { __key: string; __row: number | null };

const ANN_PREFIX = 'ann:';
const KEY_FIELD = '__key';
const ADD_FIELD = '__add';

interface TableRead {
  dcId: string;
  columns: string[];
  rows: Record<string, unknown>[];
  /** Delta version read; null for the current table read through the preview. */
  version: number | null;
  /** Set when the reader may write to this table: the version the cells were
   *  read at and the columns that can be edited. */
  edit: { deltaVersion: number; editable: Set<string> } | null;
}

type Load =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; table: TableRead }
  | { kind: 'refused'; message: string };

/** Columns whose values are present and distinct on every row. */
function uniqueColumns(read: TableRead): string[] {
  return read.columns.filter((col) => {
    const seen = new Set<string>();
    for (const row of read.rows) {
      const k = asKey(row[col]);
      if (k === null || seen.has(k)) return false;
      seen.add(k);
    }
    return read.rows.length > 0;
  });
}

function tableLabel(entry: DataVersionCollectionStatus, all: DataVersionCollectionStatus[]): string {
  const tag = entry.data_collection_tag || entry.dc_id;
  const clash = all.filter((e) => e.data_collection_tag === entry.data_collection_tag).length > 1;
  return clash && entry.workflow_tag ? `${entry.workflow_tag} / ${tag}` : tag;
}

function csvCell(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

const cellKey = (row: number, column: string) => `${row}\u0000${column}`;

/** The "+" header: adds a label column. */
const AddLabelHeader: React.FC<{ onAdd: () => void; disabled: boolean }> = ({ onAdd, disabled }) => (
  <Tooltip
    withinPortal
    label={disabled ? `At most ${MAX_ANNOTATION_COLUMNS} label columns` : 'Add a label column'}
  >
    <ActionIcon
      size="sm"
      variant="subtle"
      color="gray"
      aria-label="Add a label column"
      data-testid="label-add"
      disabled={disabled}
      onClick={onAdd}
    >
      <Icon icon="mdi:plus" width={16} />
    </ActionIcon>
  </Tooltip>
);

export interface AnnotationPanelProps {
  /** The rendered tab: the data-version status call reads the whole family from it. */
  dashboardId: string;
  /** Data pins of a past-version view, or null on a live view. */
  pins: DataPinFields | null;
  state: DashboardAnnotationsState;
  /** Every group on the dashboard, for the 24-group budget. */
  groups: SelectionGroup[];
  /** A real write landed: re-render the dashboard. */
  onDataWritten: () => void;
}

/**
 * The Labels tab of the Analysis panel: one grid. Label columns hold session
 * labels (each label of the compared one is a group); the table's own columns
 * can be edited in place by whoever may write to the table, saved in one go
 * from the bar under the grid. Every column action is in its header menu.
 */
const AnnotationPanel: React.FC<AnnotationPanelProps> = ({
  dashboardId,
  pins,
  state,
  groups,
  onDataWritten,
}) => {
  const scheme = useComputedColorScheme('light');
  const { annotations, setAnnotations } = state;
  const pinned = pins !== null;

  // ---- Tables the dashboard reads -----------------------------------------
  const [collections, setCollections] = useState<DataVersionCollectionStatus[] | null>(null);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const pinsKey = JSON.stringify(pins ?? {});
  useEffect(() => {
    let cancelled = false;
    setCollections(null);
    setCollectionsError(null);
    fetchDataVersionStatus(dashboardId, pins ?? {})
      .then((res) => {
        if (!cancelled) setCollections(res.collections);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCollectionsError(err instanceof Error ? err.message : 'The tables could not be listed.');
        }
      });
    return () => {
      cancelled = true;
    };
    // pinsKey is the stable identity of pins.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, pinsKey]);
  const tables = useMemo(
    () => (collections ?? []).filter((c) => (c.dc_type || '').toLowerCase() === 'table'),
    [collections],
  );

  // ---- Who may write, per table -------------------------------------------
  const statusCache = useRef(new Map<string, TableEditStatus | null>());
  const editStatusOf = useCallback(async (dcId: string): Promise<TableEditStatus | null> => {
    if (statusCache.current.has(dcId)) return statusCache.current.get(dcId) ?? null;
    const s = await fetchTableEditStatus(dcId).catch(() => null);
    statusCache.current.set(dcId, s);
    return s;
  }, []);

  // ---- Reading one table ----------------------------------------------------
  const cache = useRef(new Map<string, Load>());
  const readTable = useCallback(
    async (dcId: string, force = false): Promise<Load> => {
      const cached = cache.current.get(dcId);
      if (cached && !force) return cached;
      const entry = (collections ?? []).find((c) => c.dc_id === dcId);
      let version: number | null = null;
      if (pinned) {
        // Fail closed: a past view never shows today's rows as if they were then.
        if (!entry || entry.status !== 'pinned' || typeof entry.delta_version !== 'number') {
          const why = entry?.reason ? ` (${entry.reason.replace(/_/g, ' ')})` : '';
          const load: Load = {
            kind: 'refused',
            message: `This view shows a past version, and the version of this table it read cannot be resolved${why}. The grid stays closed rather than show the table as it is now.`,
          };
          cache.current.set(dcId, load);
          return load;
        }
        version = entry.delta_version;
      } else {
        // Whoever may write reads the table as the editor does: whole, with
        // the version its cells will be saved against.
        const status = await editStatusOf(dcId);
        if (status?.can_edit) {
          try {
            const data = await fetchTableForEdit(dcId);
            if (data.rows.length <= MAX_ANNOTATION_ROWS) {
              const load: Load = {
                kind: 'ready',
                table: {
                  dcId,
                  columns: data.columns.map((c) => c.name),
                  rows: data.rows,
                  version: null,
                  edit: {
                    deltaVersion: data.delta_version,
                    editable: new Set(data.columns.filter((c) => c.editable).map((c) => c.name)),
                  },
                },
              };
              cache.current.set(dcId, load);
              return load;
            }
          } catch {
            // Falls back to the read-only preview below.
          }
        }
      }
      try {
        const res = await fetchDataCollectionPreview(dcId, MAX_ANNOTATION_ROWS, [], version);
        const load: Load =
          res.total_rows > MAX_ANNOTATION_ROWS
            ? {
                kind: 'refused',
                message: `This table has ${res.total_rows.toLocaleString()} rows. Labels work on tables of up to ${MAX_ANNOTATION_ROWS.toLocaleString()} rows, so that the list of samples is never cut short; pick a smaller table.`,
              }
            : {
                kind: 'ready',
                table: { dcId, columns: res.columns, rows: res.rows, version: res.version ?? null, edit: null },
              };
        cache.current.set(dcId, load);
        return load;
      } catch (err) {
        return {
          kind: 'refused',
          message: err instanceof Error ? err.message : 'The table could not be read.',
        };
      }
    },
    [collections, pinned, editStatusOf],
  );

  // ---- Which table and key -------------------------------------------------
  const [choice, setChoice] = useState<{ dcId: string; keyColumn: string } | null>(null);
  const [load, setLoad] = useState<Load>({ kind: 'idle' });
  const [changing, setChanging] = useState(false);

  // The stored annotations decide; otherwise the first table with a unique column.
  useEffect(() => {
    if (!collections || choice) return;
    if (annotations) {
      setChoice({ dcId: annotations.dcId, keyColumn: annotations.keyColumn });
      return;
    }
    let cancelled = false;
    (async () => {
      for (const t of tables) {
        const l = await readTable(t.dc_id);
        if (cancelled) return;
        if (l.kind === 'ready') {
          const unique = uniqueColumns(l.table);
          if (unique.length > 0) {
            setChoice({ dcId: t.dc_id, keyColumn: unique[0] });
            return;
          }
        }
      }
      if (!cancelled && tables[0]) setChoice({ dcId: tables[0].dc_id, keyColumn: '' });
    })();
    return () => {
      cancelled = true;
    };
  }, [collections, tables, annotations, choice, readTable]);

  useEffect(() => {
    if (!choice) return;
    let cancelled = false;
    setLoad({ kind: 'loading' });
    void readTable(choice.dcId).then((l) => {
      if (!cancelled) setLoad(l);
    });
    return () => {
      cancelled = true;
    };
  }, [choice, readTable]);

  const table = load.kind === 'ready' ? load.table : null;
  const keyColumn = choice?.keyColumn ?? '';
  const keyOptions = useMemo(() => (table ? uniqueColumns(table) : []), [table]);
  const currentLabel = (() => {
    const entry = tables.find((t) => t.dc_id === choice?.dcId);
    return entry ? tableLabel(entry, tables) : (choice?.dcId ?? '');
  })();

  // Labels of another table or key would be lost by a switch: ask first.
  const [pendingChoice, setPendingChoice] = useState<{ dcId: string; keyColumn: string } | null>(null);
  const requestChoice = (next: { dcId: string; keyColumn: string }) => {
    const bound = annotations && annotations.columns.length > 0;
    if (bound && (annotations.dcId !== next.dcId || annotations.keyColumn !== next.keyColumn)) {
      setPendingChoice(next);
    } else {
      setChoice(next);
    }
  };
  const confirmSwitch = () => {
    if (!pendingChoice) return;
    setAnnotations(null);
    setChoice(pendingChoice);
    setPendingChoice(null);
  };
  const onTableChange = async (dcId: string | null) => {
    if (!dcId) return;
    const l = await readTable(dcId);
    const unique = l.kind === 'ready' ? uniqueColumns(l.table) : [];
    requestChoice({ dcId, keyColumn: unique[0] ?? '' });
  };

  // The annotations bound to what is on screen (created on first edit).
  const bound: DashboardAnnotations | null =
    choice && keyColumn
      ? annotations && annotations.dcId === choice.dcId && annotations.keyColumn === keyColumn
        ? annotations
        : null
      : null;
  const ensureBound = (): DashboardAnnotations | null =>
    bound ?? (choice && keyColumn ? emptyAnnotations(choice.dcId, keyColumn) : null);

  // ---- Writing to the table: who, and unsaved cells -------------------------
  const writeBlocked: string | null = pinned
    ? 'This view shows a past version; a change to the table would not appear in it.'
    : !table
      ? 'The table is not loaded.'
      : !table.edit
        ? statusCache.current.get(table.dcId)?.reason || 'You cannot change this table.'
        : null;
  const [cellEdits, setCellEdits] = useState<
    Map<string, { row: number; column: string; value: string | null }>
  >(new Map());
  useEffect(() => setCellEdits(new Map()), [table]);

  // ---- Grid rows ----------------------------------------------------------
  const { rows, contextColumns, tableKeys } = useMemo(() => {
    if (!table || !keyColumn) {
      return { rows: [] as GridRow[], contextColumns: [] as string[], tableKeys: new Set<string>() };
    }
    const first = new Map<string, { row: Record<string, unknown>; index: number }>();
    const perKey = new Map<string, Map<string, Set<string>>>();
    table.rows.forEach((row, index) => {
      const key = asKey(row[keyColumn]);
      if (key === null) return;
      if (!first.has(key)) first.set(key, { row, index });
      let cols = perKey.get(key);
      if (!cols) perKey.set(key, (cols = new Map()));
      for (const c of table.columns) {
        let vals = cols.get(c);
        if (!vals) cols.set(c, (vals = new Set()));
        vals.add(JSON.stringify(row[c] ?? null));
      }
    });
    // With several rows per key, only columns holding one value per key can stand for the key.
    const context = table.columns.filter(
      (c) => c !== keyColumn && [...perKey.values()].every((cols) => (cols.get(c)?.size ?? 0) <= 1),
    );
    const out: GridRow[] = [];
    for (const [key, { row, index }] of first) {
      const r: GridRow = { __key: key, __row: table.edit ? index : null };
      for (const c of context) {
        const edit = table.edit ? cellEdits.get(cellKey(index, c)) : undefined;
        r[c] = edit ? edit.value : row[c];
      }
      for (const col of bound?.columns ?? []) r[ANN_PREFIX + col.id] = col.values[key] ?? '';
      out.push(r);
    }
    return { rows: out, contextColumns: context, tableKeys: new Set(first.keys()) };
  }, [table, keyColumn, bound, cellEdits]);

  const missingKeys = useMemo(() => {
    if (!bound || tableKeys.size === 0) return 0;
    const all = new Set<string>();
    for (const c of bound.columns) for (const k of Object.keys(c.values)) all.add(k);
    return [...all].filter((k) => !tableKeys.has(k)).length;
  }, [bound, tableKeys]);

  // ---- Label edits --------------------------------------------------------
  const commit = useCallback((next: DashboardAnnotations) => setAnnotations(next), [setAnnotations]);
  const gridApi = useRef<GridApi<GridRow> | null>(null);

  const setLabelCell = useCallback(
    (params: ValueSetterParams<GridRow>) => {
      const field = params.colDef.field ?? '';
      const base = ensureBound();
      if (!base || !field.startsWith(ANN_PREFIX)) return false;
      const label = String(params.newValue ?? '').slice(0, MAX_LABEL_LENGTH);
      commit(setLabel(base, field.slice(ANN_PREFIX.length), params.data.__key, label));
      // The row is rebuilt from the annotations, which are the source of truth.
      return false;
    },
    // ensureBound reads bound and choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bound, choice, keyColumn, commit],
  );

  const setTableCell = useCallback(
    (params: ValueSetterParams<GridRow>) => {
      const column = params.colDef.field ?? '';
      const index = params.data.__row;
      if (!table?.edit || index === null) return false;
      const original = table.rows[index]?.[column];
      const raw = params.newValue;
      const value = raw === null || raw === undefined || String(raw).trim() === '' ? null : String(raw);
      setCellEdits((prev) => {
        const next = new Map(prev);
        const same = (original ?? null) === null ? value === null : String(original) === value;
        if (same) next.delete(cellKey(index, column));
        else next.set(cellKey(index, column), { row: index, column, value });
        return next;
      });
      return false;
    },
    [table],
  );

  // ---- Naming a column (add / rename) ---------------------------------------
  const [naming, setNaming] = useState<{ id: string | null; value: string; error: string | null } | null>(
    null,
  );
  const submitName = () => {
    if (!naming) return;
    const base = ensureBound();
    const name = naming.value.trim();
    if (!base || !name) return;
    const others = base.columns.filter((c) => c.id !== naming.id);
    if (name.length > MAX_LABEL_LENGTH) {
      setNaming({ ...naming, error: `At most ${MAX_LABEL_LENGTH} characters.` });
      return;
    }
    if (others.some((c) => c.name === name) || name === keyColumn || contextColumns.includes(name)) {
      setNaming({ ...naming, error: `"${name}" is already a column here.` });
      return;
    }
    if (naming.id) {
      commit({ ...base, columns: base.columns.map((c) => (c.id === naming.id ? { ...c, name } : c)) });
    } else {
      commit({ ...base, columns: [...base.columns, { id: newAnnotationId(), name, values: {} }] });
    }
    setNaming(null);
  };

  const keepOnAccount = (id: string) => {
    if (!bound) return;
    commit({
      ...bound,
      columns: bound.columns.map((c) => {
        if (c.id !== id) return c;
        const { local: _local, ...shared } = c;
        return shared;
      }),
    });
  };
  const removeLabelColumn = (id: string) => {
    if (!bound) return;
    commit({
      ...bound,
      columns: bound.columns.filter((c) => c.id !== id),
      activeColumnId: bound.activeColumnId === id ? null : bound.activeColumnId,
    });
  };
  const toggleCompare = (id: string) => {
    if (!bound) return;
    commit({ ...bound, activeColumnId: bound.activeColumnId === id ? null : id });
  };

  // ---- Paste ------------------------------------------------------------------
  // AG Grid Community has no clipboard, so a block pasted on a focused label
  // cell is written from that cell down and to the right, across label columns.
  const onPaste = (e: React.ClipboardEvent) => {
    const api = gridApi.current;
    const focused = api?.getFocusedCell();
    const base = ensureBound();
    if (!api || !focused || !base) return;
    const startCol = focused.column.getColId();
    if (!startCol.startsWith(ANN_PREFIX)) return;
    const text = e.clipboardData.getData('text/plain');
    // A single value typed into an open editor is the editor's business.
    const editing = api.getEditingCells().length > 0;
    if (editing && !/[\t\n]/.test(text)) return;
    e.preventDefault();
    if (editing) api.stopEditing(true);
    const block = parsePastedBlock(text);
    const labelCols = api
      .getAllDisplayedColumns()
      .map((c) => c.getColId())
      .filter((id) => id.startsWith(ANN_PREFIX));
    const firstCol = labelCols.indexOf(startCol);
    let next = base;
    let skipped = 0;
    block.forEach((cells, i) => {
      const row = api.getDisplayedRowAtIndex(focused.rowIndex + i);
      if (!row?.data) {
        skipped += 1;
        return;
      }
      cells.forEach((cell, j) => {
        const colId = labelCols[firstCol + j];
        if (!colId) return;
        next = setLabel(
          next,
          colId.slice(ANN_PREFIX.length),
          row.data!.__key,
          cell.slice(0, MAX_LABEL_LENGTH),
        );
      });
    });
    commit(next);
    if (skipped > 0) {
      notifications.show({
        color: 'orange',
        message: `${skipped} pasted row${skipped === 1 ? '' : 's'} went past the last row and were left out.`,
      });
    }
  };

  // ---- Real writes: cells, a label column, a file -----------------------------
  const reloadTable = async () => {
    if (!choice) return;
    statusCache.current.delete(choice.dcId);
    setLoad(await readTable(choice.dcId, true));
  };
  const afterWrite = async () => {
    await reloadTable();
    onDataWritten();
  };

  const [cellSave, setCellSave] = useState<{ busy: boolean; error: string | null; stale: boolean }>({
    busy: false,
    error: null,
    stale: false,
  });
  const saveCells = async () => {
    if (!table?.edit || cellEdits.size === 0) return;
    setCellSave({ busy: true, error: null, stale: false });
    try {
      await patchTableCells(table.dcId, table.edit.deltaVersion, [...cellEdits.values()]);
      const n = cellEdits.size;
      setCellSave({ busy: false, error: null, stale: false });
      notifications.show({ color: 'teal', message: `${n} change${n === 1 ? '' : 's'} saved to the table.` });
      await afterWrite();
    } catch (err) {
      const stale = err instanceof TableEditError && err.code === 'stale_version';
      const cells =
        err instanceof TableEditError && err.cellErrors.length > 0
          ? ` ${err.cellErrors.map((c) => `${c.column}: ${c.message}`).join('; ')}`
          : '';
      setCellSave({
        busy: false,
        stale,
        error: (err instanceof Error ? err.message : 'The changes could not be saved.') + cells,
      });
    }
  };

  const [saving, setSaving] = useState<{
    columnId: string;
    report: TableMergeReport | null;
    error: string | null;
    stale: boolean;
    busy: boolean;
  } | null>(null);
  const labelsCsv = (columnId: string): File | null => {
    const col = bound?.columns.find((c) => c.id === columnId);
    if (!col) return null;
    const lines = [`${csvCell(keyColumn)},${csvCell(col.name)}`];
    for (const [key, label] of Object.entries(col.values)) {
      if (tableKeys.has(key)) lines.push(`${csvCell(key)},${csvCell(label)}`);
    }
    // Built here from the labels; this is the write the reader asked for.
    return new File([lines.join('\n') + '\n'], `${col.name}.csv`, { type: 'text/csv' });
  };
  const startSave = async (columnId: string) => {
    const file = labelsCsv(columnId);
    if (!file || !choice) return;
    setSaving({ columnId, report: null, error: null, stale: false, busy: true });
    try {
      const report = await mergeTableFile(choice.dcId, file, {
        mode: 'add_columns',
        key: keyColumn,
        dryRun: true,
      });
      setSaving({ columnId, report, error: null, stale: false, busy: false });
    } catch (err) {
      setSaving({
        columnId,
        report: null,
        error: err instanceof Error ? err.message : 'The table could not be checked.',
        stale: false,
        busy: false,
      });
    }
  };
  const applySave = async () => {
    if (!saving?.report || !choice) return;
    const file = labelsCsv(saving.columnId);
    if (!file) return;
    setSaving({ ...saving, busy: true });
    try {
      await mergeTableFile(choice.dcId, file, {
        mode: saving.report.mode,
        key: saving.report.key,
        baseVersion: saving.report.delta_version,
        dryRun: false,
      });
      const name = bound?.columns.find((c) => c.id === saving.columnId)?.name ?? 'The labels';
      removeLabelColumn(saving.columnId);
      setSaving(null);
      notifications.show({ color: 'teal', message: `"${name}" is now a column of the table.` });
      await afterWrite();
    } catch (err) {
      const stale = err instanceof TableEditError && err.code === 'stale_version';
      setSaving({
        ...saving,
        busy: false,
        stale,
        error: err instanceof Error ? err.message : 'The table could not be changed.',
      });
    }
  };

  // ---- Import a file ------------------------------------------------------------
  // Dropped anywhere on the tab or picked. "As labels" (the default) is read
  // here and never sent; "Into the table" is a real write, for whoever may.
  const [dragging, setDragging] = useState(false);
  const [importing, setImporting] = useState<{
    file: File;
    destination: 'labels' | 'table';
    match: DropMatch | { error: string };
    mode: AnnotationMergeMode;
    tableReport: TableMergeReport | null;
    tableBusy: boolean;
    tableApplying: boolean;
    tableError: string | null;
  } | null>(null);
  const [importNote, setImportNote] = useState<{ color: string; text: string } | null>(null);
  const openImport = async (file: File) => {
    const base = ensureBound();
    if (!base) return;
    setImportNote(null);
    if (!/\.(csv|tsv|txt|tab)$/i.test(file.name)) {
      setImportNote({ color: 'red', text: 'Import a CSV or TSV file. Excel and Parquet are not read here.' });
      return;
    }
    if (file.size > MAX_DROP_BYTES) {
      setImportNote({ color: 'red', text: 'The file is over 5 MB.' });
      return;
    }
    const parsed = parseDroppedTable(file.name, await file.text());
    const match = 'error' in parsed ? parsed : matchDroppedTable(parsed, keyColumn, tableKeys);
    setImporting({
      file,
      destination: 'labels',
      match,
      mode: 'error' in match ? 'add_columns' : suggestedMergeMode(base, match),
      tableReport: null,
      tableBusy: false,
      tableApplying: false,
      tableError: null,
    });
  };
  const labelsPlan = useMemo(() => {
    const base = ensureBound();
    return importing && base && !('error' in importing.match)
      ? planAnnotationMerge(base, importing.match, importing.mode)
      : null;
    // ensureBound reads bound and choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [importing, bound, choice, keyColumn]);
  const applyLabelsImport = () => {
    if (!importing || !labelsPlan || labelsPlan.report.reason) return;
    commit(labelsPlan.next);
    setImporting(null);
    setImportNote(
      state.storage === 'account'
        ? {
            color: 'teal',
            text: `${importing.file.name}: ${labelsPlan.report.labels} labels, kept in this browser. "Keep on my account" in a column's menu sends one to your account.`,
          }
        : null,
    );
  };
  const previewTableImport = async (mode: TableMergeMode | 'auto' = 'auto', key: string | null = null) => {
    if (!importing || !choice) return;
    const cur = importing;
    setImporting({ ...cur, destination: 'table', tableBusy: true, tableError: null });
    try {
      const report = await mergeTableFile(choice.dcId, cur.file, { mode, key, dryRun: true });
      setImporting({ ...cur, destination: 'table', tableReport: report, tableBusy: false, tableError: null });
    } catch (err) {
      setImporting({
        ...cur,
        destination: 'table',
        tableBusy: false,
        tableError: err instanceof Error ? err.message : 'The file could not be read against the table.',
      });
    }
  };
  const applyTableImport = async () => {
    if (!importing?.tableReport || !choice) return;
    const cur = importing;
    const report = importing.tableReport;
    setImporting({ ...cur, tableApplying: true });
    try {
      await mergeTableFile(choice.dcId, cur.file, {
        mode: report.mode,
        key: report.key,
        baseVersion: report.delta_version,
        dryRun: false,
      });
      setImporting(null);
      notifications.show({ color: 'teal', message: `${cur.file.name} applied to the table.` });
      await afterWrite();
    } catch (err) {
      setImporting({
        ...cur,
        tableApplying: false,
        tableError: err instanceof Error ? err.message : 'The table could not be changed.',
      });
    }
  };
  const tableImportBlocked =
    writeBlocked ?? (cellEdits.size > 0 ? 'Save or discard your changes to the table first.' : null);

  const carriesFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes('Files');
  const onDrop = (e: React.DragEvent) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length !== 1) {
      setImportNote({ color: 'orange', text: 'Drop one file at a time.' });
      return;
    }
    void openImport(files[0]);
  };

  // ---- Columns ------------------------------------------------------------------
  const labelColumnCount = bound?.columns.length ?? 0;
  const colDefs = useMemo<ColDef<GridRow>[]>(
    () => {
      const labelCols = (bound?.columns ?? []).map<ColDef<GridRow>>((c) => {
        const budget = annotationColumnBudget(c, groups);
        const actions: LabelColumnActions = {
          name: c.name,
          active: c.id === bound?.activeColumnId,
          local: Boolean(c.local),
          compareBlocked: budget.ok ? null : budget.reason,
          canKeepOnAccount: Boolean(c.local) && state.storage === 'account',
          saveBlocked: writeBlocked,
          onCompare: () => toggleCompare(c.id),
          onRename: () => setNaming({ id: c.id, value: c.name, error: null }),
          onKeepOnAccount: () => keepOnAccount(c.id),
          onSaveToTable: () => void startSave(c.id),
          onDelete: () => removeLabelColumn(c.id),
        };
        return {
          field: ANN_PREFIX + c.id,
          headerName: c.name,
          headerComponent: LabelColumnHeader,
          headerComponentParams: { actions },
          editable: true,
          valueSetter: setLabelCell,
          sortable: false,
          minWidth: 150,
        };
      });
      const canEditCells = Boolean(table?.edit) && !pinned;
      return [
        { field: KEY_FIELD, headerName: keyColumn || 'key', pinned: 'left', editable: false, minWidth: 140 },
        ...labelCols,
        {
          field: ADD_FIELD,
          headerName: '',
          headerComponent: AddLabelHeader,
          headerComponentParams: {
            onAdd: () => setNaming({ id: null, value: '', error: null }),
            disabled: labelColumnCount >= MAX_ANNOTATION_COLUMNS,
          },
          width: 52,
          minWidth: 52,
          maxWidth: 52,
          editable: false,
          sortable: false,
          filter: false,
          resizable: false,
          suppressMovable: true,
        },
        ...contextColumns.map<ColDef<GridRow>>((c) => {
          const editable = canEditCells && Boolean(table?.edit?.editable.has(c));
          return {
            field: c,
            headerName: c,
            editable,
            valueSetter: editable ? setTableCell : undefined,
            headerTooltip: editable ? 'Click a cell to change the table' : undefined,
            cellClassRules: {
              'dc-label-cell-pending': (p) =>
                p.data?.__row !== null &&
                p.data?.__row !== undefined &&
                cellEdits.has(cellKey(p.data.__row, c)),
            },
            minWidth: 110,
          };
        }),
      ];
    },
    // The actions close over the current state; the defs are rebuilt with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      keyColumn,
      bound,
      contextColumns,
      setLabelCell,
      setTableCell,
      cellEdits,
      groups,
      table,
      pinned,
      writeBlocked,
      state.storage,
      labelColumnCount,
    ],
  );

  // ---- Render ---------------------------------------------------------------------
  const storageNote =
    state.storage === 'browser'
      ? state.browserUnavailable
        ? 'This browser keeps nothing: your labels last until you leave the page.'
        : 'Labels are kept in this browser. Sign in to keep them on your account.'
      : null;
  const activeLocal = bound?.columns.some((c) => c.local && c.id === bound.activeColumnId);

  if (collectionsError) {
    return (
      <Alert color="red" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
        {collectionsError}
      </Alert>
    );
  }
  if (!collections) return <Loader size="sm" />;
  if (tables.length === 0 && !annotations) {
    return <Text size="sm">This dashboard reads no table to label.</Text>;
  }

  return (
    <Stack
      gap="xs"
      onDragOver={(e) => {
        if (!carriesFiles(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
      style={{ position: 'relative' }}
      data-testid="annotation-drop-zone"
    >
      {dragging && (
        <Box className="dc-table-drop-overlay" data-testid="annotation-drop-overlay">
          <Stack gap={4} align="center">
            <Icon icon="mdi:file-table-outline" width={32} />
            <Text fw={600}>Drop to import</Text>
            <Text size="sm" c="dimmed">
              As labels (read in your browser) or into the table. You see the result first.
            </Text>
          </Stack>
        </Box>
      )}

      <Group justify="space-between" gap="xs" wrap="nowrap">
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Text size="sm" fw={500} truncate data-testid="annotation-context">
            {currentLabel}
            {keyColumn && (
              <Text span c="dimmed">
                {' '}
                · {keyColumn}
              </Text>
            )}
          </Text>
          <Anchor
            component="button"
            size="sm"
            onClick={() => setChanging((v) => !v)}
            data-testid="annotation-change"
          >
            {changing ? 'Done' : 'Change'}
          </Anchor>
        </Group>
        <FileButton
          onChange={(f) => f && void openImport(f)}
          accept=".csv,.tsv,.txt,.tab,text/csv,text/tab-separated-values"
          inputProps={{ 'data-testid': 'annotation-file-input' } as React.ComponentProps<'input'>}
        >
          {(props) => (
            <Button
              {...props}
              size="xs"
              variant="subtle"
              color="gray"
              disabled={!table || !keyColumn}
              leftSection={<Icon icon="mdi:tray-arrow-up" width={14} />}
            >
              Import
            </Button>
          )}
        </FileButton>
      </Group>

      {changing && (
        <Group gap="sm" wrap="wrap">
          <Select
            size="xs"
            w={240}
            aria-label="Table"
            data={tables.map((t) => ({ value: t.dc_id, label: tableLabel(t, tables) }))}
            value={choice?.dcId ?? null}
            onChange={(v) => void onTableChange(v)}
            allowDeselect={false}
            data-testid="annotation-table-select"
          />
          <Select
            size="xs"
            w={200}
            aria-label="Key column"
            data={keyOptions}
            value={keyColumn || null}
            onChange={(v) => v && choice && requestChoice({ dcId: choice.dcId, keyColumn: v })}
            allowDeselect={false}
            disabled={!table}
            placeholder={table && keyOptions.length === 0 ? 'No column is unique per row' : undefined}
            data-testid="annotation-key-select"
          />
        </Group>
      )}

      {pendingChoice && (
        <Alert color="orange" py={6}>
          <Group justify="space-between" gap="xs">
            <Text size="sm">
              Your {annotations?.columns.length} label column
              {annotations?.columns.length === 1 ? '' : 's'} belong to another table or key and would
              be discarded.
            </Text>
            <Group gap="xs">
              <Button size="xs" color="orange" onClick={confirmSwitch}>
                Discard and switch
              </Button>
              <Button size="xs" variant="default" onClick={() => setPendingChoice(null)}>
                Keep
              </Button>
            </Group>
          </Group>
        </Alert>
      )}

      {storageNote && (
        <Text size="xs" c="dimmed" data-testid="annotation-storage-note">
          {storageNote}
        </Text>
      )}
      {state.loadError && (
        <Alert color="red" py={6} data-testid="annotation-load-error">
          {state.loadError}
        </Alert>
      )}
      {state.saveError && (
        <Alert color="orange" py={6} data-testid="annotation-save-error">
          {state.saveError}
        </Alert>
      )}
      {activeLocal && (
        <Text size="xs" c="dimmed" data-testid="annotation-local-compare-note">
          The compared labels stay in your browser; to colour the charts they go with each chart
          request, and nothing is stored on the server.
        </Text>
      )}
      {importNote && (
        <Alert
          color={importNote.color}
          py={6}
          withCloseButton
          onClose={() => setImportNote(null)}
          data-testid="annotation-drop-report"
        >
          {importNote.text}
        </Alert>
      )}

      {load.kind === 'loading' && <Loader size="sm" />}
      {load.kind === 'refused' && (
        <Alert color="orange" data-testid="annotation-refused">
          {load.message}
        </Alert>
      )}
      {table && !keyColumn && (
        <Text size="sm">This table has no column unique per row to label rows by.</Text>
      )}
      {table && keyColumn && (
        <>
          <Box
            onPaste={onPaste}
            className={scheme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
            style={{ height: 'calc(100vh - 260px)', minHeight: 300, width: '100%' }}
            data-testid="annotation-grid"
          >
            <AgGridReact<GridRow>
              rowData={rows}
              columnDefs={colDefs}
              defaultColDef={{ sortable: true, filter: true, resizable: true }}
              getRowId={(p) => p.data.__key}
              onGridReady={(e) => {
                gridApi.current = e.api;
              }}
              singleClickEdit
              stopEditingWhenCellsLoseFocus
              tooltipShowDelay={200}
            />
          </Box>

          {cellEdits.size > 0 ? (
            <Paper withBorder radius="sm" px="sm" py={6} data-testid="annotation-cell-bar">
              <Group justify="space-between" gap="xs">
                <Text size="sm">
                  {cellEdits.size} change{cellEdits.size === 1 ? '' : 's'} to the table
                </Text>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => {
                      setCellEdits(new Map());
                      setCellSave({ busy: false, error: null, stale: false });
                    }}
                    data-testid="annotation-cell-discard"
                  >
                    Discard
                  </Button>
                  <Button
                    size="xs"
                    loading={cellSave.busy}
                    onClick={() => void saveCells()}
                    data-testid="annotation-cell-save"
                  >
                    Save to table
                  </Button>
                </Group>
              </Group>
              {cellSave.error && (
                <Group gap="xs" mt={6}>
                  <Text size="xs" c={cellSave.stale ? 'orange' : 'red'}>
                    {cellSave.error}
                  </Text>
                  {cellSave.stale && (
                    <Anchor component="button" size="xs" onClick={() => void reloadTable()}>
                      Reload the table (discards these changes)
                    </Anchor>
                  )}
                </Group>
              )}
            </Paper>
          ) : (
            (missingKeys > 0 || labelColumnCount === 0) && (
              <Text size="xs" c="dimmed">
                {labelColumnCount === 0 &&
                  'Add a label column with +, paste from a spreadsheet, or drop a CSV or TSV here.'}
                {missingKeys > 0 &&
                  ` ${missingKeys} labelled row${missingKeys === 1 ? ' is' : 's are'} no longer in the table; kept, not shown.`}
              </Text>
            )
          )}
        </>
      )}

      <Modal
        opened={naming !== null}
        onClose={() => setNaming(null)}
        title={naming?.id ? 'Rename label column' : 'New label column'}
        size="sm"
        zIndex={Z_LAYERS.nestedOverlay}
      >
        <Stack gap="sm">
          <TextInput
            data-autofocus
            placeholder="e.g. response"
            value={naming?.value ?? ''}
            error={naming?.error}
            onChange={(e) => naming && setNaming({ ...naming, value: e.currentTarget.value, error: null })}
            onKeyDown={(e) => e.key === 'Enter' && submitName()}
            data-testid="label-name-input"
          />
          <Group justify="flex-end" gap="xs">
            <Button size="xs" variant="default" onClick={() => setNaming(null)}>
              Cancel
            </Button>
            <Button
              size="xs"
              onClick={submitName}
              disabled={!naming?.value.trim()}
              data-testid="label-name-save"
            >
              {naming?.id ? 'Rename' : 'Add'}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={importing !== null}
        onClose={() => setImporting(null)}
        title={importing ? `Import ${importing.file.name}` : 'Import'}
        size="lg"
        zIndex={Z_LAYERS.nestedOverlay}
      >
        {importing && (
          <Stack gap="sm" data-testid="annotation-drop-preview">
            <Tooltip
              withinPortal
              disabled={!tableImportBlocked}
              label={tableImportBlocked ?? ''}
              position="bottom-start"
            >
              <div style={{ alignSelf: 'flex-start' }}>
                <SegmentedControl
                  size="xs"
                  value={importing.destination}
                  onChange={(v) =>
                    v === 'table'
                      ? void previewTableImport()
                      : setImporting({ ...importing, destination: 'labels' })
                  }
                  data={[
                    { value: 'labels', label: 'As labels' },
                    { value: 'table', label: 'Into the table', disabled: Boolean(tableImportBlocked) },
                  ]}
                  data-testid="annotation-import-destination"
                />
              </div>
            </Tooltip>

            {importing.destination === 'labels' &&
              ('error' in importing.match ? (
                <Alert color="red" py={6} data-testid="annotation-drop-reason">
                  {importing.match.error}
                </Alert>
              ) : (
                labelsPlan && (
                  <Stack gap="xs">
                    <Group justify="space-between" gap="xs" wrap="wrap">
                      <Text size="xs" c="dimmed">
                        Read in your browser, matched on &quot;{importing.match.fileKeyColumn}&quot;:{' '}
                        {importing.match.matchedRows} row{importing.match.matchedRows === 1 ? '' : 's'}
                      </Text>
                      <SegmentedControl
                        size="xs"
                        value={importing.mode}
                        onChange={(m) => setImporting({ ...importing, mode: m as AnnotationMergeMode })}
                        data={[
                          { value: 'add_columns', label: 'Add columns' },
                          { value: 'fill_missing', label: 'Fill missing' },
                          { value: 'replace', label: 'Replace' },
                        ]}
                        data-testid="annotation-drop-mode"
                      />
                    </Group>
                    <Text size="xs">
                      {importing.mode === 'add_columns' &&
                        'Each new column of the file becomes a label column; the others are left as they are.'}
                      {importing.mode === 'fill_missing' &&
                        'Labels go into the label columns of the same name, only where a row has none.'}
                      {importing.mode === 'replace' &&
                        'The file replaces all your label columns on this table.'}
                    </Text>
                    <Stack gap={2}>
                      {labelsPlan.report.newAnnotations.length > 0 && (
                        <Text size="xs">New: {labelsPlan.report.newAnnotations.join(', ')}</Text>
                      )}
                      {labelsPlan.report.updatedAnnotations.length > 0 && (
                        <Text size="xs">Filled: {labelsPlan.report.updatedAnnotations.join(', ')}</Text>
                      )}
                      {labelsPlan.report.removedAnnotations.length > 0 && (
                        <Text size="xs" c="orange">
                          Removed: {labelsPlan.report.removedAnnotations.join(', ')}
                        </Text>
                      )}
                      <Text size="xs" c="dimmed">
                        {labelsPlan.report.labels} label{labelsPlan.report.labels === 1 ? '' : 's'}{' '}
                        written
                        {labelsPlan.report.conflicts > 0 &&
                          ` · ${labelsPlan.report.conflicts} differing label${labelsPlan.report.conflicts === 1 ? '' : 's'} kept as they are`}
                        {labelsPlan.report.ignored.length > 0 &&
                          ` · left out: ${labelsPlan.report.ignored.map((x) => `${x.name} (${x.reason})`).join(', ')}`}
                      </Text>
                      {importing.match.unmatchedRows > 0 && (
                        <Text size="xs" c="orange">
                          {importing.match.unmatchedRows} row
                          {importing.match.unmatchedRows === 1 ? '' : 's'} not in the table, left out (
                          {importing.match.unmatchedSample.join(', ')}
                          {importing.match.unmatchedRows > importing.match.unmatchedSample.length
                            ? ', …'
                            : ''}
                          )
                        </Text>
                      )}
                    </Stack>
                    {labelsPlan.report.reason && (
                      <Alert color="red" py={6} data-testid="annotation-drop-reason">
                        {labelsPlan.report.reason}
                      </Alert>
                    )}
                    <Group justify="flex-end" gap="xs">
                      <Button size="xs" variant="default" onClick={() => setImporting(null)}>
                        Cancel
                      </Button>
                      <Button
                        size="xs"
                        onClick={applyLabelsImport}
                        disabled={Boolean(labelsPlan.report.reason)}
                        data-testid="annotation-drop-apply"
                      >
                        Apply
                      </Button>
                    </Group>
                  </Stack>
                )
              ))}

            {importing.destination === 'table' && (
              <Stack gap="xs">
                <Text size="xs" c="dimmed">
                  The file is sent to the server and changes the table itself.
                </Text>
                {importing.tableBusy && !importing.tableReport && <Loader size="sm" />}
                {importing.tableError && (
                  <Alert color="red" py={6}>
                    {importing.tableError}
                  </Alert>
                )}
                {importing.tableReport && (
                  <TableMergePanel
                    report={importing.tableReport}
                    fileName={importing.file.name}
                    busy={importing.tableBusy}
                    applying={importing.tableApplying}
                    onMode={(m) => void previewTableImport(m, importing.tableReport?.key ?? null)}
                    onKey={(k) => void previewTableImport(importing.tableReport?.mode ?? 'auto', k)}
                    onApply={() => void applyTableImport()}
                    onCancel={() => setImporting(null)}
                  />
                )}
              </Stack>
            )}
          </Stack>
        )}
      </Modal>

      <Modal
        opened={saving !== null}
        onClose={() => setSaving(null)}
        title="Save to table"
        size="lg"
        zIndex={Z_LAYERS.nestedOverlay}
        data-testid="annotation-save-modal"
      >
        <LoadingOverlay visible={Boolean(saving?.busy)} />
        {saving?.error && (
          <Alert color={saving.stale ? 'orange' : 'red'} mb="sm">
            <Stack gap="xs">
              <Text size="sm">{saving.error}</Text>
              {saving.stale && (
                <Button
                  size="xs"
                  variant="light"
                  color="orange"
                  onClick={() => {
                    void reloadTable().then(() => startSave(saving.columnId));
                  }}
                >
                  Reload the table and check again
                </Button>
              )}
            </Stack>
          </Alert>
        )}
        {saving?.report && (
          <Stack gap="xs">
            <Text size="sm">
              {saving.report.matched_rows} of {saving.report.table_rows} rows get a value
              {saving.report.new_columns.length > 0 &&
                ` in the new column ${saving.report.new_columns.map((c) => `"${c}"`).join(', ')}`}
              .
            </Text>
            {saving.report.warnings.map((w) => (
              <Text key={w} size="xs" c="orange">
                {w}
              </Text>
            ))}
            {saving.report.reason && (
              <Alert color="red" py={6} data-testid="annotation-save-reason">
                {saving.report.reason}
              </Alert>
            )}
            <Group justify="flex-end" gap="xs">
              <Button variant="default" size="xs" onClick={() => setSaving(null)}>
                Cancel
              </Button>
              <Button
                size="xs"
                onClick={() => void applySave()}
                disabled={!saving.report.can_apply || Boolean(saving.report.reason)}
                data-testid="annotation-save-apply"
              >
                Add the column
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
};

export default AnnotationPanel;
