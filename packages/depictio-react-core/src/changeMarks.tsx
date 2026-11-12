/**
 * Which components changed since the reader's last visit (#1397).
 *
 * The viewer provides, the component chrome (and later the figure renderers)
 * consume. The default value is empty and inert, so the editor and every other
 * host that mounts no provider are unaffected: no mark, no dot, no request.
 */
import React, { createContext, useContext } from 'react';

export type ChangeReason = 'definition' | 'data';

export interface ChangeMarksValue {
  /** `${tabId}:${componentIndex}` -> reasons. Empty when the feature is off or nothing changed. */
  marked: Record<string, ChangeReason[]>;
  /** The tab currently rendered (component keys are `${tabId}:${index}`). */
  tabId: string | null;
  /** Keys whose figure shows the before/after overlay. */
  comparing: ReadonlySet<string>;
  toggleCompare: (key: string) => void;
  /** Open the side-by-side Before | Now view for one component (no-op until wired). */
  openCompare: (key: string) => void;
  dismiss: (key: string) => void;
  /** What to diff against, for the before/after requests: the reader's baseline (anonymous), or the read-only since/before_run. */
  diffQuery: { baseline?: unknown; since?: string | null; beforeRun?: string | null };
  /** The dashboard version the baseline saw, for rendering the 'before' definition. */
  baselineVersionId: string | null;
  readOnly: boolean;
}

const NO_COMPARING: ReadonlySet<string> = new Set<string>();
const noop = (): void => {};

export const EMPTY_CHANGE_MARKS: ChangeMarksValue = {
  marked: {},
  tabId: null,
  comparing: NO_COMPARING,
  toggleCompare: noop,
  openCompare: noop,
  dismiss: noop,
  diffQuery: {},
  baselineVersionId: null,
  readOnly: false,
};

export const ChangeMarksContext = createContext<ChangeMarksValue>(EMPTY_CHANGE_MARKS);

/** The key a component is marked under: unique across a dashboard family. */
export const changeKey = (tabId: string, componentIndex: string): string =>
  `${tabId}:${componentIndex}`;

const NO_REASONS: ChangeReason[] = [];

export function useChangeMark(componentIndex: string | undefined): {
  reasons: ChangeReason[];
  key: string | null;
  comparing: boolean;
} {
  const value = useContext(ChangeMarksContext);
  if (!componentIndex || !value.tabId) return { reasons: NO_REASONS, key: null, comparing: false };
  const key = changeKey(value.tabId, componentIndex);
  return {
    reasons: value.marked[key] ?? NO_REASONS,
    key,
    comparing: value.comparing.has(key),
  };
}

/**
 * The words behind a mark, for its tooltip ("Definition changed by a@b",
 * "Data refreshed: run_c"), kept apart from `ChangeMarksValue` so that
 * contract stays as small as its consumers need.
 */
const NO_LINES: string[] = [];

export const ChangeMarkDetailsContext = createContext<Record<string, string[]>>({});

export function useChangeMarkDetails(key: string | null): string[] {
  const details = useContext(ChangeMarkDetailsContext);
  return (key && details[key]) || NO_LINES;
}

const EMPTY_DETAILS: Record<string, string[]> = {};

export const ChangeMarksProviderBase: React.FC<{
  value: ChangeMarksValue;
  details?: Record<string, string[]>;
  children: React.ReactNode;
}> = ({ value, details, children }) => (
  <ChangeMarksContext.Provider value={value}>
    <ChangeMarkDetailsContext.Provider value={details ?? EMPTY_DETAILS}>
      {children}
    </ChangeMarkDetailsContext.Provider>
  </ChangeMarksContext.Provider>
);
