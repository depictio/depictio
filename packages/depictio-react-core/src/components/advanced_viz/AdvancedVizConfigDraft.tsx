import React, { createContext, useContext } from 'react';

/**
 * Carries a Tier-2 control change from inside a renderer back out to whoever
 * owns the component's config.
 *
 * The renderers have always held their settings in plain local state, so a
 * threshold or a top-N the author tuned was thrown away on the next remount: a
 * refresh, a filter change, a scroll back into view under LazyMount. The
 * settings popover was a viewing aid that looked like an editor.
 *
 * A null context (the default) means nobody owns the config, and a control
 * change stays local exactly as it does today. Only a surface that can persist
 * the result provides a sink, which is what makes writing from a read-only
 * surface structurally impossible rather than merely discouraged.
 *
 * Kept in its own module, free of renderer imports, so a provider can be
 * mounted without pulling the plotly-heavy advanced_viz lazy chunk onto the
 * importer's boot path. Same shape and the same reasons as
 * `AdvancedVizInspectorBridge`.
 */
export type VizConfigPatch = Record<string, unknown>;

/** `componentIndex` identifies which component the patch belongs to. A builder
 *  preview owns exactly one and can ignore it; a dashboard-wide sink cannot. */
export type VizConfigDraftSink = (componentIndex: string, patch: VizConfigPatch) => void;

export const AdvancedVizConfigDraftContext = createContext<VizConfigDraftSink | null>(null);

export const AdvancedVizConfigDraftProvider: React.FC<{
  value: VizConfigDraftSink | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <AdvancedVizConfigDraftContext.Provider value={value}>
    {children}
  </AdvancedVizConfigDraftContext.Provider>
);

export function useAdvancedVizConfigDraft(): VizConfigDraftSink | null {
  return useContext(AdvancedVizConfigDraftContext);
}
