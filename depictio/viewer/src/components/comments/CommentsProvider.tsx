import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CommentsControlProvider,
  fetchCommentAccess,
  fetchCommentCounts,
} from 'depictio-react-core';
import type {
  CommentCounts,
  CommentsControl,
  CommentViewState,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

import { useUiStore } from '../../store/useUiStore';
import type { CurrentUser } from '../../hooks/useCurrentUser';
import CommentsDrawer from './CommentsDrawer';

const EMPTY_COUNTS: CommentCounts = { open: {}, proposed: {} };

export interface CommentsProviderProps {
  dashboardId: string | null;
  /** This tab's components, for group headers and anchor titles. */
  metadata: StoredMetadata[];
  /** The dashboard's live (non-debounced) filters, attached to new comments. */
  filters: InteractiveFilter[];
  /** Restores a thread's view: replaces the dashboard filters. */
  onApplyViewState: (viewState: CommentViewState) => void;
  currentUser: CurrentUser | null;
  children: React.ReactNode;
}

/**
 * Comments for editors and owners of the dashboard's project.
 *
 * Asks the API once per tab whether the user may comment. When they may not,
 * it renders its children and nothing else: no context reaches the component
 * chrome or the header, so viewers never see a badge, a button or a drawer.
 */
const CommentsProvider: React.FC<CommentsProviderProps> = ({
  dashboardId,
  metadata,
  filters,
  onApplyViewState,
  currentUser,
  children,
}) => {
  const [canComment, setCanComment] = useState(false);
  const [counts, setCounts] = useState<CommentCounts>(EMPTY_COUNTS);
  const openComments = useUiStore((s) => s.openComments);
  const closeComments = useUiStore((s) => s.closeComments);

  useEffect(() => {
    setCanComment(false);
    setCounts(EMPTY_COUNTS);
    closeComments();
    if (!dashboardId) return;
    let cancelled = false;
    fetchCommentAccess(dashboardId)
      .then((r) => {
        if (!cancelled) setCanComment(Boolean(r.can_comment));
      })
      // An unreachable comments API is the same as no access: stay silent.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [dashboardId, closeComments]);

  const refreshCounts = useCallback(async () => {
    if (!dashboardId) return;
    try {
      setCounts(await fetchCommentCounts(dashboardId));
    } catch {
      // Badges are a convenience; a failed refresh keeps the last counts.
    }
  }, [dashboardId]);

  useEffect(() => {
    if (canComment) void refreshCounts();
  }, [canComment, refreshCounts]);

  const control = useMemo<CommentsControl | null>(
    () =>
      canComment
        ? {
            openCounts: counts.open ?? {},
            proposedCounts: counts.proposed ?? {},
            openDrawer: (componentIndex) => openComments(componentIndex ?? null),
            canComment: true,
          }
        : null,
    [canComment, counts, openComments],
  );

  if (!control || !dashboardId) return <>{children}</>;

  return (
    <CommentsControlProvider value={control}>
      {children}
      <CommentsDrawer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onApplyViewState={onApplyViewState}
        currentUser={currentUser}
        onMutated={refreshCounts}
      />
    </CommentsControlProvider>
  );
};

export default CommentsProvider;
