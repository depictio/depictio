import React, { createContext, useContext } from 'react';

import type { ControlsPlacement } from './controlsDock';

/**
 * Carries a change to the component itself (not to its `config`) from inside
 * an advanced-viz tile back out to whoever owns the component.
 *
 * Same rule as `AdvancedVizConfigDraft`: a null context means nobody can
 * persist the result, and the change stays local to the viewer. Only a surface
 * that saves the dashboard (the editor) provides a sink. It is a separate
 * channel because the config sink merges its patch into `stored_metadata[].config`,
 * and a component-level field such as `controls_placement` (`auto | right | top |
 * popover | overlay`) is a sibling of that object, with a different set of
 * values from the config's own `controls_placement` (`popover | rail | header`):
 * sent through the config sink it would land in the wrong place and fail the
 * config's validation.
 *
 * Kept in its own module, free of renderer imports, for the same reason as
 * `AdvancedVizConfigDraft`: a provider can be mounted without pulling the
 * plotly-heavy advanced_viz chunk onto the importer's boot path.
 */
export interface VizComponentPatch {
  /** Where the viz controls sit; null clears it (back to `auto`). */
  controls_placement?: ControlsPlacement | null;
}

/** `componentIndex` identifies which component the patch belongs to. */
export type VizComponentDraftSink = (componentIndex: string, patch: VizComponentPatch) => void;

export const AdvancedVizComponentDraftContext = createContext<VizComponentDraftSink | null>(null);

export const AdvancedVizComponentDraftProvider: React.FC<{
  value: VizComponentDraftSink | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <AdvancedVizComponentDraftContext.Provider value={value}>
    {children}
  </AdvancedVizComponentDraftContext.Provider>
);

export function useAdvancedVizComponentDraft(): VizComponentDraftSink | null {
  return useContext(AdvancedVizComponentDraftContext);
}
