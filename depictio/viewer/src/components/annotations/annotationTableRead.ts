import {
  fetchDataCollectionPreview,
  fetchTableEditStatus,
  fetchTableForEdit,
  MAX_ANNOTATION_ROWS,
} from 'depictio-react-core';
import type { AnnotationTable, DataVersionCollectionStatus, TableEditStatus } from 'depictio-react-core';

/**
 * Reading a metadata table for the Metadata panel, kept outside the panel.
 *
 * The panel unmounts when it closes, and its reads lived in it: every opening
 * asked the server again, one request after another (who may write, then the
 * rows), and the grid stayed empty until the last answered, in the same moments
 * the dashboard re-flowed to make room. Held here, a reopening costs no request,
 * and the first table can be read before the panel is opened
 * (`warmAnnotationTable`).
 */

export interface TableRead {
  dcId: string;
  columns: string[];
  rows: Record<string, unknown>[];
  /** Delta version read; null for the current table read through the preview. */
  version: number | null;
  /** Set when the reader may write to this table: the version the cells were
   *  read at and the columns that can be edited. */
  edit: { deltaVersion: number; editable: Set<string> } | null;
}

export type Load =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; table: TableRead }
  | { kind: 'refused'; message: string };

/** How long a read is trusted. A write through the panel forgets it at once; a
 *  change made elsewhere (an ingest, another editor) shows up after this. A
 *  stale edit still cannot overwrite: a save names the version it read. */
const TTL_MS = 60_000;

interface Stamped<T> {
  value: T;
  at: number;
}
const loads = new Map<string, Stamped<Load>>();
const statuses = new Map<string, Stamped<TableEditStatus | null>>();
/** Reads in flight, so a warm-up and the panel opening on it share one request. */
const inflight = new Map<string, Promise<Load>>();

const fresh = <T>(entry: Stamped<T> | undefined): entry is Stamped<T> =>
  entry !== undefined && Date.now() - entry.at < TTL_MS;

const loadKey = (dashboardId: string, dcId: string, version: number | null) =>
  `${dashboardId}|${dcId}|${version ?? 'live'}`;

/** Who may write to the table, as last read (sync, for the banner). */
export function cachedEditStatus(dcId: string): TableEditStatus | null {
  return statuses.get(dcId)?.value ?? null;
}

async function editStatusOf(dcId: string): Promise<TableEditStatus | null> {
  const hit = statuses.get(dcId);
  if (fresh(hit)) return hit.value;
  const value = await fetchTableEditStatus(dcId).catch(() => null);
  statuses.set(dcId, { value, at: Date.now() });
  return value;
}

/** Drops what is held of one table: after a write to it. */
export function forgetAnnotationTable(dcId: string): void {
  statuses.delete(dcId);
  for (const key of [...loads.keys()]) {
    if (key.split('|')[1] === dcId) loads.delete(key);
  }
}

export interface ReadRequest {
  dashboardId: string;
  dcId: string;
  /** A past-version view: the data collection's status in that version. */
  pinned: boolean;
  entry?: DataVersionCollectionStatus;
  force?: boolean;
}

async function fetchTable({ dcId, pinned, entry }: ReadRequest): Promise<Load> {
  let version: number | null = null;
  if (pinned) {
    // Fail closed: a past view never shows today's rows as if they were then.
    if (!entry || entry.status !== 'pinned' || typeof entry.delta_version !== 'number') {
      const why = entry?.reason ? ` (${entry.reason.replace(/_/g, ' ')})` : '';
      return {
        kind: 'refused',
        message: `This view shows a past version, and the version of this table it read cannot be resolved${why}. The grid stays closed rather than show the table as it is now.`,
      };
    }
    version = entry.delta_version;
  } else {
    // Whoever may write reads the table as the editor does: whole, with the
    // version its cells will be saved against.
    const status = await editStatusOf(dcId);
    if (status?.can_edit) {
      try {
        const data = await fetchTableForEdit(dcId);
        if (data.rows.length <= MAX_ANNOTATION_ROWS) {
          return {
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
        }
      } catch {
        // Falls back to the read-only preview below.
      }
    }
  }
  try {
    const res = await fetchDataCollectionPreview(dcId, MAX_ANNOTATION_ROWS, [], version);
    return res.total_rows > MAX_ANNOTATION_ROWS
      ? {
          kind: 'refused',
          message: `This table has ${res.total_rows.toLocaleString()} rows. Labels work on tables of up to ${MAX_ANNOTATION_ROWS.toLocaleString()} rows, so that the list of samples is never cut short; pick a smaller table.`,
        }
      : {
          kind: 'ready',
          table: { dcId, columns: res.columns, rows: res.rows, version: res.version ?? null, edit: null },
        };
  } catch (err) {
    return {
      kind: 'refused',
      message: err instanceof Error ? err.message : 'The table could not be read.',
    };
  }
}

/** The table, from what is held when fresh, else from the server. Only a table
 *  that was read is held: a failure is asked again next time. */
export function readAnnotationTable(req: ReadRequest): Promise<Load> {
  const version = req.pinned ? (req.entry?.delta_version ?? null) : null;
  const key = loadKey(req.dashboardId, req.dcId, version);
  const hit = loads.get(key);
  if (!req.force && fresh(hit)) return Promise.resolve(hit.value);
  const running = inflight.get(key);
  if (!req.force && running) return running;
  const promise = fetchTable(req)
    .then((load) => {
      if (load.kind === 'ready') loads.set(key, { value: load, at: Date.now() });
      return load;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, promise);
  return promise;
}

/** The table the panel opens on: the one holding the compared (else the first)
 *  label, else the table whose labels reach the most collections. The panel and
 *  the warm-up both ask, so they agree on which table that is. */
export function defaultAnnotationTable(
  tables: AnnotationTable[],
  columns: { id: string; dcId: string }[] | undefined,
  activeColumnId: string | null | undefined,
): AnnotationTable | undefined {
  const eligible = tables
    .filter((t) => t.eligible)
    .sort((a, b) => (b.link_targets ?? 0) - (a.link_targets ?? 0));
  const anyCol = columns?.find((c) => c.id === activeColumnId) ?? columns?.[0];
  return eligible.find((t) => t.dc_id === anyCol?.dcId) ?? eligible[0];
}

/** Reads the table the panel will open on, before it is opened. Live views
 *  only: a past view needs the version status first, and is rarely the one a
 *  reader opens. Errors stay unheard: the panel asks again. */
export function warmAnnotationTable(dashboardId: string, entry: AnnotationTable | undefined): void {
  if (!entry) return;
  void readAnnotationTable({ dashboardId, dcId: entry.dc_id, pinned: false });
}
