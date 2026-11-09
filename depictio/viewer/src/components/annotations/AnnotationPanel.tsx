import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Group,
  Loader,
  LoadingOverlay,
  FileButton,
  Menu,
  Modal,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Tabs,
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
  distinctLabels,
  emptyAnnotations,
  fetchDataCollectionPreview,
  fetchDataVersionStatus,
  fetchTableEditStatus,
  matchDroppedTable,
  MAX_ANNOTATION_COLUMNS,
  MAX_ANNOTATION_ROWS,
  MAX_DROP_BYTES,
  MAX_LABEL_LENGTH,
  mergeTableFile,
  newAnnotationId,
  parseDroppedTable,
  parsePastedBlock,
  planAnnotationMerge,
  setLabel,
  suggestedMergeMode,
  TableEditError,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  AnnotationMergeMode,
  DashboardAnnotations,
  DropMatch,
  DataPinFields,
  DataVersionCollectionStatus,
  SelectionGroup,
  TableEditStatus,
  TableMergeReport,
} from 'depictio-react-core';

import TableEditor from '../../projects/detail/TableEditor';
// The drop overlay is the table editor's, so both drops look the same.
import '../../projects/detail/TableEditor.css';
import type { DashboardAnnotationsState } from './useDashboardAnnotations';

/** One grid row: the key, the read-only context, one field per annotation. */
type GridRow = Record<string, unknown> & { __key: string };

const ANN_PREFIX = 'ann:';
const KEY_FIELD = '__key';

interface TableRead {
  dcId: string;
  columns: string[];
  rows: Record<string, unknown>[];
  /** Delta version read; null for the current table. */
  version: number | null;
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

export interface AnnotationPanelProps {
  /** The rendered tab: the data-version status call reads the whole family from it. */
  dashboardId: string;
  /** Data pins of a past-version view, or null on a live view. */
  pins: DataPinFields | null;
  state: DashboardAnnotationsState;
  /** Every group on the dashboard, for the 24-group budget. */
  groups: SelectionGroup[];
  onOpenAnalysis: () => void;
  /** A real write landed: re-render the dashboard. */
  onDataWritten: () => void;
}

const AnnotationPanel: React.FC<AnnotationPanelProps> = ({
  dashboardId,
  pins,
  state,
  groups,
  onOpenAnalysis,
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
      }
      try {
        const res = await fetchDataCollectionPreview(dcId, MAX_ANNOTATION_ROWS, [], version);
        const load: Load =
          res.total_rows > MAX_ANNOTATION_ROWS
            ? {
                kind: 'refused',
                message: `This table has ${res.total_rows.toLocaleString()} rows. Annotation reads tables of up to ${MAX_ANNOTATION_ROWS.toLocaleString()} rows, so that the list of samples is never cut short; pick a smaller table.`,
              }
            : {
                kind: 'ready',
                table: { dcId, columns: res.columns, rows: res.rows, version: res.version ?? null },
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
    [collections, pinned],
  );

  // ---- Which table and key -------------------------------------------------
  const [choice, setChoice] = useState<{ dcId: string; keyColumn: string } | null>(null);
  const [load, setLoad] = useState<Load>({ kind: 'idle' });

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

  // Annotations of another table or key would be lost by a switch: ask first.
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

  // ---- Grid rows ----------------------------------------------------------
  const { rows, contextColumns, tableKeys } = useMemo(() => {
    if (!table || !keyColumn) {
      return { rows: [] as GridRow[], contextColumns: [] as string[], tableKeys: new Set<string>() };
    }
    const first = new Map<string, Record<string, unknown>>();
    const perKey = new Map<string, Map<string, Set<string>>>();
    for (const row of table.rows) {
      const key = asKey(row[keyColumn]);
      if (key === null) continue;
      if (!first.has(key)) first.set(key, row);
      let cols = perKey.get(key);
      if (!cols) perKey.set(key, (cols = new Map()));
      for (const c of table.columns) {
        let vals = cols.get(c);
        if (!vals) cols.set(c, (vals = new Set()));
        vals.add(JSON.stringify(row[c] ?? null));
      }
    }
    // With several rows per key, only columns holding one value per key can stand for the key.
    const context = table.columns.filter(
      (c) => c !== keyColumn && [...perKey.values()].every((cols) => (cols.get(c)?.size ?? 0) <= 1),
    );
    const out: GridRow[] = [];
    for (const [key, row] of first) {
      const r: GridRow = { __key: key };
      for (const c of context) r[c] = row[c];
      for (const col of bound?.columns ?? []) r[ANN_PREFIX + col.id] = col.values[key] ?? '';
      out.push(r);
    }
    return { rows: out, contextColumns: context, tableKeys: new Set(first.keys()) };
  }, [table, keyColumn, bound]);

  const missingKeys = useMemo(() => {
    if (!bound || tableKeys.size === 0) return 0;
    const all = new Set<string>();
    for (const c of bound.columns) for (const k of Object.keys(c.values)) all.add(k);
    return [...all].filter((k) => !tableKeys.has(k)).length;
  }, [bound, tableKeys]);

  // ---- Edits --------------------------------------------------------------
  const commit = useCallback(
    (next: DashboardAnnotations) => {
      setAnnotations(next);
    },
    [setAnnotations],
  );

  const gridApi = useRef<GridApi<GridRow> | null>(null);
  const setCell = useCallback(
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

  const colDefs = useMemo<ColDef<GridRow>[]>(
    () => [
      { field: KEY_FIELD, headerName: keyColumn || 'key', pinned: 'left', editable: false, minWidth: 140 },
      ...(bound?.columns ?? []).map<ColDef<GridRow>>((c) => ({
        field: ANN_PREFIX + c.id,
        headerName: c.name,
        editable: true,
        valueSetter: setCell,
        cellClass: 'dc-annotation-cell',
        headerTooltip: 'Type a label, or paste a column from a spreadsheet',
        minWidth: 130,
      })),
      ...contextColumns.map<ColDef<GridRow>>((c) => ({
        field: c,
        headerName: c,
        editable: false,
        minWidth: 110,
      })),
    ],
    [keyColumn, bound, contextColumns, setCell],
  );

  const [newName, setNewName] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const addAnnotation = () => {
    const base = ensureBound();
    const name = newName.trim();
    if (!base || !name) return;
    if (base.columns.length >= MAX_ANNOTATION_COLUMNS) {
      setAddError(`At most ${MAX_ANNOTATION_COLUMNS} annotations.`);
      return;
    }
    if (name.length > MAX_LABEL_LENGTH) {
      setAddError(`A name has at most ${MAX_LABEL_LENGTH} characters.`);
      return;
    }
    if (base.columns.some((c) => c.name === name) || name === keyColumn) {
      setAddError(`"${name}" is already a column here.`);
      return;
    }
    const id = newAnnotationId();
    commit({
      ...base,
      columns: [...base.columns, { id, name, values: {} }],
      activeColumnId: base.activeColumnId,
    });
    setNewName('');
    setAddError(null);
  };
  /** Send a file's annotation to the account: the reader's explicit choice. */
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
  const removeAnnotation = (id: string) => {
    if (!bound) return;
    commit({
      ...bound,
      columns: bound.columns.filter((c) => c.id !== id),
      activeColumnId: bound.activeColumnId === id ? null : bound.activeColumnId,
    });
  };

  // Paste: AG Grid Community has no clipboard, so a block pasted on a focused
  // annotation cell is written from that cell down and to the right.
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
    const annCols = api
      .getAllDisplayedColumns()
      .map((c) => c.getColId())
      .filter((id) => id.startsWith(ANN_PREFIX));
    const firstCol = annCols.indexOf(startCol);
    let next = base;
    let skipped = 0;
    block.forEach((cells, i) => {
      const row = api.getDisplayedRowAtIndex(focused.rowIndex + i);
      if (!row?.data) {
        skipped += 1;
        return;
      }
      cells.forEach((cell, j) => {
        const colId = annCols[firstCol + j];
        if (!colId) return;
        next = setLabel(next, colId.slice(ANN_PREFIX.length), row.data!.__key, cell.slice(0, MAX_LABEL_LENGTH));
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

  // Drop or pick a file: read in the browser, never uploaded. Like the table
  // editor's file merge, it opens a preview with three modes; nothing changes
  // until the reader applies it.
  const [dropReport, setDropReport] = useState<{ color: string; text: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pendingDrop, setPendingDrop] = useState<{
    fileName: string;
    match: DropMatch;
    mode: AnnotationMergeMode;
  } | null>(null);
  const readFile = async (file: File) => {
    const base = ensureBound();
    if (!base) return;
    setDropReport(null);
    if (!/\.(csv|tsv|txt|tab)$/i.test(file.name)) {
      setDropReport({ color: 'red', text: 'Drop a CSV or TSV file. Excel and Parquet are not read here.' });
      return;
    }
    if (file.size > MAX_DROP_BYTES) {
      setDropReport({ color: 'red', text: 'The file is over 5 MB.' });
      return;
    }
    const parsed = parseDroppedTable(file.name, await file.text());
    if ('error' in parsed) {
      setDropReport({ color: 'red', text: parsed.error });
      return;
    }
    const match = matchDroppedTable(parsed, keyColumn, tableKeys);
    if ('error' in match) {
      setDropReport({ color: 'red', text: match.error });
      return;
    }
    setPendingDrop({ fileName: file.name, match, mode: suggestedMergeMode(base, match) });
  };
  const carriesFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes('Files');
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length !== 1) {
      setDropReport({ color: 'orange', text: 'Drop one file at a time.' });
      return;
    }
    void readFile(files[0]);
  };
  const plan = useMemo(() => {
    const base = ensureBound();
    return pendingDrop && base
      ? planAnnotationMerge(base, pendingDrop.match, pendingDrop.mode)
      : null;
    // ensureBound reads bound and choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingDrop, bound, choice, keyColumn]);
  const applyDrop = () => {
    if (!plan || !pendingDrop || plan.report.reason) return;
    commit(plan.next);
    setPendingDrop(null);
    setDropReport({
      color: 'teal',
      text:
        `${pendingDrop.fileName} applied: ${plan.report.labels} label${plan.report.labels === 1 ? '' : 's'}.` +
        (state.storage === 'account'
          ? ' What it wrote stays in this browser; use the cloud icon to keep an annotation on your account.'
          : ''),
    });
  };

  // ---- Compare by ----------------------------------------------------------
  const budgets = useMemo(
    () => new Map((bound?.columns ?? []).map((c) => [c.id, annotationColumnBudget(c, groups)] as const)),
    [bound, groups],
  );
  const setActive = (id: string | null) => {
    if (!bound) return;
    commit({ ...bound, activeColumnId: id });
  };
  const blocked = (bound?.columns ?? []).filter((c) => {
    const b = budgets.get(c.id);
    return b && !b.ok;
  });

  // ---- Real writes ----------------------------------------------------------
  const [editStatus, setEditStatus] = useState<TableEditStatus | null>(null);
  useEffect(() => {
    setEditStatus(null);
    if (!choice?.dcId) return;
    let cancelled = false;
    fetchTableEditStatus(choice.dcId)
      .then((s) => !cancelled && setEditStatus(s))
      .catch(() => !cancelled && setEditStatus(null));
    return () => {
      cancelled = true;
    };
  }, [choice?.dcId]);
  const writeBlocked: string | null = pinned
    ? 'This view shows a past version; a change to the table would not appear in it.'
    : !editStatus
      ? 'Checking whether you can change this table…'
      : !editStatus.can_edit
        ? editStatus.reason || 'You cannot change this table.'
        : null;

  const reloadTable = async () => {
    if (!choice) return;
    const l = await readTable(choice.dcId, true);
    setLoad(l);
  };
  const afterWrite = async () => {
    await reloadTable();
    onDataWritten();
  };

  const [saving, setSaving] = useState<{
    columnId: string;
    report: TableMergeReport | null;
    error: string | null;
    stale: boolean;
    busy: boolean;
  } | null>(null);
  const toCsvFile = (columnId: string): File | null => {
    const col = bound?.columns.find((c) => c.id === columnId);
    if (!col) return null;
    const lines = [`${csvCell(keyColumn)},${csvCell(col.name)}`];
    for (const [key, label] of Object.entries(col.values)) {
      if (tableKeys.has(key)) lines.push(`${csvCell(key)},${csvCell(label)}`);
    }
    // Built here from the labels; this is the write the user asked for.
    return new File([lines.join('\n') + '\n'], `${col.name}.csv`, { type: 'text/csv' });
  };
  const startSave = async (columnId: string) => {
    const file = toCsvFile(columnId);
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
    const file = toCsvFile(saving.columnId);
    if (!file) return;
    setSaving({ ...saving, busy: true });
    try {
      await mergeTableFile(choice.dcId, file, {
        mode: saving.report.mode,
        key: saving.report.key,
        baseVersion: saving.report.delta_version,
        dryRun: false,
      });
      const name = bound?.columns.find((c) => c.id === saving.columnId)?.name ?? 'The annotation';
      removeAnnotation(saving.columnId);
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

  // ---- Render ---------------------------------------------------------------
  const [tab, setTab] = useState<string | null>('annotate');
  const storageNote =
    state.storage === 'browser'
      ? state.browserUnavailable
        ? 'This browser keeps nothing: your annotations last until you leave the page.'
        : 'Kept in this browser. A temporary account cannot keep annotations on an account; sign in to keep them anywhere.'
      : state.pending
        ? 'Saving to your account…'
        : annotations?.columns.some((c) => c.local)
          ? 'Kept on your account, except annotations from a dropped file, which stay in this browser. Only you see them.'
          : 'Kept on your account. Only you see them.';

  if (collectionsError) {
    return (
      <Alert color="red" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
        {collectionsError}
      </Alert>
    );
  }
  if (!collections) return <Loader size="sm" />;
  if (tables.length === 0 && !annotations) {
    return <Text size="sm">This dashboard reads no table to annotate.</Text>;
  }

  return (
    <Stack gap="sm" data-testid="annotation-panel-body">
      <Group gap="sm" align="flex-end" wrap="wrap">
        <Select
          label="Table"
          size="xs"
          w={220}
          data={tables.map((t) => ({ value: t.dc_id, label: tableLabel(t, tables) }))}
          value={choice?.dcId ?? null}
          onChange={(v) => void onTableChange(v)}
          allowDeselect={false}
          data-testid="annotation-table-select"
        />
        <Select
          label="Key column"
          size="xs"
          w={200}
          data={keyOptions}
          value={keyColumn || null}
          onChange={(v) => v && choice && requestChoice({ dcId: choice.dcId, keyColumn: v })}
          allowDeselect={false}
          disabled={!table}
          placeholder={table && keyOptions.length === 0 ? 'No column is unique per row' : undefined}
          data-testid="annotation-key-select"
        />
      </Group>

      {pendingChoice && (
        <Alert color="orange" title="Switch and discard?">
          <Stack gap="xs">
            <Text size="sm">
              Your {annotations?.columns.length} annotation
              {annotations?.columns.length === 1 ? '' : 's'} belong to another table or key and
              would be discarded.
            </Text>
            <Group gap="xs">
              <Button size="xs" color="orange" onClick={confirmSwitch}>
                Switch and discard
              </Button>
              <Button size="xs" variant="default" onClick={() => setPendingChoice(null)}>
                Keep them
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}

      <Text size="xs" c="dimmed" data-testid="annotation-storage-note">
        {storageNote}
      </Text>
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

      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="annotate" leftSection={<Icon icon="mdi:tag-text-outline" width={14} />}>
            Annotate
          </Tabs.Tab>
          <Tooltip label={writeBlocked} disabled={!writeBlocked} withinPortal>
            <Tabs.Tab
              value="edit"
              disabled={Boolean(writeBlocked)}
              leftSection={<Icon icon="mdi:table-edit" width={14} />}
              data-testid="annotation-edit-tab"
            >
              Edit table
            </Tabs.Tab>
          </Tooltip>
        </Tabs.List>

        <Tabs.Panel value="annotate" pt="sm">
          {load.kind === 'loading' && <Loader size="sm" />}
          {load.kind === 'refused' && (
            <Alert color="orange" data-testid="annotation-refused">
              {load.message}
            </Alert>
          )}
          {table && !keyColumn && (
            <Text size="sm">This table has no column unique per row to key annotations on.</Text>
          )}
          {table && keyColumn && (
            <Stack gap="xs">
              <Group gap="xs" align="flex-end" wrap="wrap">
                <TextInput
                  size="xs"
                  label="New annotation"
                  placeholder="e.g. response"
                  value={newName}
                  onChange={(e) => setNewName(e.currentTarget.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addAnnotation()}
                  error={addError}
                  w={180}
                  data-testid="annotation-new-name"
                />
                <Button
                  size="xs"
                  leftSection={<Icon icon="mdi:plus" width={14} />}
                  onClick={addAnnotation}
                  disabled={!newName.trim()}
                  data-testid="annotation-add"
                >
                  Add annotation
                </Button>
                <FileButton
                  onChange={(f) => f && void readFile(f)}
                  accept=".csv,.tsv,.txt,.tab,text/csv,text/tab-separated-values"
                  inputProps={{ 'data-testid': 'annotation-file-input' } as React.ComponentProps<'input'>}
                >
                  {(props) => (
                    <Button
                      {...props}
                      size="xs"
                      variant="default"
                      leftSection={<Icon icon="mdi:file-upload-outline" width={14} />}
                    >
                      Annotate from file
                    </Button>
                  )}
                </FileButton>
                <Select
                  size="xs"
                  label="Compare by"
                  w={220}
                  placeholder="None"
                  clearable
                  data={(bound?.columns ?? []).map((c) => ({
                    value: c.id,
                    label: `${c.name} (${distinctLabels(c).length} labels)`,
                    disabled: !budgets.get(c.id)?.ok,
                  }))}
                  value={bound?.activeColumnId ?? null}
                  onChange={setActive}
                  disabled={!bound || bound.columns.length === 0}
                  data-testid="annotation-compare-by"
                />
                <Button
                  size="xs"
                  variant="light"
                  onClick={onOpenAnalysis}
                  disabled={!bound?.activeColumnId}
                  data-testid="annotation-open-analysis"
                >
                  Open Analysis
                </Button>
                <Menu withinPortal position="bottom-end">
                  <Menu.Target>
                    <Tooltip label={writeBlocked} disabled={!writeBlocked} withinPortal>
                      <Button
                        size="xs"
                        variant="default"
                        disabled={Boolean(writeBlocked) || !bound || bound.columns.length === 0}
                        leftSection={<Icon icon="mdi:table-column-plus-after" width={14} />}
                        data-testid="annotation-save-to-table"
                      >
                        Save to table
                      </Button>
                    </Tooltip>
                  </Menu.Target>
                  <Menu.Dropdown>
                    {(bound?.columns ?? []).map((c) => (
                      <Menu.Item key={c.id} onClick={() => void startSave(c.id)}>
                        {c.name}
                      </Menu.Item>
                    ))}
                  </Menu.Dropdown>
                </Menu>
              </Group>

              {bound?.columns.some((c) => c.local && c.id === bound.activeColumnId) && (
                <Text size="xs" c="dimmed" data-testid="annotation-local-compare-note">
                  This annotation stays in your browser. To colour and split the charts, its labels
                  and keys go with each chart request; nothing is stored on the server.
                </Text>
              )}
              {blocked.map((c) => {
                const b = budgets.get(c.id);
                return b && !b.ok ? (
                  <Text key={c.id} size="xs" c="dimmed">
                    {c.name}: {b.reason}
                  </Text>
                ) : null;
              })}

              {(bound?.columns.length ?? 0) > 0 && (
                <Group gap={6} wrap="wrap" data-testid="annotation-list">
                  {bound!.columns.map((c) => {
                    const active = c.id === bound!.activeColumnId;
                    return (
                      <Paper
                        key={c.id}
                        withBorder
                        radius="sm"
                        px={8}
                        py={2}
                        data-testid={c.local ? 'annotation-item-local' : 'annotation-item'}
                        data-active={active || undefined}
                        style={
                          active ? { borderColor: 'var(--mantine-primary-color-filled)' } : undefined
                        }
                      >
                        <Group gap={6} wrap="nowrap">
                          {c.local && (
                            <Tooltip
                              withinPortal
                              label="From a dropped file: kept in this browser only."
                            >
                              <Icon
                                icon="mdi:monitor"
                                width={13}
                                aria-label="Kept in this browser"
                                style={{ color: 'var(--mantine-color-dimmed)' }}
                              />
                            </Tooltip>
                          )}
                          <Text size="xs" fw={active ? 600 : 500}>
                            {c.name}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {Object.keys(c.values).length}
                          </Text>
                          {c.local && state.storage === 'account' && (
                            <Tooltip withinPortal label="Keep on my account (its labels are sent to the server)">
                              <ActionIcon
                                size="xs"
                                variant="subtle"
                                color="gray"
                                aria-label={`Keep ${c.name} on my account`}
                                data-testid="annotation-keep-on-account"
                                onClick={() => keepOnAccount(c.id)}
                              >
                                <Icon icon="mdi:cloud-upload-outline" width={13} />
                              </ActionIcon>
                            </Tooltip>
                          )}
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            color="gray"
                            aria-label={`Remove ${c.name}`}
                            onClick={() => removeAnnotation(c.id)}
                          >
                            <Icon icon="mdi:close" width={12} />
                          </ActionIcon>
                        </Group>
                      </Paper>
                    );
                  })}
                </Group>
              )}

              {pendingDrop && plan && (
                <Paper withBorder radius="md" p="sm" data-testid="annotation-drop-preview">
                  <Stack gap="xs">
                    <Group justify="space-between" wrap="wrap" gap="xs">
                      <Text size="sm" fw={600}>
                        {pendingDrop.fileName}
                        <Text span size="xs" c="dimmed" fw={400}>
                          {' '}· read in your browser, matched on &quot;{pendingDrop.match.fileKeyColumn}&quot;:{' '}
                          {pendingDrop.match.matchedRows} row{pendingDrop.match.matchedRows === 1 ? '' : 's'}
                        </Text>
                      </Text>
                      <SegmentedControl
                        size="xs"
                        value={pendingDrop.mode}
                        onChange={(m) => setPendingDrop({ ...pendingDrop, mode: m as AnnotationMergeMode })}
                        data={[
                          { value: 'add_columns', label: 'Add columns' },
                          { value: 'fill_missing', label: 'Fill missing' },
                          { value: 'replace', label: 'Replace' },
                        ]}
                        data-testid="annotation-drop-mode"
                      />
                    </Group>
                    <Text size="xs">
                      {pendingDrop.mode === 'add_columns' &&
                        'Each new column of the file becomes an annotation; existing annotations are left as they are.'}
                      {pendingDrop.mode === 'fill_missing' &&
                        'Labels go into the annotations of the same name, only where a row has none.'}
                      {pendingDrop.mode === 'replace' &&
                        'The file replaces all your annotations on this table.'}
                    </Text>
                    <Stack gap={2}>
                      {plan.report.newAnnotations.length > 0 && (
                        <Text size="xs">New: {plan.report.newAnnotations.join(', ')}</Text>
                      )}
                      {plan.report.updatedAnnotations.length > 0 && (
                        <Text size="xs">Filled: {plan.report.updatedAnnotations.join(', ')}</Text>
                      )}
                      {plan.report.removedAnnotations.length > 0 && (
                        <Text size="xs" c="orange">
                          Removed: {plan.report.removedAnnotations.join(', ')}
                        </Text>
                      )}
                      <Text size="xs" c="dimmed">
                        {plan.report.labels} label{plan.report.labels === 1 ? '' : 's'} written
                        {plan.report.conflicts > 0 &&
                          ` · ${plan.report.conflicts} differing label${plan.report.conflicts === 1 ? '' : 's'} kept as they are`}
                        {plan.report.ignored.length > 0 &&
                          ` · left out: ${plan.report.ignored.map((x) => `${x.name} (${x.reason})`).join(', ')}`}
                      </Text>
                      {pendingDrop.match.unmatchedRows > 0 && (
                        <Text size="xs" c="orange">
                          {pendingDrop.match.unmatchedRows} row{pendingDrop.match.unmatchedRows === 1 ? '' : 's'} not in
                          the table, left out ({pendingDrop.match.unmatchedSample.join(', ')}
                          {pendingDrop.match.unmatchedRows > pendingDrop.match.unmatchedSample.length ? ', …' : ''})
                        </Text>
                      )}
                    </Stack>
                    {plan.report.reason && (
                      <Alert color="red" py={6} data-testid="annotation-drop-reason">
                        {plan.report.reason}
                      </Alert>
                    )}
                    <Group justify="flex-end" gap="xs">
                      <Button
                        size="xs"
                        variant="default"
                        onClick={() => setPendingDrop(null)}
                        data-testid="annotation-drop-cancel"
                      >
                        Cancel
                      </Button>
                      <Button
                        size="xs"
                        onClick={applyDrop}
                        disabled={Boolean(plan.report.reason)}
                        data-testid="annotation-drop-apply"
                      >
                        Apply
                      </Button>
                    </Group>
                  </Stack>
                </Paper>
              )}

              {dropReport && (
                <Alert
                  color={dropReport.color}
                  py={6}
                  withCloseButton
                  onClose={() => setDropReport(null)}
                  data-testid="annotation-drop-report"
                >
                  {dropReport.text}
                </Alert>
              )}

              <Box
                onPaste={onPaste}
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
                data-testid="annotation-drop-zone"
                style={{ position: 'relative' }}
              >
                {dragging && (
                  <Box className="dc-table-drop-overlay" data-testid="annotation-drop-overlay">
                    <Stack gap={4} align="center">
                      <Icon icon="mdi:file-table-outline" width={32} />
                      <Text fw={600}>Drop to annotate</Text>
                      <Text size="sm" c="dimmed">
                        Add columns, fill missing labels or replace them. Read in your browser; you
                        see the result first.
                      </Text>
                    </Stack>
                  </Box>
                )}
                <Box
                  className={scheme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
                  style={{ height: 'calc(100vh - 420px)', minHeight: 280, width: '100%' }}
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
              </Box>
              <Text size="xs" c="dimmed">
                {rows.length.toLocaleString()} rows
                {missingKeys > 0 &&
                  ` · ${missingKeys} labelled key${missingKeys === 1 ? ' is' : 's are'} not in the table now; kept, not shown`}
                {' · '}Drop a CSV or TSV on the grid, or use Annotate from file: it is read in your browser and never uploaded.
              </Text>
            </Stack>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="edit" pt="sm">
          {choice?.dcId && !writeBlocked && (
            <Stack gap="xs">
              <Alert color="blue" py={6}>
                Changes here, files dropped here included, are written to the table itself.
              </Alert>
              <TableEditor
                dcId={choice.dcId}
                onSaved={() => void afterWrite()}
                onShowReadOnly={() => setTab('annotate')}
              />
            </Stack>
          )}
        </Tabs.Panel>
      </Tabs>

      <Modal
        opened={saving !== null}
        onClose={() => setSaving(null)}
        title="Save to table"
        size="lg"
        // Opened from inside the Annotate drawer.
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
