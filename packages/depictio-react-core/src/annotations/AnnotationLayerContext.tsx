import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import type { AnnotateTool } from './layer';
import type { Annotation, AnnotationKind, Geometry, RenderableAnnotation } from './types';

/** A shape just drawn in annotate mode, waiting for its label. */
export interface PendingAnnotation {
  componentIndex: string;
  geometry: Geometry;
  kind: AnnotationKind;
}

/** What the annotation popover hands back on save. */
export interface AnnotationDraft {
  annotation: Annotation;
  /** Optional first comment of the thread. */
  body?: string;
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
  onCaptured: (componentIndex: string, geometry: Geometry, kindHint: AnnotationKind) => void;
  cancelPending: () => void;
  /** Stores the pending annotation. Rejects on failure (the popover stays open). */
  savePending: (draft: AnnotationDraft) => Promise<void>;
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
  children,
}) => {
  const [pending, setPending] = useState<PendingAnnotation | null>(null);
  const [annotatable, setAnnotatable] = useState<Record<string, boolean>>(EMPTY_ANNOTATABLE);
  const reportAnnotatable = useCallback((componentIndex: string, value: boolean) => {
    setAnnotatable((prev) => withAnnotatable(prev, componentIndex, value));
  }, []);
  const effectiveAnnotate = canAnnotate ? annotate : null;

  // Leaving annotate mode (or moving it to another component) drops the shape
  // that was waiting for a label.
  useEffect(() => {
    setPending((p) =>
      p && (!effectiveAnnotate || effectiveAnnotate.componentIndex !== p.componentIndex) ? null : p,
    );
  }, [effectiveAnnotate]);

  const onCaptured = useCallback(
    (componentIndex: string, geometry: Geometry, kind: AnnotationKind) => {
      if (!canAnnotate) return;
      // One label at a time: a second gesture while the popover is open is ignored.
      setPending((p) => p ?? { componentIndex, geometry, kind });
    },
    [canAnnotate],
  );

  const cancelPending = useCallback(() => setPending(null), []);

  const savePending = useCallback(
    async (draft: AnnotationDraft) => {
      if (!pending || !onSave) return;
      await onSave(pending.componentIndex, draft);
      setPending(null);
    },
    [pending, onSave],
  );

  const value = useMemo<AnnotationLayerControl>(
    () => ({
      itemsFor: (componentIndex) => items[componentIndex] ?? EMPTY,
      highlightId,
      canAnnotate,
      annotate: effectiveAnnotate,
      setAnnotate: canAnnotate && setAnnotate ? setAnnotate : noop,
      pending,
      onCaptured,
      cancelPending,
      savePending,
      reportAnnotatable,
      isAnnotatable: (componentIndex) => annotatable[componentIndex] === true,
    }),
    [
      items,
      highlightId,
      canAnnotate,
      effectiveAnnotate,
      setAnnotate,
      pending,
      onCaptured,
      cancelPending,
      savePending,
      reportAnnotatable,
      annotatable,
    ],
  );

  return <AnnotationLayerContext.Provider value={value}>{children}</AnnotationLayerContext.Provider>;
};
