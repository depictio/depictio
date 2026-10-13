import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import type { AnnotationPatchInput } from './edit';
import { itemsWithEditDraft, nextEditDraft } from './inlineEdit';
import type { AnnotationEditDraft, ClientPoint } from './inlineEdit';
import type { AnnotateTool } from './layer';
import { defaultColorFor } from './layer';
import type { AnnotationStats } from './summary';
import { sameStats } from './summary';
import type {
  Annotation,
  AnnotationColor,
  AnnotationKind,
  AnnotationStyle,
  Geometry,
  RenderableAnnotation,
} from './types';

/** A shape just drawn in annotate mode, waiting for its label. */
export interface PendingAnnotation {
  componentIndex: string;
  geometry: Geometry;
  kind: AnnotationKind;
  /** The view of the component it was drawn on (see `Annotation.variant`). */
  variant?: string | null;
}

/**
 * What the label popover currently holds for the pending capture, drawn as a
 * preview on the component. `label` is '' until something is typed.
 */
export interface PendingDraft {
  label: string;
  color: AnnotationColor;
  style?: AnnotationStyle;
  /** The captured geometry, minus its region when the highlight is off. */
  geometry: Geometry;
}

export type PendingDraftPatch = Partial<PendingDraft>;

/** The draft a fresh capture starts from (same defaults as the form). */
export function initialPendingDraft(pending: PendingAnnotation): PendingDraft {
  return { label: '', color: defaultColorFor(pending.kind), geometry: pending.geometry };
}

/** What the annotation popover hands back on save. */
export interface AnnotationDraft {
  annotation: Annotation;
  /** Optional first comment of the thread. */
  body?: string;
}

/** The draft with the view its capture was drawn on; `draft` itself when none. */
export function withPendingVariant(draft: AnnotationDraft, pending: PendingAnnotation): AnnotationDraft {
  if (!pending.variant) return draft;
  return { ...draft, annotation: { ...draft.annotation, variant: pending.variant } };
}

/** The saved annotation being edited in place on its component. */
export interface InlineAnnotationEdit {
  threadId: string;
  componentIndex: string;
  /** Where it was clicked (viewport coords); null opens the editor centred. */
  anchor: ClientPoint | null;
}

export interface AnnotateState {
  componentIndex: string;
  tool: AnnotateTool;
}

/**
 * The chart annotation layer, as renderers and the component chrome see it.
 *
 * Same contract as `CommentsContext`: the app provides, react-core consumes,
 * and a null context (nothing mounted) means no annotations at all. The app
 * decides what is drawn (every annotation thread for editors, published ones
 * for viewers) and how a new annotation is stored; this package only knows
 * how to draw and capture them.
 */
export interface AnnotationLayerControl {
  /** Annotations drawn on a component (stable array identity per update). */
  itemsFor: (componentIndex: string) => RenderableAnnotation[];
  /** Annotation drawn emphasised, e.g. the thread focused in the drawer. */
  highlightId: string | null;
  /** Whether the user may create annotations (annotate mode, point stats). */
  canAnnotate: boolean;
  /** Component in annotate mode and its tool, or null. */
  annotate: AnnotateState | null;
  setAnnotate: (componentIndex: string | null, tool?: AnnotateTool | null) => void;
  /** Shape captured and awaiting a label (at most one at a time). */
  pending: PendingAnnotation | null;
  /** `variant`: the view of the component the shape was drawn on, stored with it. */
  onCaptured: (
    componentIndex: string,
    geometry: Geometry,
    kindHint: AnnotationKind,
    variant?: string | null,
  ) => void;
  cancelPending: () => void;
  /** Stores the pending annotation. Rejects on failure (the popover stays open). */
  savePending: (draft: AnnotationDraft) => Promise<void>;
  /** Live state of the label popover, for the preview; null when nothing is pending. */
  pendingDraft: PendingDraft | null;
  /** The popover pushes its fields here as they change. Stable identity. */
  updatePendingDraft: (patch: PendingDraftPatch) => void;
  /**
   * Opens a thread from its annotation on a component (label, marked-points
   * ring or table row badge clicked outside annotate mode). Null when the app
   * does not handle it.
   */
  onAnnotationClick: ((threadId: string, componentIndex: string) => void) | null;
  /**
   * What renderers call when a saved annotation is clicked outside annotate
   * mode: opens the inline editor at `anchor` when the app can update
   * annotations, else falls back to `onAnnotationClick`. Null when neither.
   */
  openAnnotation: ((threadId: string, componentIndex: string, anchor?: ClientPoint | null) => void) | null;
  /** The annotation edited in place (at most one), or null. */
  editing: InlineAnnotationEdit | null;
  /** Saved version of the annotation in `editing` (null with it). */
  editingAnnotation: Annotation | null;
  closeEditor: () => void;
  /** Stores the inline edit. Rejects on failure (the editor stays open). */
  saveEdit: (patch: AnnotationPatchInput) => Promise<void>;
  /** Deletes the thread being edited; null when the app does not allow it. */
  deleteEdited: (() => Promise<void>) | null;
  /** Closes the inline editor and opens the thread's discussion; null when not handled. */
  openDiscussion: (() => void) | null;
  /** Unsaved changes of an open annotation editor, drawn in place of the saved version. */
  editDraft: AnnotationEditDraft | null;
  /**
   * Editors push their unsaved changes here as they change; an empty patch
   * (or null) clears that thread's draft. Stable identity.
   */
  setEditDraft: (threadId: string, patch: AnnotationPatchInput | null) => void;
  /**
   * Renderers report the counts measured on their data (see
   * `AnnotationStats`), per thread id. Stable identity; unchanged maps are
   * not forwarded.
   */
  reportStats: (componentIndex: string, stats: Record<string, AnnotationStats>) => void;
  /**
   * Renderers report whether they can capture annotations right now (a 3D
   * embedding, a multi-panel barplot tab or a table without a row-id column
   * cannot). Stable identity; pass false on unmount.
   */
  reportAnnotatable: (componentIndex: string, annotatable: boolean) => void;
  /** Last value a mounted renderer reported for the component (false when none). */
  isAnnotatable: (componentIndex: string) => boolean;
}

export const AnnotationLayerContext = createContext<AnnotationLayerControl | null>(null);

export function useAnnotationLayer(): AnnotationLayerControl | null {
  return useContext(AnnotationLayerContext);
}

const EMPTY: RenderableAnnotation[] = [];

export interface AnnotationLayerProviderProps {
  /** Drawable annotations per component index. */
  items: Record<string, RenderableAnnotation[]>;
  highlightId?: string | null;
  canAnnotate: boolean;
  annotate?: AnnotateState | null;
  setAnnotate?: (componentIndex: string | null, tool?: AnnotateTool | null) => void;
  /** Stores a new annotation on a component. Required when `canAnnotate`. */
  onSave?: (componentIndex: string, draft: AnnotationDraft) => Promise<void>;
  /**
   * Opens a saved annotation's discussion: on click when there is no
   * `onAnnotationUpdate`, else from the inline editor's "Open discussion".
   */
  onAnnotationClick?: (threadId: string, componentIndex: string) => void;
  /**
   * Stores an annotation edited in place on its component. Rejects on
   * failure (the editor stays open). Without it a click opens the discussion.
   */
  onAnnotationUpdate?: (threadId: string, componentIndex: string, patch: AnnotationPatchInput) => Promise<void>;
  /** Deletes an annotation's thread from the inline editor. Rejects on failure. */
  onAnnotationDelete?: (threadId: string, componentIndex: string) => Promise<void>;
  /**
   * Counts measured on a component's data, per thread id, whenever they
   * change (points marked / found, data points inside a range).
   */
  onStats?: (componentIndex: string, stats: Record<string, AnnotationStats>) => void;
  children: React.ReactNode;
}

const noop = () => undefined;
const EMPTY_ANNOTATABLE: Record<string, boolean> = {};

/** `prev` with the component's flag set; `prev` itself when unchanged. */
export function withAnnotatable(
  prev: Record<string, boolean>,
  componentIndex: string,
  value: boolean,
): Record<string, boolean> {
  if (value ? prev[componentIndex] === true : !(componentIndex in prev)) return prev;
  const next = { ...prev };
  if (value) next[componentIndex] = true;
  else delete next[componentIndex];
  return next;
}

/**
 * Builds the layer control from plain values and owns the pending capture,
 * so the app only supplies the items, the annotate-mode state and a save
 * callback.
 */
export const AnnotationLayerProvider: React.FC<AnnotationLayerProviderProps> = ({
  items,
  highlightId = null,
  canAnnotate,
  annotate = null,
  setAnnotate,
  onSave,
  onAnnotationClick,
  onAnnotationUpdate,
  onAnnotationDelete,
  onStats,
  children,
}) => {
  const [pending, setPending] = useState<PendingAnnotation | null>(null);
  // The draft patch is tied to the capture it was typed for, so a new capture
  // never shows the previous label.
  const [draftPatch, setDraftPatch] = useState<{ for: PendingAnnotation; patch: PendingDraftPatch } | null>(
    null,
  );
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const updatePendingDraft = useCallback((patch: PendingDraftPatch) => {
    const p = pendingRef.current;
    if (!p) return;
    setDraftPatch((prev) => ({ for: p, patch: { ...(prev?.for === p ? prev.patch : {}), ...patch } }));
  }, []);
  const pendingDraft = useMemo<PendingDraft | null>(
    () =>
      pending
        ? { ...initialPendingDraft(pending), ...(draftPatch?.for === pending ? draftPatch.patch : {}) }
        : null,
    [pending, draftPatch],
  );

  const onStatsRef = useRef(onStats);
  onStatsRef.current = onStats;
  const reportedStats = useRef<Record<string, Record<string, AnnotationStats>>>({});
  const reportStats = useCallback((componentIndex: string, stats: Record<string, AnnotationStats>) => {
    const prev = reportedStats.current[componentIndex];
    // Nothing to tell about a component that never had counts.
    if (prev === undefined && Object.keys(stats).length === 0) return;
    if (sameStats(prev, stats)) return;
    reportedStats.current[componentIndex] = stats;
    onStatsRef.current?.(componentIndex, stats);
  }, []);
  const [annotatable, setAnnotatable] = useState<Record<string, boolean>>(EMPTY_ANNOTATABLE);
  const reportAnnotatable = useCallback((componentIndex: string, value: boolean) => {
    setAnnotatable((prev) => withAnnotatable(prev, componentIndex, value));
  }, []);
  const effectiveAnnotate = canAnnotate ? annotate : null;

  // ── Editing a saved annotation: the inline editor (one at a time) and the
  // unsaved changes of whichever editor is open, drawn live on the component.
  const [editDraft, setEditDraftState] = useState<AnnotationEditDraft | null>(null);
  const setEditDraft = useCallback((threadId: string, patch: AnnotationPatchInput | null) => {
    setEditDraftState((prev) => nextEditDraft(prev, threadId, patch));
  }, []);
  const [editingState, setEditing] = useState<InlineAnnotationEdit | null>(null);
  const editingAnnotation = editingState
    ? ((items[editingState.componentIndex] ?? EMPTY).find((i) => i.id === editingState.threadId)?.annotation ??
      null)
    : null;
  // A thread that disappeared (deleted, filtered out) closes its editor.
  const editing = editingAnnotation ? editingState : null;
  const editingRef = useRef(editingState);
  editingRef.current = editingState;
  const closeEditor = useCallback(() => {
    const e = editingRef.current;
    if (!e) return;
    setEditDraft(e.threadId, null);
    setEditing(null);
  }, [setEditDraft]);

  // Leaving annotate mode (or moving it to another component) drops the shape
  // that was waiting for a label.
  useEffect(() => {
    setPending((p) =>
      p && (!effectiveAnnotate || effectiveAnnotate.componentIndex !== p.componentIndex) ? null : p,
    );
  }, [effectiveAnnotate]);
  // Entering annotate mode closes the inline editor: clicks belong to the tools.
  useEffect(() => {
    if (effectiveAnnotate) closeEditor();
  }, [effectiveAnnotate, closeEditor]);

  const openAnnotation = useMemo(() => {
    if (onAnnotationUpdate) {
      return (threadId: string, componentIndex: string, anchor: ClientPoint | null = null) =>
        setEditing({ threadId, componentIndex, anchor });
    }
    return onAnnotationClick ?? null;
  }, [onAnnotationUpdate, onAnnotationClick]);

  const saveEdit = useCallback(
    async (patch: AnnotationPatchInput) => {
      if (!editing || !onAnnotationUpdate) return;
      await onAnnotationUpdate(editing.threadId, editing.componentIndex, patch);
      closeEditor();
    },
    [editing, onAnnotationUpdate, closeEditor],
  );
  const deleteEdited = useMemo(
    () =>
      editing && onAnnotationDelete
        ? async () => {
            await onAnnotationDelete(editing.threadId, editing.componentIndex);
            closeEditor();
          }
        : null,
    [editing, onAnnotationDelete, closeEditor],
  );
  const openDiscussion = useMemo(
    () =>
      editing && onAnnotationClick
        ? () => {
            closeEditor();
            onAnnotationClick(editing.threadId, editing.componentIndex);
          }
        : null,
    [editing, onAnnotationClick, closeEditor],
  );
  const drawnItems = useMemo(() => itemsWithEditDraft(items, editDraft), [items, editDraft]);

  const onCaptured = useCallback(
    (componentIndex: string, geometry: Geometry, kind: AnnotationKind, variant?: string | null) => {
      if (!canAnnotate) return;
      // One label at a time: a second gesture while the popover is open is ignored.
      setPending((p) => p ?? { componentIndex, geometry, kind, ...(variant ? { variant } : {}) });
    },
    [canAnnotate],
  );

  const cancelPending = useCallback(() => setPending(null), []);

  const savePending = useCallback(
    async (draft: AnnotationDraft) => {
      if (!pending || !onSave) return;
      await onSave(pending.componentIndex, withPendingVariant(draft, pending));
      setPending(null);
    },
    [pending, onSave],
  );

  const value = useMemo<AnnotationLayerControl>(
    () => ({
      itemsFor: (componentIndex) => drawnItems[componentIndex] ?? EMPTY,
      // The annotation being edited is drawn emphasised, wherever it is edited.
      highlightId: editing?.threadId ?? editDraft?.threadId ?? highlightId,
      canAnnotate,
      annotate: effectiveAnnotate,
      setAnnotate: canAnnotate && setAnnotate ? setAnnotate : noop,
      pending,
      onCaptured,
      cancelPending,
      savePending,
      pendingDraft,
      updatePendingDraft,
      onAnnotationClick: onAnnotationClick ?? null,
      openAnnotation,
      editing,
      editingAnnotation,
      closeEditor,
      saveEdit,
      deleteEdited,
      openDiscussion,
      editDraft,
      setEditDraft,
      reportStats,
      reportAnnotatable,
      isAnnotatable: (componentIndex) => annotatable[componentIndex] === true,
    }),
    [
      drawnItems,
      highlightId,
      canAnnotate,
      effectiveAnnotate,
      setAnnotate,
      pending,
      onCaptured,
      cancelPending,
      savePending,
      pendingDraft,
      updatePendingDraft,
      onAnnotationClick,
      openAnnotation,
      editing,
      editingAnnotation,
      closeEditor,
      saveEdit,
      deleteEdited,
      openDiscussion,
      editDraft,
      setEditDraft,
      reportStats,
      reportAnnotatable,
      annotatable,
    ],
  );

  return <AnnotationLayerContext.Provider value={value}>{children}</AnnotationLayerContext.Provider>;
};
