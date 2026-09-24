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
  /** Thread last clicked in the drawer, highlighted until another is. */
  focusedThreadId: string | null;
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
  setFocusedThread: (threadId: string | null) => void;
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
  focusedThreadId: null,
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
    set({ commentsOpen: false, focusedThreadId: null, commentsComponentIndex: null }),
  setCommentsScope: (scope) => set({ commentsScope: scope }),
  setFocusedThread: (threadId) => set({ focusedThreadId: threadId }),
  setAnnotate: (componentIndex, tool = null) =>
    set({ annotateComponentIndex: componentIndex, annotateTool: componentIndex ? tool : null }),
  resetComments: () =>
    set({
      commentsOpen: false,
      commentsScope: 'tab',
      commentsComponentIndex: null,
      focusedThreadId: null,
      annotateComponentIndex: null,
      annotateTool: null,
    }),
}));

export default useUiStore;
