import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Box,
  Button,
  Checkbox,
  FileButton,
  Group,
  Loader,
  LoadingOverlay,
  Modal,
  Paper,
  Popover,
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
import type {
  CellMouseDownEvent,
  CellMouseOverEvent,
  ColDef,
  GridApi,
  ValueSetterParams,
} from 'ag-grid-community';
import {
  annotationColumnBudget,
  asKey,
  buildMetadataSheet,
  columnsFor,
  copyName,
  emptyAnnotations,
  fetchDataVersionStatus,
  matchDroppedTable,
  MAX_ANNOTATION_COLUMNS,
  MAX_DROP_BYTES,
  MAX_LABEL_LENGTH,
  mergeTableFile,
  metadataSheetName,
  newAnnotationId,
  parseDroppedTable,
  parsePastedBlock,
  patchTableCells,
  planAnnotationMerge,
  setLabel,
  suggestedMergeMode,
  TableEditError,
  withShared,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  AnnotationColumn,
  AnnotationMergeMode,
  AnnotationTable,
  AnnotationTarget,
  DashboardAnnotations,
  DataPinFields,
  DataVersionCollectionStatus,
  DropMatch,
  SelectionGroup,
  TableMergeMode,
  TableMergeReport,
} from 'depictio-react-core';

import TableMergePanel from '../../projects/detail/TableMergePanel';
// The drop overlay is the table editor's, so both drops look the same.
import '../../projects/detail/TableEditor.css';
import FillCell from './FillCell';
import LabelColumnHeader, {
  LABEL_KIND,
  type LabelColumnActions,
  type LabelColumnKind,
} from './LabelColumnHeader';
import './AnnotationPanel.css';
import {
  cachedEditStatus,
  defaultAnnotationTable,
  forgetAnnotationTable,
  readAnnotationTable,
  type Load,
} from './annotationTableRead';
import type { AnnotationTablesState } from './useAnnotationTables';
import type { DashboardAnnotationsState } from './useDashboardAnnotations';

/** Edit-status codes of a table whose data lives outside Depictio (a pipeline
 *  run, a URL, an ingest of unknown origin): the labels go back through that
 *  source, so the refusal points to Export. */
const SOURCE_ELSEWHERE = new Set(['pipeline_table', 'url_table', 'not_user_added']);

/** One grid row: the key, its row in the table when it can be edited, the
 *  table's columns and one field per label column. */
type GridRow = Record<string, unknown> & { __key: string; __row: number | null };
/** A cell in display coordinates: row index and column index. */
type CellPos = { row: number; col: number };

/** The panel's slide and the dashboard's re-flow around it (250 ms + margin). */
const PANEL_SETTLE_MS = 300;

/** What undo and redo restore (see `history` in the panel). */
interface Snapshot {
  annotations: DashboardAnnotations | null;
  shared: AnnotationColumn[];
  cellEdits: Map<string, { row: number; column: string; value: string | null }>;
}
/** Steps kept to go back through. */
const UNDO_DEPTH = 100;

/** At most this many rows, the grid is as tall as they are. */
const FIT_ROWS_MAX = 40;
const ANN_PREFIX = 'ann:';
const KEY_FIELD = '__key';

/** A table's name, with its workflow when another table has the same tag. */
export function annotationTableLabel(entry: AnnotationTable, all: AnnotationTable[]): string {
  const tag = entry.tag || entry.dc_id;
  const clash = all.filter((e) => e.tag === entry.tag).length > 1;
  return clash && entry.workflow_name ? `${entry.workflow_name} / ${tag}` : tag;
}

function csvCell(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

const cellKey = (row: number, column: string) => `${row}\u0000${column}`;

export interface AnnotationPanelProps {
  /** The rendered tab: the data-version status call reads the whole family from it. */
  dashboardId: string;
  /** The dashboard's project: a table's own page is under it. */
  projectId?: string;
  /** The project's tables with whether each can carry labels (server rule). */
  tables: AnnotationTable[];
  /** The labels shared on the dashboard, and whether this reader may change them. */
  sharing: Pick<AnnotationTablesState, 'shared' | 'canShare' | 'saveShared'>;
  /** Data pins of a past-version view, or null on a live view. */
  pins: DataPinFields | null;
  state: DashboardAnnotationsState;
  /** Every group on the dashboard, for the 24-group budget. */
  groups: SelectionGroup[];
  /** A real write landed: re-render the dashboard. */
  onDataWritten: () => void;
}

/**
 * The Metadata panel: one grid per metadata table (a samplesheet or a
 * metadata sheet linked to the data). Label columns hold session labels, each
 * belonging to its table (each label of the compared one is a group in
 * Analysis); the table's own columns can be edited in place by whoever may
 * write to the table, saved in one go from the bar under the grid. Every
 * column action is in its header menu.
 */
const AnnotationPanel: React.FC<AnnotationPanelProps> = ({
  dashboardId,
  projectId,
  tables: allTables,
  sharing,
  pins,
  state,
  groups,
  onDataWritten,
}) => {
  const scheme = useComputedColorScheme('light');
  const { annotations, setAnnotations } = state;
  const pinned = pins !== null;
  // The reader's own labels (`annotations`) and the dashboard's shared ones,
  // as one set: what the grid shows. Own labels are written through
  // `setAnnotations`, shared ones through `saveShared`.
  const { shared, saveShared } = sharing;
  const canShare = sharing.canShare && !pinned;
  const view = useMemo(() => withShared(annotations, shared), [annotations, shared]);
  const isShared = useCallback((id: string) => shared.some((c) => c.id === id), [shared]);
  // ---- Undo and redo --------------------------------------------------------
  // What a change can touch, kept whole before it: the reader's labels, the
  // shared ones and the table cells waiting for Save. One entry per action: a
  // paste that lands on three kinds of cell is one step back, not three.
  const history = useRef<{ undo: Snapshot[]; redo: Snapshot[] }>({ undo: [], redo: [] });
  const live = useRef<Snapshot | null>(null);
  const sameTick = useRef(false);
  const replaying = useRef(false);
  const remember = useCallback(() => {
    if (replaying.current || sameTick.current || !live.current) return;
    sameTick.current = true;
    window.setTimeout(() => {
      sameTick.current = false;
    }, 0);
    history.current.undo.push(live.current);
    if (history.current.undo.length > UNDO_DEPTH) history.current.undo.shift();
    history.current.redo = [];
  }, []);
  const writeShared = useCallback(
    async (next: AnnotationColumn[]): Promise<boolean> => {
      remember();
      const error = await saveShared(next);
      if (error) notifications.show({ color: 'red', message: error });
      return error === null;
    },
    [saveShared, remember],
  );
  const setSharedLabel = (cols: AnnotationColumn[], id: string, key: string, label: unknown) =>
    setLabel({ version: 2, columns: cols, activeColumnId: null }, id, key, label).columns;

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
  // The table whose labels reach the most collections comes first: it opens by
  // default, and a label on it is the one the charts can follow.
  const tables = useMemo(
    () =>
      allTables
        .filter((t) => t.eligible)
        .sort((a, b) => (b.link_targets ?? 0) - (a.link_targets ?? 0)),
    [allTables],
  );

  // ---- Reading one table ----------------------------------------------------
  // Held outside the panel (`annotationTableRead`): a reopening asks nothing.
  const readTable = useCallback(
    (dcId: string, force = false): Promise<Load> =>
      readAnnotationTable({
        dashboardId,
        dcId,
        pinned,
        entry: (collections ?? []).find((c) => c.dc_id === dcId),
        force,
      }),
    [dashboardId, collections, pinned],
  );

  // ---- Which table and key -------------------------------------------------
  // Labels belong to a table, so switching table loses nothing: each shows its own.
  const [choice, setChoice] = useState<AnnotationTarget | null>(null);
  const [load, setLoad] = useState<Load>({ kind: 'idle' });

  // Opens on the table of the compared labels, else the first metadata table.
  useEffect(() => {
    if (choice || tables.length === 0) return;
    const active = view?.columns.find((c) => c.id === view.activeColumnId);
    const anyCol = active ?? view?.columns[0];
    const entry = defaultAnnotationTable(tables, view?.columns, view?.activeColumnId);
    if (!entry) return;
    const keyColumn =
      anyCol && anyCol.dcId === entry.dc_id && entry.key_columns.includes(anyCol.keyColumn)
        ? anyCol.keyColumn
        : entry.key_columns[0];
    if (keyColumn) setChoice({ dcId: entry.dc_id, keyColumn });
  }, [tables, view, choice]);

  useEffect(() => {
    // A live read needs no version status; a past view reads it first.
    if (!choice || (pinned && !collections)) return;
    let cancelled = false;
    setLoad({ kind: 'loading' });
    void readTable(choice.dcId).then((l) => {
      if (!cancelled) setLoad(l);
    });
    return () => {
      cancelled = true;
    };
  }, [choice, collections, pinned, readTable]);

  const table = load.kind === 'ready' ? load.table : null;
  // The panel opens while the dashboard re-flows to make room for it, every
  // figure and tile resizing for that long. The grid mounts when that is done:
  // laid out against the width it keeps, and not competing with the re-flow.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(true), PANEL_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, []);
  const keyColumn = choice?.keyColumn ?? '';
  const chosenEntry = tables.find((t) => t.dc_id === choice?.dcId) ?? null;
  const keyOptions = chosenEntry?.key_columns ?? [];
  const onTableChange = (dcId: string) => {
    const entry = tables.find((t) => t.dc_id === dcId);
    if (!entry || !entry.key_columns[0]) return;
    // Back on a table: its labels' key if it has some, else the first link's.
    const own = view?.columns.find((c) => c.dcId === dcId);
    setChoice({ dcId, keyColumn: own?.keyColumn ?? entry.key_columns[0] });
  };

  // What is on screen: the labels of this table on this key. Edits apply to
  // the whole set (`ensureBound`), which keeps the labels of other tables.
  const bound: DashboardAnnotations | null =
    choice && keyColumn && view ? { ...view, columns: columnsFor(view, choice) } : null;
  const ensureBound = (): DashboardAnnotations | null =>
    choice && keyColumn ? (annotations ?? emptyAnnotations()) : null;

  // ---- Writing to the table: who, and unsaved cells -------------------------
  const writeBlocked: string | null = pinned
    ? 'This view shows a past version; a change to the table would not appear in it.'
    : !table
      ? 'The table is not loaded.'
      : !table.edit
        ? SOURCE_ELSEWHERE.has(cachedEditStatus(table.dcId)?.code ?? '')
          ? `${cachedEditStatus(table.dcId)?.reason ?? ''} Export gives you its rows with your labels added, to put in that source.`.trim()
          : cachedEditStatus(table.dcId)?.reason || 'You cannot change this table.'
        : null;
  const [cellEdits, setCellEdits] = useState<
    Map<string, { row: number; column: string; value: string | null }>
  >(new Map());
  useEffect(() => {
    setCellEdits(new Map());
    // Cells saved or another table read: the steps recorded against the old
    // rows no longer lead anywhere.
    history.current = { undo: [], redo: [] };
  }, [table]);
  live.current = { annotations, shared, cellEdits };
  const restore = (snap: Snapshot) => {
    replaying.current = true;
    setAnnotations(snap.annotations);
    if (snap.shared !== shared) void saveShared(snap.shared);
    setCellEdits(snap.cellEdits);
    window.setTimeout(() => {
      replaying.current = false;
    }, 0);
  };
  const step = (from: 'undo' | 'redo'): boolean => {
    const stack = history.current[from];
    const target = stack.pop();
    if (!target || !live.current) return false;
    history.current[from === 'undo' ? 'redo' : 'undo'].push(live.current);
    restore(target);
    return true;
  };

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
  const commit = useCallback(
    (next: DashboardAnnotations) => {
      remember();
      setAnnotations(next);
    },
    [setAnnotations, remember],
  );
  const gridApi = useRef<GridApi<GridRow> | null>(null);

  const setLabelCell = useCallback(
    (params: ValueSetterParams<GridRow>) => {
      const field = params.colDef.field ?? '';
      const base = ensureBound();
      if (!base || !field.startsWith(ANN_PREFIX)) return false;
      const id = field.slice(ANN_PREFIX.length);
      const label = String(params.newValue ?? '').slice(0, MAX_LABEL_LENGTH);
      if (isShared(id)) {
        if (canShare) void writeShared(setSharedLabel(shared, id, params.data.__key, label));
      } else {
        commit(setLabel(base, id, params.data.__key, label));
      }
      // The row is rebuilt from the labels, which are the source of truth.
      return false;
    },
    // ensureBound reads bound and choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bound, choice, keyColumn, commit, shared, canShare, isShared, writeShared],
  );

  // One edit of one table cell, kept aside until Save: typed in the grid or
  // pasted from a spreadsheet.
  const applyTableCell = useCallback(
    (index: number, column: string, raw: unknown) => {
      if (!table?.edit) return;
      const original = table.rows[index]?.[column];
      const value = raw === null || raw === undefined || String(raw).trim() === '' ? null : String(raw);
      remember();
      setCellEdits((prev) => {
        const next = new Map(prev);
        const same = (original ?? null) === null ? value === null : String(original) === value;
        if (same) next.delete(cellKey(index, column));
        else next.set(cellKey(index, column), { row: index, column, value });
        return next;
      });
    },
    [table, remember],
  );
  const setTableCell = useCallback(
    (params: ValueSetterParams<GridRow>) => {
      const index = params.data.__row;
      if (index !== null) applyTableCell(index, params.colDef.field ?? '', params.newValue);
      return false;
    },
    [applyTableCell],
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
    const others = (view?.columns ?? []).filter((c) => c.id !== naming.id);
    if (name.length > MAX_LABEL_LENGTH) {
      setNaming({ ...naming, error: `At most ${MAX_LABEL_LENGTH} characters.` });
      return;
    }
    if (others.some((c) => c.name === name) || name === keyColumn || contextColumns.includes(name)) {
      setNaming({
        ...naming,
        error: others.some((c) => c.name === name && c.dcId !== choice?.dcId)
          ? `"${name}" already names labels of another table.`
          : `"${name}" is already a column here.`,
      });
      return;
    }
    if (naming.id && isShared(naming.id)) {
      void writeShared(shared.map((c) => (c.id === naming.id ? { ...c, name } : c)));
    } else if (naming.id) {
      commit({ ...base, columns: base.columns.map((c) => (c.id === naming.id ? { ...c, name } : c)) });
    } else {
      const column = { id: newAnnotationId(), name, dcId: choice!.dcId, keyColumn, values: {} };
      commit({ ...base, columns: [...base.columns, column] });
    }
    setNaming(null);
  };

  const keepOnAccount = (id: string) => {
    const base = ensureBound();
    if (!base) return;
    commit({
      ...base,
      columns: base.columns.map((c) => {
        if (c.id !== id) return c;
        const { local: _local, ...shared } = c;
        return shared;
      }),
    });
  };
  const removeLabelColumn = (id: string) => {
    const base = ensureBound();
    if (!base) return;
    if (isShared(id)) {
      void writeShared(shared.filter((c) => c.id !== id));
      if (base.activeColumnId === id) commit({ ...base, activeColumnId: null });
      return;
    }
    commit({
      ...base,
      columns: base.columns.filter((c) => c.id !== id),
      activeColumnId: base.activeColumnId === id ? null : base.activeColumnId,
    });
  };
  const toggleCompare = (id: string) => {
    const base = ensureBound();
    if (!base) return;
    commit({ ...base, activeColumnId: base.activeColumnId === id ? null : id });
  };

  // ---- Sharing on the dashboard --------------------------------------------------
  // Asked first: who will see it, and that it is read-only for them.
  const [confirm, setConfirm] = useState<{
    title: string;
    body: string;
    action: string;
    color?: string;
    run: () => void;
  } | null>(null);
  const shareColumn = (id: string) => {
    const base = ensureBound();
    const column = base?.columns.find((c) => c.id === id);
    if (!base || !column) return;
    setConfirm({
      title: `Share "${column.name}" on this dashboard`,
      body: 'Everyone who can open this dashboard will see these labels and can compare by them. They cannot change them; you and the other editors can.',
      action: 'Share',
      run: () => {
        const { local: _local, shared: _shared, ...plain } = column;
        void writeShared([...shared, plain]).then((ok) => {
          if (ok) commit({ ...base, columns: base.columns.filter((c) => c.id !== id) });
        });
      },
    });
  };
  const stopSharing = (id: string) => {
    const base = ensureBound();
    const column = shared.find((c) => c.id === id);
    if (!base || !column) return;
    setConfirm({
      title: `Stop sharing "${column.name}"`,
      body: 'It becomes one of your own labels again. The other readers of this dashboard no longer see it.',
      action: 'Stop sharing',
      run: () => {
        void writeShared(shared.filter((c) => c.id !== id)).then((ok) => {
          if (!ok) return;
          const { shared: _shared, ...plain } = column;
          commit({ ...base, columns: [...base.columns, plain] });
        });
      },
    });
  };
  const copyToMine = (id: string) => {
    const base = ensureBound();
    const column = shared.find((c) => c.id === id);
    if (!base || !column) return;
    if ((view?.columns.length ?? 0) >= MAX_ANNOTATION_COLUMNS) {
      notifications.show({ color: 'orange', message: `At most ${MAX_ANNOTATION_COLUMNS} label columns.` });
      return;
    }
    const name = copyName(column.name, (view?.columns ?? []).map((c) => c.name));
    const copy = {
      id: newAnnotationId(),
      name,
      dcId: column.dcId,
      keyColumn: column.keyColumn,
      values: { ...column.values },
    };
    commit({ ...base, columns: [...base.columns, copy] });
    notifications.show({ color: 'teal', message: `"${name}" is one of your labels now.` });
  };
  const askDelete = (id: string) => {
    if (!isShared(id)) {
      removeLabelColumn(id);
      return;
    }
    const column = shared.find((c) => c.id === id);
    setConfirm({
      title: `Delete "${column?.name ?? 'labels'}"`,
      body: 'It is shared on this dashboard: deleting it removes it for everyone. A past version of the dashboard still holds it.',
      action: 'Delete for everyone',
      color: 'red',
      run: () => removeLabelColumn(id),
    });
  };

  // ---- Export as metadata sheet ---------------------------------------------------
  // Built here from the rows on screen and downloaded: no request carries it.
  const [exporting, setExporting] = useState<Set<string> | null>(null);
  const exportSheet = (selected: Set<string> | null = exporting) => {
    if (!table || !keyColumn || !selected || !chosenEntry) return;
    const labels = (bound?.columns ?? []).filter((c) => selected.has(c.id));
    // Cells changed in the grid but not yet saved to the table are in the file.
    const rows = cellEdits.size
      ? table.rows.map((row, i) => {
          let out = row;
          for (const e of cellEdits.values()) {
            if (e.row === i) out = { ...out, [e.column]: e.value };
          }
          return out;
        })
      : table.rows;
    const text = buildMetadataSheet(table.columns, rows, keyColumn, labels);
    const url = URL.createObjectURL(new Blob([text], { type: 'text/tab-separated-values' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = metadataSheetName(chosenEntry.tag || 'metadata');
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExporting(null);
  };
  // With no label column there is nothing to choose: the table goes out as it is.
  const startExport = () => {
    const ids = new Set((bound?.columns ?? []).map((c) => c.id));
    if (ids.size === 0) exportSheet(ids);
    else setExporting(ids);
  };

  // ---- Cell ranges, copy, paste, fill -----------------------------------------
  // AG Grid Community has neither a cell range nor a clipboard, so both are
  // done here: a range is two corners in display coordinates (row index,
  // column index), drawn by a class on the cells it covers.
  const [range, setRange] = useState<{ anchor: CellPos; head: CellPos } | null>(null);
  const rangeRef = useRef(range);
  rangeRef.current = range;
  const rangeDragging = useRef(false);
  useEffect(() => {
    const up = (e: MouseEvent) => {
      if (!rangeDragging.current) return;
      rangeDragging.current = false;
      // A quick drag can end on a cell the pointer never reported moving over:
      // the range ends on the cell the button is released on.
      const cell = (document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null)?.closest(
        '.ag-cell',
      );
      const rowIndex = Number(cell?.closest('.ag-row')?.getAttribute('row-index'));
      const col = cell ? (gridApi.current?.getAllDisplayedColumns() ?? []).findIndex((c) => c.getColId() === cell.getAttribute('col-id')) : -1;
      if (!cell || Number.isNaN(rowIndex) || col < 0) return;
      setRange((r) => (r && (r.head.row !== rowIndex || r.head.col !== col) ? { ...r, head: { row: rowIndex, col } } : r));
    };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  }, []);
  const displayedIds = () => gridApi.current?.getAllDisplayedColumns().map((c) => c.getColId()) ?? [];
  const boxOf = (r: { anchor: CellPos; head: CellPos } | null) =>
    r
      ? {
          r0: Math.min(r.anchor.row, r.head.row),
          r1: Math.max(r.anchor.row, r.head.row),
          c0: Math.min(r.anchor.col, r.head.col),
          c1: Math.max(r.anchor.col, r.head.col),
        }
      : null;
  const isInRange = useCallback((rowIndex: number | null, colId: string): boolean => {
    const box = boxOf(rangeRef.current);
    if (!box || rowIndex === null) return false;
    if (box.r0 === box.r1 && box.c0 === box.c1) return false; // one cell is just the focus
    const col = (gridApi.current?.getAllDisplayedColumns() ?? []).findIndex((c) => c.getColId() === colId);
    return rowIndex >= box.r0 && rowIndex <= box.r1 && col >= box.c0 && col <= box.c1;
  }, []);
  const rangeRules = useMemo(
    () => ({
      'dc-range-cell': (p: { node: { rowIndex: number | null }; column: { getColId: () => string } }) =>
        isInRange(p.node.rowIndex, p.column.getColId()),
    }),
    [isInRange],
  );
  // Repaint the cells when the range moves: class rules are read on refresh.
  useEffect(() => {
    gridApi.current?.refreshCells({ force: true, suppressFlash: true });
  }, [range]);

  const takesValue = (colId: string) =>
    colId.startsWith(ANN_PREFIX) || Boolean(!pinned && table?.edit?.editable.has(colId));

  // Every write, whatever started it (paste, fill, Delete): label columns and
  // the table's editable columns, shared labels only when this reader may.
  const applyWrites = (writes: { row: GridRow; colId: string; value: string }[]) => {
    const base = ensureBound();
    let next = base;
    let nextShared = shared;
    let readOnly = 0;
    for (const { row, colId, value } of writes) {
      if (!colId.startsWith(ANN_PREFIX)) {
        if (row.__row !== null && row.__row !== undefined) applyTableCell(row.__row, colId, value);
        continue;
      }
      if (!next) continue;
      const id = colId.slice(ANN_PREFIX.length);
      const label = value.slice(0, MAX_LABEL_LENGTH);
      if (isShared(id)) {
        if (canShare) nextShared = setSharedLabel(nextShared, id, row.__key, label);
        else readOnly += 1;
        continue;
      }
      next = setLabel(next, id, row.__key, label);
    }
    if (next && next !== base) commit(next);
    if (nextShared !== shared) void writeShared(nextShared);
    if (readOnly > 0) {
      notifications.show({
        color: 'orange',
        message: `${readOnly} value${readOnly === 1 ? '' : 's'} fell on shared labels, which are read-only, and were left out.`,
      });
    }
  };
  const rowAt = (index: number) => gridApi.current?.getDisplayedRowAtIndex(index)?.data as GridRow | undefined;
  const cellText = (row: GridRow | undefined, colId: string) => {
    const v = row?.[colId];
    return v === null || v === undefined ? '' : String(v);
  };

  // Copy: the selected range as a tab-separated block (what a spreadsheet
  // pastes), else the focused cell, or the text of an open editor when nothing
  // in it is selected (a click opens the editor without selecting its text).
  const onCopy = (e: ClipboardEvent) => {
    const api = gridApi.current;
    if (!api) return;
    const active = document.activeElement;
    if (api.getEditingCells().length > 0) {
      if (!(active instanceof HTMLInputElement) && !(active instanceof HTMLTextAreaElement)) return;
      if (active.selectionStart !== active.selectionEnd) return; // the editor copies its selection
      e.clipboardData?.setData('text/plain', active.value);
      e.preventDefault();
      return;
    }
    const box = boxOf(rangeRef.current);
    if (box && (box.r1 > box.r0 || box.c1 > box.c0)) {
      const ids = displayedIds();
      const lines: string[] = [];
      for (let r = box.r0; r <= box.r1; r += 1) {
        const row = rowAt(r);
        lines.push(ids.slice(box.c0, box.c1 + 1).map((id) => cellText(row, id)).join('\t'));
      }
      e.clipboardData?.setData('text/plain', lines.join('\n'));
      e.preventDefault();
      return;
    }
    const focused = api.getFocusedCell();
    if (!focused) return;
    e.clipboardData?.setData('text/plain', cellText(rowAt(focused.rowIndex), focused.column.getColId()));
    e.preventDefault();
  };

  // Paste: one value goes into every selected cell; a block is written from the
  // range's first cell (or the focused one) down and to the right, across the
  // columns that take a value.
  const onPaste = (e: ClipboardEvent) => {
    const api = gridApi.current;
    if (!api) return;
    const ids = displayedIds();
    const box = boxOf(rangeRef.current);
    const focused = api.getFocusedCell();
    const startRow = box ? box.r0 : focused?.rowIndex;
    const startCol = box ? ids[box.c0] : focused?.column.getColId();
    if (startRow === undefined || !startCol || !takesValue(startCol)) return;
    const text = e.clipboardData?.getData('text/plain') ?? '';
    // A single value typed into an open editor is the editor's business.
    const editing = api.getEditingCells().length > 0;
    if (editing && !/[\t\n]/.test(text)) return;
    e.preventDefault();
    if (editing) api.stopEditing(true);
    const block = parsePastedBlock(text);
    const writes: { row: GridRow; colId: string; value: string }[] = [];
    let skipped = 0;
    if (box && (box.r1 > box.r0 || box.c1 > box.c0) && block.length === 1 && block[0].length === 1) {
      for (let r = box.r0; r <= box.r1; r += 1) {
        const row = rowAt(r);
        if (!row) continue;
        for (let c = box.c0; c <= box.c1; c += 1) {
          if (takesValue(ids[c])) writes.push({ row, colId: ids[c], value: block[0][0] });
        }
      }
    } else {
      const cols = ids.filter(takesValue);
      const firstCol = cols.indexOf(startCol);
      block.forEach((cells, i) => {
        const row = rowAt(startRow + i);
        if (!row) {
          skipped += 1;
          return;
        }
        cells.forEach((cell, j) => {
          const colId = cols[firstCol + j];
          if (colId) writes.push({ row, colId, value: cell });
        });
      });
    }
    applyWrites(writes);
    if (skipped > 0) {
      notifications.show({
        color: 'orange',
        message: `${skipped} pasted row${skipped === 1 ? '' : 's'} went past the last row and were left out.`,
      });
    }
  };

  // Delete / Backspace empties the selected cells (or the focused one).
  const onKeyDown = (e: React.KeyboardEvent) => {
    const api = gridApi.current;
    if (!api) return;
    if (e.key === 'Escape' && rangeRef.current && api.getEditingCells().length === 0) {
      setRange(null);
      return;
    }
    // Cmd/Ctrl+Z steps back, with Shift (or Ctrl+Y) forward. An open editor
    // keeps its own undo for the text being typed.
    if ((e.metaKey || e.ctrlKey) && !e.altKey && ['z', 'y'].includes(e.key.toLowerCase())) {
      if (api.getEditingCells().length > 0) return;
      if ((e.target as HTMLElement).closest('input, textarea, [contenteditable="true"]')) return;
      const forward = e.key.toLowerCase() === 'y' || e.shiftKey;
      if (step(forward ? 'redo' : 'undo')) e.preventDefault();
      return;
    }
    if (e.key !== 'Delete' && e.key !== 'Backspace') return;
    if (api.getEditingCells().length > 0) return;
    if ((e.target as HTMLElement).closest('input, textarea, [contenteditable="true"]')) return;
    const ids = displayedIds();
    const box = boxOf(rangeRef.current);
    const focused = api.getFocusedCell();
    const r0 = box ? box.r0 : focused?.rowIndex;
    const r1 = box ? box.r1 : focused?.rowIndex;
    const c0 = box ? box.c0 : focused ? ids.indexOf(focused.column.getColId()) : -1;
    const c1 = box ? box.c1 : c0;
    if (r0 === undefined || r1 === undefined || c0 < 0) return;
    const writes: { row: GridRow; colId: string; value: string }[] = [];
    for (let r = r0; r <= r1; r += 1) {
      const row = rowAt(r);
      if (!row) continue;
      for (let c = c0; c <= c1; c += 1) {
        if (takesValue(ids[c]) && cellText(row, ids[c]) !== '') writes.push({ row, colId: ids[c], value: '' });
      }
    }
    if (writes.length === 0) return;
    e.preventDefault();
    applyWrites(writes);
  };

  // Copy and paste are the document's events, not the grid's: with no text
  // selected (cells are not selectable) the browser sends them to the page's
  // body or to whatever holds the selection, never to the focused cell, so a
  // handler on the grid's box was never called. They are taken here, and only
  // while the focus is inside the grid.
  const gridBoxRef = useRef<HTMLDivElement | null>(null);
  const clipboardRef = useRef({ onCopy, onPaste });
  clipboardRef.current = { onCopy, onPaste };
  useEffect(() => {
    const inGrid = () => {
      const active = document.activeElement;
      return Boolean(active && gridBoxRef.current?.contains(active));
    };
    const copy = (e: ClipboardEvent) => inGrid() && clipboardRef.current.onCopy(e);
    const paste = (e: ClipboardEvent) => inGrid() && clipboardRef.current.onPaste(e);
    document.addEventListener('copy', copy);
    document.addEventListener('paste', paste);
    return () => {
      document.removeEventListener('copy', copy);
      document.removeEventListener('paste', paste);
    };
  }, []);

  // The grid's mouse: a press starts a range, moving over cells with the button
  // down stretches it, Shift extends the last one. The fill handle and an open
  // editor keep their own mouse.
  const posOf = (e: { node: { rowIndex: number | null }; column: { getColId: () => string } }): CellPos | null => {
    const col = displayedIds().indexOf(e.column.getColId());
    return e.node.rowIndex === null || col < 0 ? null : { row: e.node.rowIndex, col };
  };
  const onCellMouseDown = (e: CellMouseDownEvent<GridRow>) => {
    const ev = e.event as MouseEvent | null | undefined;
    if (!ev || ev.button !== 0) return;
    if ((ev.target as HTMLElement | null)?.closest('.dc-fill-handle')) return;
    if (gridApi.current?.getEditingCells().length) return;
    const pos = posOf(e);
    if (!pos) return;
    const focused = gridApi.current?.getFocusedCell();
    const focusPos = focused ? posOf({ node: { rowIndex: focused.rowIndex }, column: focused.column }) : null;
    const anchor = ev.shiftKey ? (rangeRef.current?.anchor ?? focusPos ?? pos) : pos;
    setRange({ anchor, head: pos });
    rangeDragging.current = true;
  };
  const onCellMouseOver = (e: CellMouseOverEvent<GridRow>) => {
    if (!rangeDragging.current) return;
    const pos = posOf(e);
    if (!pos) return;
    setRange((r) => (r && (r.head.row !== pos.row || r.head.col !== pos.col) ? { ...r, head: pos } : r));
  };

  // A new label column or another table: fit the columns again. Left alone
  // otherwise, so a width the reader dragged is not undone by an edit.
  const fitKey = `${bound?.columns.length ?? 0}|${table?.dcId ?? ''}`;
  useEffect(() => {
    const id = setTimeout(() => gridApi.current?.autoSizeAllColumns(), 60);
    return () => clearTimeout(id);
  }, [fitKey]);

  // ---- Fill ---------------------------------------------------------------------
  // The fill handle's drop: the value of the cell it started on goes into every
  // row it crossed, the label columns and the editable table columns alike.
  const fillRange = (colId: string, from: number, to: number) => {
    const source = rowAt(from);
    if (!source) return;
    const value = cellText(source, colId);
    const [lo, hi] = from < to ? [from + 1, to] : [to, from - 1];
    const writes: { row: GridRow; colId: string; value: string }[] = [];
    for (let i = lo; i <= hi; i += 1) {
      const row = rowAt(i);
      if (row) writes.push({ row, colId, value });
    }
    applyWrites(writes);
  };
  // The grid's column definitions are memoised; they call the latest closure.
  const fillRef = useRef(fillRange);
  fillRef.current = fillRange;
  const fillParams = useMemo(
    () => ({ onFill: (c: string, f: number, t: number) => fillRef.current(c, f, t) }),
    [],
  );

  // ---- Real writes: cells, a label column, a file -----------------------------
  const reloadTable = async () => {
    if (!choice) return;
    forgetAnnotationTable(choice.dcId);
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
      mode: 'error' in match || !choice ? 'add_columns' : suggestedMergeMode(base, choice, match),
      tableReport: null,
      tableBusy: false,
      tableApplying: false,
      tableError: null,
    });
  };
  const labelsPlan = useMemo(() => {
    const base = ensureBound();
    return importing && base && choice && !('error' in importing.match)
      ? planAnnotationMerge(base, choice, importing.match, importing.mode)
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
        const kind: LabelColumnKind = c.shared
          ? canShare
            ? 'shared'
            : 'shared-readonly'
          : c.local
            ? 'local'
            : 'mine';
        const actions: LabelColumnActions = {
          name: c.name,
          kind,
          active: c.id === bound?.activeColumnId,
          compareBlocked: budget.ok ? null : budget.reason,
          canKeepOnAccount: Boolean(c.local) && state.storage === 'account',
          canShare,
          saveBlocked: writeBlocked,
          onCompare: () => toggleCompare(c.id),
          onRename: () => setNaming({ id: c.id, value: c.name, error: null }),
          onKeepOnAccount: () => keepOnAccount(c.id),
          onShare: () => shareColumn(c.id),
          onStopSharing: () => stopSharing(c.id),
          onCopy: () => copyToMine(c.id),
          onSaveToTable: () => void startSave(c.id),
          onDelete: () => askDelete(c.id),
        };
        return {
          field: ANN_PREFIX + c.id,
          headerName: c.name,
          headerComponent: LabelColumnHeader,
          headerComponentParams: { actions },
          editable: kind !== 'shared-readonly',
          headerClass: 'dc-label-head',
          cellClassRules: rangeRules,
          cellRenderer: kind === 'shared-readonly' ? undefined : FillCell,
          cellRendererParams: fillParams,
          cellClass: ['dc-label-cell', ...(kind === 'shared-readonly' ? ['dc-label-cell-readonly'] : [])],
          valueSetter: setLabelCell,
          sortable: false,
          minWidth: 150,
        };
      });
      const canEditCells = Boolean(table?.edit) && !pinned;
      return [
        // Not pinned: AG Grid lays its horizontal scrollbar under the scrolling
        // columns only, so a pinned key made the bar start after it.
        {
          field: KEY_FIELD,
          headerName: keyColumn || 'key',
          editable: false,
          minWidth: 140,
          cellClassRules: rangeRules,
        },
        ...labelCols,
        ...contextColumns.map<ColDef<GridRow>>((c) => {
          const editable = canEditCells && Boolean(table?.edit?.editable.has(c));
          return {
            field: c,
            headerName: c,
            editable,
            valueSetter: editable ? setTableCell : undefined,
            cellRenderer: editable ? FillCell : undefined,
            cellRendererParams: editable ? fillParams : undefined,
            maxWidth: 380,
            headerTooltip: editable ? 'Double-click a cell to change the table' : undefined,
            cellClassRules: {
              ...rangeRules,
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
      canShare,
      shared,
    ],
  );

  // ---- Render ---------------------------------------------------------------------
  const storageNote =
    state.storage === 'browser'
      ? state.browserUnavailable
        ? 'This browser keeps nothing: your labels last until you leave the page.'
        : 'Labels are kept in this browser. Sign in to keep them on your account.'
      : null;
  const activeLocal = view?.columns.some((c) => c.local && c.id === view.activeColumnId);
  const otherTables = allTables.filter((t) => !t.eligible);

  if (collectionsError) {
    return (
      <Alert color="red" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
        {collectionsError}
      </Alert>
    );
  }
  if (!collections) return <Loader size="sm" />;
  if (tables.length === 0) {
    return (
      <Text size="sm" data-testid="annotation-no-table">
        This project has no metadata table linked to the data, so there is nothing to label.
      </Text>
    );
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

      <Group justify="space-between" gap="xs" wrap="wrap">
        <Group gap="xs" wrap="wrap" style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed">
            Table
          </Text>
          {tables.length > 1 ? (
            <Select
              size="xs"
              w={190}
              aria-label="Table to label"
              leftSection={<Icon icon="mdi:table" width={14} />}
              data={tables.map((t) => ({
                value: t.dc_id,
                label: annotationTableLabel(t, tables),
              }))}
              value={choice?.dcId ?? null}
              onChange={(v) => v && onTableChange(v)}
              allowDeselect={false}
              comboboxProps={{ withinPortal: true, zIndex: Z_LAYERS.nestedOverlay }}
              classNames={{ input: 'dc-mp-select' }}
              data-testid="annotation-table-select"
            />
          ) : (
            <Text size="sm" fw={500} truncate data-testid="annotation-context">
              {chosenEntry ? annotationTableLabel(chosenEntry, tables) : ''}
            </Text>
          )}
          {keyOptions.length > 1 ? (
            <Select
              size="xs"
              w={160}
              aria-label="Key column"
              data={keyOptions}
              value={keyColumn || null}
              onChange={(v) => v && choice && setChoice({ dcId: choice.dcId, keyColumn: v })}
              allowDeselect={false}
              data-testid="annotation-key-select"
            />
          ) : (
            <Tooltip withinPortal label="Labels are keyed on this column, the one the table links by">
              <Text size="xs" c="dimmed" truncate data-testid="annotation-key">
                key: {keyColumn}
              </Text>
            </Tooltip>
          )}
          {projectId && choice && (
            // The table's own page: its rows, its links and where it comes from.
            <Button
              component="a"
              href={`/projects/${projectId}?table=${choice.dcId}`}
              target="_blank"
              rel="noopener noreferrer"
              size="xs"
              variant="light"
              color="gray"
              style={{ flexShrink: 0 }}
              leftSection={<Icon icon="mdi:open-in-new" width={14} />}
              data-testid="annotation-open-table"
            >
              Open in project
            </Button>
          )}
          {otherTables.length > 0 && (
            <Popover withinPortal width={340} position="bottom-start" shadow="md" zIndex={Z_LAYERS.nestedOverlay}>
              <Popover.Target>
                <Button
                  size="xs"
                  variant="subtle"
                  color="gray"
                  style={{ flexShrink: 0 }}
                  rightSection={<Icon icon="mdi:chevron-down" width={14} />}
                  data-testid="annotation-other-tables"
                >
                  {otherTables.length} other table{otherTables.length === 1 ? '' : 's'}
                </Button>
              </Popover.Target>
              <Popover.Dropdown>
                <Stack gap={8}>
                  <Text size="xs" c="dimmed">
                    Other tables of the project. Only a metadata table linked to the data can carry labels.
                  </Text>
                  {otherTables.map((t) => (
                    <Box key={t.dc_id}>
                      <Group gap={4} wrap="nowrap">
                        <Text size="sm" fw={600} truncate style={{ flex: 1, minWidth: 0 }}>
                          {annotationTableLabel(t, allTables)}
                        </Text>
                        {projectId && (
                          <Anchor
                            size="xs"
                            href={`/projects/${projectId}?table=${t.dc_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Open in project
                          </Anchor>
                        )}
                      </Group>
                      <Text size="xs" c="dimmed">
                        {t.reason}
                      </Text>
                    </Box>
                  ))}
                </Stack>
              </Popover.Dropdown>
            </Popover>
          )}
        </Group>
        <Group gap={4} wrap="nowrap">
        <Tooltip
          withinPortal
          label={
            labelColumnCount >= MAX_ANNOTATION_COLUMNS
              ? `At most ${MAX_ANNOTATION_COLUMNS} label columns`
              : 'A new column of your own labels, next to the table'
          }
        >
          <Button
            size="xs"
            className="dc-mp-btn dc-mp-btn--primary"
            disabled={!table || !keyColumn || labelColumnCount >= MAX_ANNOTATION_COLUMNS}
            leftSection={<Icon icon="mdi:plus" width={14} />}
            onClick={() => setNaming({ id: null, value: '', error: null })}
            data-testid="label-add"
          >
            Add column
          </Button>
        </Tooltip>
        <Tooltip withinPortal label="Fit every column to its content">
          <Button
            size="xs"
            className="dc-mp-btn"
            disabled={!table}
            leftSection={<Icon icon="mdi:arrow-expand-horizontal" width={14} />}
            onClick={() => gridApi.current?.autoSizeAllColumns()}
            data-testid="annotation-fit-columns"
          >
            Fit
          </Button>
        </Tooltip>
        <Tooltip
          withinPortal
          multiline
          w={300}
          label={
            writeBlocked && SOURCE_ELSEWHERE.has(cachedEditStatus(table?.dcId ?? '')?.code ?? '')
              ? "This table's rows with your label columns added, as a TSV. Add the columns to the sheet this table comes from (for a pipeline, its metadata sheet) and ingest it again: the pipeline's statistics will include them."
              : "This table's rows with label columns added, as a TSV built in your browser."
          }
        >
          <Button
            size="xs"
            className="dc-mp-btn"
            disabled={!table || !keyColumn}
            leftSection={<Icon icon="mdi:tray-arrow-down" width={14} />}
            onClick={startExport}
            data-testid="annotation-export"
          >
            Export
          </Button>
        </Tooltip>
        <FileButton
          onChange={(f) => f && void openImport(f)}
          accept=".csv,.tsv,.txt,.tab,text/csv,text/tab-separated-values"
          inputProps={{ 'data-testid': 'annotation-file-input' } as React.ComponentProps<'input'>}
        >
          {(props) => (
            <Button
              {...props}
              size="xs"
              className="dc-mp-btn"
              disabled={!table || !keyColumn}
              leftSection={<Icon icon="mdi:tray-arrow-up" width={14} />}
            >
              Import
            </Button>
          )}
        </FileButton>
        </Group>
      </Group>

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

      {(load.kind === 'loading' || (table && !settled)) && <Loader size="sm" />}
      {load.kind === 'refused' && (
        <Alert color="orange" data-testid="annotation-refused">
          {load.message}
        </Alert>
      )}
      {table && keyColumn && settled && (
        <>
          {labelColumnCount === 0 ? (
            <Paper
              withBorder
              p="sm"
              radius="md"
              className="dc-mp-empty"
              data-testid="annotation-empty-state"
            >
              <Group gap="sm" wrap="nowrap" align="flex-start">
                <Icon
                  icon="mdi:file-upload-outline"
                  width={24}
                  className="dc-mp-empty-icon"
                  style={{ flexShrink: 0 }}
                />
                <Stack gap={2}>
                  <Text size="sm" fw={600}>
                    Drop a CSV or TSV here to import labels
                  </Text>
                  <Text size="xs" c="dimmed">
                    One row per {keyColumn}. You see the result before anything is applied. Or use{' '}
                    <b>Add column</b> to type labels in the grid, or paste a block from a spreadsheet
                    onto a label cell. <b>Export</b> downloads the table, with your edits, at any time.
                  </Text>
                </Stack>
              </Group>
            </Paper>
          ) : (
            <Text size="xs" c="dimmed" data-testid="annotation-grid-hint">
              Double-click a cell to edit it. Teal columns are your labels: press the chart icon in their
              header to colour or split the charts by them. Drop a CSV or TSV anywhere to import it.
            </Text>
          )}
          <Box
            ref={gridBoxRef}
            onKeyDown={onKeyDown}
            className={scheme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
            // A short table takes the height of its rows, so the horizontal
            // scrollbar sits right under the last one; a long one fills the
            // panel and scrolls inside it (autoHeight would draw every row).
            style={
              rows.length <= FIT_ROWS_MAX
                ? { width: '100%' }
                : { height: 'calc(100vh - 260px)', minHeight: 300, width: '100%' }
            }
            data-testid="annotation-grid"
          >
            <AgGridReact<GridRow>
              rowData={rows}
              domLayout={rows.length <= FIT_ROWS_MAX ? 'autoHeight' : 'normal'}
              columnDefs={colDefs}
              defaultColDef={{ sortable: true, filter: true, resizable: true }}
              getRowId={(p) => p.data.__key}
              onGridReady={(e) => {
                gridApi.current = e.api;
              }}
              // Columns open at their content's width, so a path or a long
              // label is read rather than cut at a default 200 px.
              onFirstDataRendered={(e) => e.api.autoSizeAllColumns()}
              onCellMouseDown={onCellMouseDown}
              onCellMouseOver={onCellMouseOver}
              // A click only focuses (copy, paste and the fill handle work from
              // there); a double click, Enter or F2 opens the editor.
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
            missingKeys > 0 && (
              <Text size="xs" c="dimmed">
                {`${missingKeys} labelled row${missingKeys === 1 ? ' is' : 's are'} no longer in the table; kept, not shown.`}
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
        opened={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm?.title ?? ''}
        size="sm"
        zIndex={Z_LAYERS.nestedOverlay}
      >
        <Stack gap="sm" data-testid="annotation-confirm">
          <Text size="sm">{confirm?.body}</Text>
          <Group justify="flex-end" gap="xs">
            <Button size="xs" variant="default" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              size="xs"
              color={confirm?.color}
              onClick={() => {
                confirm?.run();
                setConfirm(null);
              }}
              data-testid="annotation-confirm-apply"
            >
              {confirm?.action}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={exporting !== null}
        onClose={() => setExporting(null)}
        title="Export as metadata sheet"
        size="sm"
        zIndex={Z_LAYERS.nestedOverlay}
      >
        <Stack gap="sm" data-testid="annotation-export-modal">
          <Text size="sm">
            Every row of {chosenEntry ? annotationTableLabel(chosenEntry, tables) : 'this table'}, with
            these label columns added. The file is built in your browser.
            {cellEdits.size > 0 &&
              ` It includes your ${cellEdits.size} unsaved change${cellEdits.size === 1 ? '' : 's'} to the table.`}
          </Text>
          <Stack gap={6}>
            {(bound?.columns ?? []).map((c) => (
              <Checkbox
                key={c.id}
                size="xs"
                checked={exporting?.has(c.id) ?? false}
                onChange={(e) => {
                  if (!exporting) return;
                  const next = new Set(exporting);
                  if (e.currentTarget.checked) next.add(c.id);
                  else next.delete(c.id);
                  setExporting(next);
                }}
                label={
                  <Group gap={6} wrap="nowrap">
                    <Icon
                      icon={LABEL_KIND[c.shared ? 'shared' : c.local ? 'local' : 'mine'].icon}
                      width={14}
                      style={{ color: 'var(--mantine-color-dimmed)' }}
                    />
                    <Text size="sm">{c.name}</Text>
                  </Group>
                }
              />
            ))}
          </Stack>
          <Group justify="flex-end" gap="xs">
            <Button size="xs" variant="default" onClick={() => setExporting(null)}>
              Cancel
            </Button>
            <Button
              size="xs"
              disabled={!exporting || exporting.size === 0}
              onClick={() => exportSheet()}
              leftSection={<Icon icon="mdi:tray-arrow-down" width={14} />}
              data-testid="annotation-export-apply"
            >
              Download TSV
            </Button>
          </Group>
        </Stack>
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
