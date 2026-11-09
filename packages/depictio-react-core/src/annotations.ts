/**
 * Session annotations on a dashboard.
 *
 * A reader labels the rows of one table, keyed on one of its columns, to
 * compare groups of samples without changing the data. The labels are the
 * source of truth; the selection groups the Analysis panel shows are derived
 * from them (`annotationGroups.ts`) and never edited back.
 *
 * Storage is the browser (temporary and anonymous accounts) or the account
 * (`/dashboards/annotations/{id}`). The caps below mirror the server model
 * (`depictio/models/models/dashboard_annotations.py`) so the panel can refuse
 * an input before a save would.
 */

export const MAX_ANNOTATION_COLUMNS = 20;
export const MAX_ANNOTATION_KEYS = 10_000;
/** The server's group name cap: every label becomes a group name. */
export const MAX_LABEL_LENGTH = 80;
/** The most groups the server renders, all groups counted (`MAX_GROUPS`). */
export const MAX_SERVER_GROUPS = 24;
/** The most rows the panel reads; a bigger table is refused, never truncated. */
export const MAX_ANNOTATION_ROWS = 10_000;

export interface AnnotationColumn {
  id: string;
  name: string;
  /** key value -> label. A key without a label is absent. */
  values: Record<string, string>;
}

export interface DashboardAnnotations {
  version: 1;
  dcId: string;
  keyColumn: string;
  columns: AnnotationColumn[];
  activeColumnId: string | null;
}

export function emptyAnnotations(dcId: string, keyColumn: string): DashboardAnnotations {
  return { version: 1, dcId, keyColumn, columns: [], activeColumnId: null };
}

function isRecordOfStrings(v: unknown): v is Record<string, string> {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) return false;
  return Object.values(v as Record<string, unknown>).every((x) => typeof x === 'string');
}

/** A stored or received value, or null when it is not annotations of version 1. */
export function parseAnnotations(raw: unknown): DashboardAnnotations | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (r.version !== 1 || typeof r.dcId !== 'string' || typeof r.keyColumn !== 'string') {
    return null;
  }
  if (!Array.isArray(r.columns)) return null;
  const columns: AnnotationColumn[] = [];
  for (const c of r.columns as unknown[]) {
    if (typeof c !== 'object' || c === null) return null;
    const col = c as Record<string, unknown>;
    if (typeof col.id !== 'string' || typeof col.name !== 'string') return null;
    if (!isRecordOfStrings(col.values)) return null;
    columns.push({ id: col.id, name: col.name, values: { ...col.values } });
  }
  const active = typeof r.activeColumnId === 'string' ? r.activeColumnId : null;
  return {
    version: 1,
    dcId: r.dcId,
    keyColumn: r.keyColumn,
    columns,
    activeColumnId: active && columns.some((c) => c.id === active) ? active : null,
  };
}

/** Why the server would refuse these annotations, or null when it would take them. */
export function annotationsProblem(a: DashboardAnnotations): string | null {
  if (a.columns.length > MAX_ANNOTATION_COLUMNS) {
    return `At most ${MAX_ANNOTATION_COLUMNS} annotations.`;
  }
  const names = new Set<string>();
  for (const c of a.columns) {
    if (!c.name.trim() || c.name.length > MAX_LABEL_LENGTH) {
      return `An annotation name must be 1 to ${MAX_LABEL_LENGTH} characters.`;
    }
    if (names.has(c.name)) return `Two annotations are named "${c.name}".`;
    names.add(c.name);
    const entries = Object.entries(c.values);
    if (entries.length > MAX_ANNOTATION_KEYS) {
      return `"${c.name}" labels more than ${MAX_ANNOTATION_KEYS.toLocaleString()} rows.`;
    }
    if (entries.some(([, label]) => label.length > MAX_LABEL_LENGTH)) {
      return `A label of "${c.name}" is longer than ${MAX_LABEL_LENGTH} characters.`;
    }
  }
  return null;
}

/** A label as stored: trimmed, and absent (null) when blank. */
export function normaliseLabel(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const s = String(value).trim();
  return s ? s : null;
}

/** Set (or clear, with a blank label) one key's label in one column. */
export function setLabel(
  a: DashboardAnnotations,
  columnId: string,
  key: string,
  label: unknown,
): DashboardAnnotations {
  const clean = normaliseLabel(label);
  return {
    ...a,
    columns: a.columns.map((c) => {
      if (c.id !== columnId) return c;
      const values = { ...c.values };
      if (clean === null) delete values[key];
      else values[key] = clean;
      return { ...c, values };
    }),
  };
}

export function newAnnotationId(): string {
  return `ann-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

// --- Browser storage ---------------------------------------------------------

const STORAGE_PREFIX = 'depictio.annotations.';

export type BrowserRead = { ok: true; value: DashboardAnnotations | null } | { ok: false };

function storage(): Storage | null {
  try {
    return typeof globalThis.localStorage === 'undefined' ? null : globalThis.localStorage;
  } catch {
    return null;
  }
}

/** `ok: false` when the browser keeps nothing (private mode, blocked storage). */
export function readBrowserAnnotations(dashboardId: string): BrowserRead {
  const store = storage();
  if (!store) return { ok: false };
  try {
    const raw = store.getItem(STORAGE_PREFIX + dashboardId);
    return { ok: true, value: raw ? parseAnnotations(JSON.parse(raw)) : null };
  } catch {
    return { ok: false };
  }
}

/** Store (or, with null, remove). Returns false when the browser refused. */
export function writeBrowserAnnotations(
  dashboardId: string,
  value: DashboardAnnotations | null,
): boolean {
  const store = storage();
  if (!store) return false;
  try {
    const key = STORAGE_PREFIX + dashboardId;
    if (value === null || value.columns.length === 0) store.removeItem(key);
    else store.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
