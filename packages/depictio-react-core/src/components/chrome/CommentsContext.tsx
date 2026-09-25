import React, { createContext, useContext } from 'react';

/**
 * Lets the app hang a "comments" action off every component's chrome without
 * this package learning about the app's store or its comments drawer.
 *
 * Same contract as `InspectorContext`: the viewer provides, the chrome
 * consumes, and a null context (the default) is the feature flag. The viewer
 * only mounts a value when the current user may comment on the dashboard
 * (editors and owners), so for everyone else no comments action is rendered.
 */
export interface CommentsControl {
  /** Open threads per component index (`__tab__` for tab-level threads). */
  openCounts: Record<string, number>;
  /** Agent proposals awaiting review, same keys. */
  proposedCounts: Record<string, number>;
  /** Unsettled threads (open or proposed) whose data or component changed
   *  since they were written, same keys. */
  staleCounts: Record<string, number>;
  /** Opens the comments drawer on one component, or on the whole tab (null). */
  openDrawer: (componentIndex?: string | null) => void;
  canComment: boolean;
}

export const CommentsContext = createContext<CommentsControl | null>(null);

export const CommentsControlProvider: React.FC<{
  value: CommentsControl | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <CommentsContext.Provider value={value}>{children}</CommentsContext.Provider>
);

export function useCommentsControl(): CommentsControl | null {
  return useContext(CommentsContext);
}
