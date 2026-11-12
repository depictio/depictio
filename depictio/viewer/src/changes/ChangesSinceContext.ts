import { createContext, useContext } from 'react';

import type { DashboardChangeSet, MarkMode } from 'depictio-react-core';

import type { ReadOnlyQuery } from './describe';

/** What the pill and the panel read. Null while the feature is off, the view
 *  is a pinned preview, or the change set has not arrived: they render nothing. */
export interface ChangesSinceValue {
  changeSet: DashboardChangeSet;
  /** The tab on screen: dashboard rows link relative to it. */
  tabId: string;
  familyId: string;
  /** May open the editor's History. */
  canEdit: boolean;
  /** `?since=` / `?before_run=`: never moves a mark. */
  readOnly: boolean;
  readOnlyQuery: ReadOnlyQuery;
  mode: MarkMode;
  setMode: (mode: MarkMode) => void;
  markAllSeen: () => Promise<void>;
  seenBusy: boolean;
}

export const ChangesSinceContext = createContext<ChangesSinceValue | null>(null);

export const useChangesSince = (): ChangesSinceValue | null => useContext(ChangesSinceContext);
