import { createContext, useContext } from 'react';

import type { DashboardChangeSet, GroupRenderDef, MarkMode } from 'depictio-react-core';

import type { ReadOnlyQuery } from './describe';
import type { NewsView } from './newsSplit';

/** What the pill and the panel read. Null while the feature is off, the view
 *  is a pinned preview, or the change set has not arrived: they render nothing. */
export interface ChangesSinceValue {
  changeSet: DashboardChangeSet;
  /** The tab on screen: dashboard rows link relative to it. */
  tabId: string;
  familyId: string;
  /** The dashboard's project: data rows link to its collections. */
  projectId: string | null;
  /** May open the editor's History. */
  canEdit: boolean;
  /** `?since=` / `?before_run=`: never moves a mark. */
  readOnly: boolean;
  readOnlyQuery: ReadOnlyQuery;
  mode: MarkMode;
  setMode: (mode: MarkMode) => void;
  markAllSeen: () => Promise<void>;
  seenBusy: boolean;
  /** How many changed figures on this tab can show what is new in place. */
  highlightable: number;
  /** How the news shows on the canvas: off, marked in place, or split by run. */
  view: NewsView;
  setView: (view: NewsView) => void;
  /** Some change came as new runs, so the split has two sides to show. */
  splitAvailable: boolean;
  /** The split's groups while it is on (the legend of the panel). */
  splitGroups: GroupRenderDef[] | null;
  /** The runs that are new since the mark, sorted. */
  newRuns: string[];
  /** The one new run the view follows, or null for all of them. */
  focusRun: string | null;
  setFocusRun: (run: string | null) => void;
  /** That run alone on the dashboard (turning the view on if it was off), or
   *  every new run again when it was already the one shown. */
  showRun: (run: string) => void;
}

export const ChangesSinceContext = createContext<ChangesSinceValue | null>(null);

export const useChangesSince = (): ChangesSinceValue | null => useContext(ChangesSinceContext);
