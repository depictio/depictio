/**
 * Where a Code-Mode snippet actually runs.
 *
 * In depictio the answer is fixed — the server executes it in the
 * RestrictedPython sandbox — so `FigureCodeMode` describes that directly and no
 * provider is mounted. Tool Studio embeds the same panel with no backend at
 * all: its preview runs the snippet in the browser under Pyodide, against the
 * fixture, with pandas instead of Polars. That is a different enough contract
 * that leaving the panel saying "runs server-side" would be wrong, so the host
 * app can supply a note the panel shows first.
 */
import React, { createContext, useContext } from 'react';

export interface CodeModeEnvironment {
  /** Shown at the top of the "About Code Mode" panel, above depictio's own
   *  description of the execution sandbox. */
  note: React.ReactNode;
  /** Open that panel on first render. A host whose execution model differs
   *  from depictio's wants the note read, not found. */
  openAbout?: boolean;
}

const CodeModeEnvironmentContext = createContext<CodeModeEnvironment | null>(null);

export const CodeModeEnvironmentProvider = CodeModeEnvironmentContext.Provider;

/** The host app's execution note, or null when the snippet runs the standard
 *  depictio way (server-side). */
export function useCodeModeEnvironment(): CodeModeEnvironment | null {
  return useContext(CodeModeEnvironmentContext);
}
