/**
 * Where an anonymous or temporary reader's "changed since your last visit"
 * mark lives: their own browser (#1397).
 *
 * One anonymous account is shared by every visitor, so the server cannot hold
 * the mark for them. It hands back `current_baseline` instead and reads the
 * stored one from the request. This module is the browser half: pure functions
 * over `localStorage`, with a per-page memory fallback so the feature still
 * works for the length of a page load when storage is blocked.
 *
 * Every storage access is wrapped: a private window, blocked site data or a
 * full quota must degrade to "no memory", never to an exception.
 */
import type { DismissedComponents, MarkMode, ReaderBaseline } from './api';

export const CHANGES_KEY_PREFIX = 'depictio.changesSince.v1:';
export const CHANGES_MODE_KEY = 'depictio.changesSince.mode.v1';

/** One entry per dashboard family: the baseline and the dismissed components. */
export const changesStorageKey = (familyId: string): string => `${CHANGES_KEY_PREFIX}${familyId}`;

export interface LocalReaderState {
  baseline: ReaderBaseline | null;
  dismissed: DismissedComponents;
}

const memory = new Map<string, string>();

function getItem(key: string): string | null {
  try {
    const stored = localStorage.getItem(key);
    if (stored !== null) return stored;
  } catch {
    // Storage blocked: fall through to this page's memory.
  }
  return memory.get(key) ?? null;
}

function setItem(key: string, value: string): void {
  memory.set(key, value);
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage blocked or full: the memory copy still serves this page load.
  }
}

/** Forget this page's memory copies (tests). */
export function resetChangesMemory(): void {
  memory.clear();
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export function isMarkMode(value: unknown): value is MarkMode {
  return value === 'sticky' || value === 'previous_visit';
}

function asDismissed(value: unknown): DismissedComponents {
  if (!isRecord(value)) return {};
  const out: DismissedComponents = {};
  for (const [key, entry] of Object.entries(value)) {
    if (!isRecord(entry)) continue;
    out[key] = {
      fingerprint: typeof entry.fingerprint === 'string' ? entry.fingerprint : null,
      data_token: typeof entry.data_token === 'string' ? entry.data_token : null,
    };
  }
  return out;
}

/** What this browser remembers of one dashboard family. Never throws. */
export function readLocalReader(familyId: string): LocalReaderState {
  const empty: LocalReaderState = { baseline: null, dismissed: {} };
  const raw = getItem(changesStorageKey(familyId));
  if (!raw) return empty;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return empty;
    const baseline =
      isRecord(parsed.baseline) && typeof parsed.baseline.seen_at === 'string'
        ? (parsed.baseline as ReaderBaseline)
        : null;
    return { baseline, dismissed: baseline ? asDismissed(parsed.dismissed) : {} };
  } catch {
    return empty;
  }
}

function writeLocalReader(familyId: string, state: LocalReaderState): void {
  setItem(changesStorageKey(familyId), JSON.stringify(state));
}

/** Store a new baseline. Dismissals belong to the baseline they were made
 *  against, so moving it clears them, as the server does. */
export function writeLocalBaseline(familyId: string, baseline: ReaderBaseline): void {
  writeLocalReader(familyId, { baseline, dismissed: {} });
}

/** Add dismissed components (the `dismissed` the server returns for a "seen"). */
export function mergeLocalDismissed(familyId: string, dismissed: DismissedComponents): void {
  const current = readLocalReader(familyId);
  if (!current.baseline) return; // nothing to be dismissed against
  writeLocalReader(familyId, {
    baseline: current.baseline,
    dismissed: { ...current.dismissed, ...asDismissed(dismissed) },
  });
}

/** The anonymous reader's mark mode, or null when they never chose. */
export function readLocalMode(): MarkMode | null {
  const raw = getItem(CHANGES_MODE_KEY);
  return isMarkMode(raw) ? raw : null;
}

export function writeLocalMode(mode: MarkMode): void {
  setItem(CHANGES_MODE_KEY, mode);
}
