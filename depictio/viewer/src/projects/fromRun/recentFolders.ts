/**
 * The last run folders the reader chose, per source, kept in this browser.
 *
 * A convenience only: every read and write is guarded, so a private window,
 * blocked storage or a corrupt entry just means an empty list.
 */
import { folderSource, normalizeFolder } from 'depictio-react-core';
import type { FolderSource } from 'depictio-react-core';

const STORAGE_KEY = 'depictio.run-folder.recent.v1';
const LIMIT = 5;

export type RecentRunFolders = Record<FolderSource, string[]>;

const EMPTY: RecentRunFolders = { local: [], s3: [] };

function onlyStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === 'string' && v.length > 0).slice(0, LIMIT)
    : [];
}

export function readRecentRunFolders(): RecentRunFolders {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<Record<FolderSource, unknown>> | null;
    return { local: onlyStrings(parsed?.local), s3: onlyStrings(parsed?.s3) };
  } catch {
    return EMPTY;
  }
}

/** Put `location` first in its source's list (moving it up when already
 *  there) and keep the last five. Returns the new lists. */
export function rememberRunFolder(location: string): RecentRunFolders {
  const current = readRecentRunFolders();
  const folder = normalizeFolder(location);
  if (!folder) return current;
  const source = folderSource(folder);
  const next: RecentRunFolders = {
    ...current,
    [source]: [folder, ...current[source].filter((f) => f !== folder)].slice(0, LIMIT),
  };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage unavailable: the list just is not remembered.
  }
  return next;
}
