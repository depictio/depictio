import { create } from 'zustand';
import type { AdvancedVizExtrasPayload } from 'depictio-react-core';

/**
 * Chrome state shared by the viewer and the editor: which component the
 * inspector is showing, and whether it is open.
 *
 * Deliberately does NOT own the filter panel's open/width state. Those live in
 * `useFilterPanelOpen` / `useFilterPanelWidth`, which already own their
 * localStorage keys and the panel-toggle event; a second owner here would mean
 * two sources of truth for one panel.
 */
export type InspectorTab = 'controls' | 'data' | 'info' | 'notes';

/** What the comments drawer lists: one component's threads, or the whole tab. */
export type CommentsScope = 'component' | 'tab';
/** Which threads the comments drawer lists: plain comments, or figure annotations. */
export type CommentsView = 'comments' | 'annotations';
/** Drawing tool of the annotate mode (same union as react-core's `AnnotateTool`). */
export type AnnotateTool = 'range' | 'line' | 'points' | 'note';

interface UiState {
  /** `StoredMetadata.index` of the inspected component, or null for none. */
  selectedComponentId: string | null;
  inspectorOpen: boolean;
  inspectorTab: InspectorTab;
  /**
   * What each advanced-viz renderer published about itself, keyed by component.
   *
   * Lives here rather than in App state so a renderer republishing (on every
   * settings tweak) doesn't re-render the whole dashboard — only the inspector
   * subscribes to this slice.
   */
  advancedVizExtras: Record<string, AdvancedVizExtrasPayload | null>;
  /** Comments drawer. `commentsComponentIndex` is the component the
   *  "This component" scope shows, kept when switching to the tab scope so
   *  switching back returns to it. */
  commentsOpen: boolean;
  commentsScope: CommentsScope;
  commentsComponentIndex: string | null;
  commentsView: CommentsView;
  /** Thread last clicked in the drawer, highlighted until another is. */
  focusedThreadId: string | null;
  /** Annotation thread whose inline editor is open in the drawer. */
  editingAnnotationThreadId: string | null;
  /** Bumped to ask the drawer to scroll the focused thread into view. */
  threadScrollRequest: number;
  /** Component in annotate mode, and the active drawing tool. */
  annotateComponentIndex: string | null;
  annotateTool: AnnotateTool | null;
}

interface UiActions {
  /** Selecting a component opens the inspector; re-selecting the one already
   *  shown closes it, so the same chrome button toggles rather than sticking. */
  inspectComponent: (componentId: string) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  closeInspector: () => void;
  /** Called by `AdvancedVizDispatch` via the inspector bridge. */
  publishAdvancedVizExtras: (
    componentId: string,
    payload: AdvancedVizExtrasPayload | null,
  ) => void;
  /** Opens the comments drawer on a component, or on the whole tab (null). */
  openComments: (componentIndex?: string | null) => void;
  closeComments: () => void;
  setCommentsScope: (scope: CommentsScope) => void;
  setCommentsView: (view: CommentsView) => void;
  setFocusedThread: (threadId: string | null) => void;
  setEditingAnnotation: (threadId: string | null) => void;
  /** An annotation clicked on a chart: opens the drawer on its component, in
   *  the annotations view, with the thread focused and its editor open. */
  editAnnotation: (threadId: string, componentIndex: string) => void;
  setAnnotate: (componentIndex: string | null, tool?: AnnotateTool | null) => void;
  /** Drops every comments/annotate state: called when the dashboard changes,
   *  so nothing from the previous dashboard leaks into the next one. */
  resetComments: () => void;
}

const INITIAL: UiState = {
  selectedComponentId: null,
  inspectorOpen: false,
  inspectorTab: 'info',
  advancedVizExtras: {},
  commentsOpen: false,
  commentsScope: 'tab',
  commentsComponentIndex: null,
  commentsView: 'comments',
  focusedThreadId: null,
  editingAnnotationThreadId: null,
  threadScrollRequest: 0,
  annotateComponentIndex: null,
  annotateTool: null,
};

export const useUiStore = create<UiState & UiActions>((set) => ({
  ...INITIAL,
  inspectComponent: (componentId) =>
    set((s) =>
      s.inspectorOpen && s.selectedComponentId === componentId
        ? { inspectorOpen: false, selectedComponentId: null }
        : { inspectorOpen: true, selectedComponentId: componentId },
    ),
  setInspectorTab: (tab) => set({ inspectorTab: tab }),
  closeInspector: () => set({ inspectorOpen: false }),
  publishAdvancedVizExtras: (componentId, payload) =>
    set((s) =>
      // Bail on an unchanged value: a renderer's cleanup publishes null on
      // unmount, and without this an already-absent entry would still swap the
      // map identity and re-render the inspector.
      s.advancedVizExtras[componentId] === payload
        ? s
        : { advancedVizExtras: { ...s.advancedVizExtras, [componentId]: payload } },
    ),
  openComments: (componentIndex) =>
    set((s) =>
      componentIndex
        ? { commentsOpen: true, commentsScope: 'component', commentsComponentIndex: componentIndex }
        : {
            commentsOpen: true,
            commentsScope: 'tab',
            commentsComponentIndex: s.commentsComponentIndex,
          },
    ),
  closeComments: () =>
    set({
      commentsOpen: false,
      focusedThreadId: null,
      editingAnnotationThreadId: null,
      commentsComponentIndex: null,
    }),
  setCommentsScope: (scope) => set({ commentsScope: scope }),
  setCommentsView: (view) => set({ commentsView: view }),
  setFocusedThread: (threadId) => set({ focusedThreadId: threadId }),
  setEditingAnnotation: (threadId) => set({ editingAnnotationThreadId: threadId }),
  editAnnotation: (threadId, componentIndex) =>
    set((s) => ({
      commentsOpen: true,
      commentsScope: 'component',
      commentsComponentIndex: componentIndex,
      commentsView: 'annotations',
      focusedThreadId: threadId,
      editingAnnotationThreadId: threadId,
      threadScrollRequest: s.threadScrollRequest + 1,
    })),
  setAnnotate: (componentIndex, tool = null) =>
    set({ annotateComponentIndex: componentIndex, annotateTool: componentIndex ? tool : null }),
  resetComments: () =>
    set({
      commentsOpen: false,
      commentsScope: 'tab',
      commentsComponentIndex: null,
      commentsView: 'comments',
      focusedThreadId: null,
      editingAnnotationThreadId: null,
      annotateComponentIndex: null,
      annotateTool: null,
    }),
}));

export default useUiStore;
