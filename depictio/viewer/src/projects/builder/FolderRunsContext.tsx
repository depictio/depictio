/**
 * What the builder knows of its data folder from the one inspection it makes
 * (`useRootDetection`, the same `folder_inspect` the New project dialog
 * reads): whether that read has settled, the folder as the server resolved
 * it, and the runs it holds when it is a folder of runs rather than one
 * (`FolderInspection.child_runs`, two or more).
 *
 * A draft that edits a shipped template reads those runs into one project,
 * the way the dialog does: its plan and its creation send them as `runs`,
 * and its workflow says "2 runs", not "one run". Nothing that depends on the
 * runs is asked of the server before the inspection settles: asked earlier,
 * a folder of runs would be read as one run, and found empty.
 */
import React, { createContext, useContext } from 'react';

import type { FolderInspection } from 'depictio-react-core';

export interface BuilderFolder {
  /** The inspection answered or failed: `runs` is final. */
  settled: boolean;
  /** The folder as the server resolved it (`~` expanded); null until read. */
  location: string | null;
  /** Its runs, when it holds two or more; null for a run. */
  runs: string[] | null;
}

const UNREAD: BuilderFolder = { settled: false, location: null, runs: null };

const FolderContext = createContext<BuilderFolder>(UNREAD);

/** The runs of an inspected folder; null for a run, or a single child. */
export function folderRuns(inspection: FolderInspection | null | undefined): string[] | null {
  if (!inspection || inspection.looks_like_run) return null;
  const runs = inspection.child_runs ?? [];
  return runs.length > 1 ? runs : null;
}

export const FolderRunsProvider: React.FC<{ folder: BuilderFolder; children: React.ReactNode }> = ({
  folder,
  children,
}) => <FolderContext.Provider value={folder}>{children}</FolderContext.Provider>;

export function useBuilderFolder(): BuilderFolder {
  return useContext(FolderContext);
}

/** The folder's runs (see `BuilderFolder.runs`). */
export function useFolderRuns(): string[] | null {
  return useContext(FolderContext).runs;
}
