/**
 * The draft a `#draft=` link would have replaced.
 *
 * Opening a link loads its draft over whatever this browser had restored, and
 * that used to be the end of the previous work. Now the previous draft is
 * kept under its own key first (the persisted shape, so append mode, sibling
 * outputs and trust flags come back exactly), and the app offers it back.
 */
import { create } from 'zustand';
import { useStudioStore } from './useStudioStore';

export const BACKUP_KEY = 'depictio-studio-draft-backup';

interface BackupState {
  /** A backup is waiting to be restored or dismissed. */
  available: boolean;
  /** The backed-up draft's tool id, for the notice. */
  toolId?: string;
}

/** A backup left by an earlier visit is still offered (until dismissed). */
function initial(): BackupState {
  try {
    const text = localStorage.getItem(BACKUP_KEY);
    if (!text) return { available: false };
    const toolId = (JSON.parse(text) as { state?: { tool?: { id?: string } } }).state?.tool?.id;
    return { available: true, toolId: toolId || undefined };
  } catch {
    return { available: false };
  }
}

export const useDraftBackup = create<BackupState>(initial);

/** Kept here when localStorage refuses it (quota), for this session at least. */
let inMemory: string | null = null;

/** True when the current draft holds anything worth keeping. */
export function hasDraftContent(): boolean {
  const s = useStudioStore.getState();
  return Boolean(s.tool.id || s.output.slug || s.fixture || s.renders.length || s.siblings.length || s.existing);
}

/** Back the current draft up before a link replaces it. No-op on an empty draft. */
export function backupCurrentDraft(): boolean {
  if (!hasDraftContent()) return false;
  const s = useStudioStore.getState();
  const partialize = useStudioStore.persist.getOptions().partialize;
  const text = JSON.stringify({ state: partialize ? partialize(s) : s, version: 1 });
  inMemory = text;
  try {
    localStorage.setItem(BACKUP_KEY, text);
  } catch {
    /* over quota: the in-memory copy still serves this session */
  }
  useDraftBackup.setState({ available: true, toolId: s.tool.id || undefined });
  return true;
}

function readBackup(): string | null {
  try {
    return localStorage.getItem(BACKUP_KEY) ?? inMemory;
  } catch {
    return inMemory;
  }
}

/** Put the backed-up draft back (replacing the link's), and drop the backup. */
export function restoreDraftBackup(): boolean {
  const text = readBackup();
  if (!text) return false;
  const parsed = JSON.parse(text) as { state?: unknown };
  const merge = useStudioStore.persist.getOptions().merge;
  const current = useStudioStore.getState();
  // merge() is the rehydrate path: rows re-derived from raw, actions kept.
  useStudioStore.setState(merge ? merge(parsed.state, current) : { ...current, ...(parsed.state as object) });
  discardDraftBackup();
  return true;
}

export function discardDraftBackup(): void {
  inMemory = null;
  try {
    localStorage.removeItem(BACKUP_KEY);
  } catch {
    /* nothing to remove */
  }
  useDraftBackup.setState({ available: false, toolId: undefined });
}
