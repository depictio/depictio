import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { notifications } from '@mantine/notifications';
import {
  AnnotationLayerProvider,
  CommentsControlProvider,
  createCommentThread,
  fetchCommentAccess,
  fetchCommentCounts,
  fetchCommentThreads,
  fetchPublishedAnnotations,
  publishedToRenderable,
  threadsToRenderable,
} from 'depictio-react-core';
import type {
  AnnotateState,
  AnnotationDraft,
  CommentCounts,
  CommentsControl,
  CommentThread,
  CommentViewState,
  InteractiveFilter,
  RenderableAnnotation,
  StoredMetadata,
} from 'depictio-react-core';

import { useUiStore } from '../../store/useUiStore';
import type { CurrentUser } from '../../hooks/useCurrentUser';
import CommentsDrawer from './CommentsDrawer';
import { buildViewState, componentLabel } from './viewState';

const EMPTY_COUNTS: CommentCounts = { open: {}, proposed: {} };
const NO_ITEMS: Record<string, RenderableAnnotation[]> = {};

type Access = 'unknown' | 'editor' | 'viewer';

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
 * Comments and chart annotations of the current tab.
 *
 * Editors and owners (the API's `/access` says `can_comment`) get the comments
 * context (chrome badges, drawer) and an annotation layer drawing every
 * annotation thread, with annotate mode. Everyone else gets no comments
 * context and a read-only layer holding only the annotations published to
 * viewers; if even that is refused, nothing is drawn.
 *
 * The tab's threads are loaded here, once, and shared by the drawer and the
 * annotation layer, so a reply, a resolve or a new annotation shows up in both.
 *
 * The provider tree has the same shape in every state (null values instead of
 * missing providers): swapping wrapper element types would remount the whole
 * dashboard beneath it each time access resolves.
 */
const CommentsProvider: React.FC<CommentsProviderProps> = ({
  dashboardId,
  metadata,
  filters,
  onApplyViewState,
  currentUser,
  children,
}) => {
  const [access, setAccess] = useState<Access>('unknown');
  const [counts, setCounts] = useState<CommentCounts>(EMPTY_COUNTS);
  const [threads, setThreads] = useState<CommentThread[] | null>(null);
  const [threadsError, setThreadsError] = useState<string | null>(null);
  const [published, setPublished] = useState<Record<string, RenderableAnnotation[]>>(NO_ITEMS);

  const openComments = useUiStore((s) => s.openComments);
  const resetComments = useUiStore((s) => s.resetComments);
  const focusedThreadId = useUiStore((s) => s.focusedThreadId);
  const annotateComponentIndex = useUiStore((s) => s.annotateComponentIndex);
  const annotateTool = useUiStore((s) => s.annotateTool);
  const setAnnotate = useUiStore((s) => s.setAnnotate);

  // Responses are only applied while they still belong to the current
  // dashboard: a slow answer for the previous tab must not land on this one.
  const dashboardRef = useRef(dashboardId);
  dashboardRef.current = dashboardId;
  const threadsReq = useRef(0);
  const countsReq = useRef(0);

  const userId = currentUser?.id ?? null;

  useEffect(() => {
    setAccess('unknown');
    setCounts(EMPTY_COUNTS);
    setThreads(null);
    setThreadsError(null);
    setPublished(NO_ITEMS);
    resetComments();
    if (!dashboardId) return;
    let cancelled = false;
    fetchCommentAccess(dashboardId)
      .then((r) => {
        if (!cancelled) setAccess(r.can_comment ? 'editor' : 'viewer');
      })
      // An unreachable comments API is the same as no access.
      .catch(() => {
        if (!cancelled) setAccess('viewer');
      });
    return () => {
      cancelled = true;
    };
    // The user is part of the key: logging in or out changes what they may see.
  }, [dashboardId, userId, resetComments]);

  const refreshCounts = useCallback(async () => {
    if (!dashboardId) return;
    const req = ++countsReq.current;
    try {
      const next = await fetchCommentCounts(dashboardId);
      if (req === countsReq.current && dashboardRef.current === dashboardId) setCounts(next);
    } catch {
      // Badges are a convenience; a failed refresh keeps the last counts.
    }
  }, [dashboardId]);

  const loadThreads = useCallback(async () => {
    if (!dashboardId) return;
    const req = ++threadsReq.current;
    setThreadsError(null);
    try {
      const next = await fetchCommentThreads(dashboardId, { scope: 'tab' });
      if (req === threadsReq.current && dashboardRef.current === dashboardId) setThreads(next);
    } catch (err) {
      if (req === threadsReq.current && dashboardRef.current === dashboardId) {
        setThreadsError(err instanceof Error ? err.message : String(err));
      }
    }
  }, [dashboardId]);

  useEffect(() => {
    if (access !== 'editor') return;
    void refreshCounts();
    void loadThreads();
  }, [access, refreshCounts, loadThreads]);

  // Viewers: the published annotations only, once per dashboard. A refusal
  // (403 on a private dashboard, an older API) simply draws nothing.
  useEffect(() => {
    if (access !== 'viewer' || !dashboardId) return;
    let cancelled = false;
    fetchPublishedAnnotations(dashboardId)
      .then((items) => {
        if (!cancelled) setPublished(publishedToRenderable(items));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [access, dashboardId]);

  // Mutations from the drawer and the annotation popover, applied locally
  // (the server's answer is the new thread) and followed by a badge refresh.
  const addThread = useCallback(
    (created: CommentThread) => {
      setThreads((prev) => [created, ...(prev ?? []).filter((t) => t.id !== created.id)]);
      void refreshCounts();
    },
    [refreshCounts],
  );
  const replaceThread = useCallback(
    (next: CommentThread) => {
      setThreads((prev) => (prev ?? []).map((t) => (t.id === next.id ? next : t)));
      void refreshCounts();
    },
    [refreshCounts],
  );
  const removeThread = useCallback(
    (id: string) => {
      setThreads((prev) => (prev ?? []).filter((t) => t.id !== id));
      void refreshCounts();
    },
    [refreshCounts],
  );

  const isEditor = access === 'editor' && !!dashboardId;

  const control = useMemo<CommentsControl | null>(
    () =>
      isEditor
        ? {
            openCounts: counts.open ?? {},
            proposedCounts: counts.proposed ?? {},
            openDrawer: (componentIndex) => openComments(componentIndex ?? null),
            canComment: true,
          }
        : null,
    [isEditor, counts, openComments],
  );

  // ── Annotation layer ──────────────────────────────────────────────────────
  const editorItems = useMemo(() => threadsToRenderable(threads ?? []), [threads]);
  const layerItems = isEditor ? editorItems : access === 'viewer' ? published : NO_ITEMS;

  const annotate = useMemo<AnnotateState | null>(
    () =>
      annotateComponentIndex && annotateTool
        ? { componentIndex: annotateComponentIndex, tool: annotateTool }
        : null,
    [annotateComponentIndex, annotateTool],
  );

  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const metadataRef = useRef(metadata);
  metadataRef.current = metadata;

  const saveAnnotation = useCallback(
    async (componentIndex: string, draft: AnnotationDraft) => {
      if (!dashboardId) return;
      const meta = metadataRef.current.find((m) => String(m.index) === componentIndex);
      try {
        const created = await createCommentThread({
          anchor: {
            dashboard_id: dashboardId,
            component_index: componentIndex,
            component_title: meta ? componentLabel(meta) : null,
            view_state: buildViewState(filtersRef.current, componentIndex),
          },
          body: draft.body || undefined,
          annotation: draft.annotation,
        });
        if (dashboardRef.current === dashboardId) addThread(created);
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Could not save annotation',
          message: err instanceof Error ? err.message : String(err),
        });
        throw err;
      }
    },
    [dashboardId, addThread],
  );

  return (
    <CommentsControlProvider value={control}>
      <AnnotationLayerProvider
        items={layerItems}
        highlightId={focusedThreadId}
        canAnnotate={isEditor}
        annotate={annotate}
        setAnnotate={setAnnotate}
        onSave={saveAnnotation}
      >
        {children}
        {isEditor && dashboardId && (
          <CommentsDrawer
            dashboardId={dashboardId}
            metadata={metadata}
            filters={filters}
            onApplyViewState={onApplyViewState}
            currentUser={currentUser}
            threads={threads}
            loadError={threadsError}
            onReload={loadThreads}
            onCreated={addThread}
            onChanged={replaceThread}
            onDeleted={removeThread}
          />
        )}
      </AnnotationLayerProvider>
    </CommentsControlProvider>
  );
};

export default CommentsProvider;
