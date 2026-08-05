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
}

const INITIAL: UiState = {
  selectedComponentId: null,
  inspectorOpen: false,
  inspectorTab: 'info',
  advancedVizExtras: {},
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
}));

export default useUiStore;
