import React, { createContext, useContext } from 'react';
import type { AdvancedVizExtrasPayload } from './AdvancedVizExtras';

/**
 * Carries a framed renderer's published payload up to the app's inspector.
 *
 * A second hop on top of `AdvancedVizExtrasContext`, which only reaches as far
 * as `AdvancedVizDispatch` — deep inside the grid, inside a `LazyMount`. The
 * inspector lives at the app shell, so it needs its own channel.
 *
 * Kept in its own module, free of renderer imports, so the app can import the
 * context without pulling the whole plotly-heavy advanced_viz lazy chunk.
 *
 * A null context (the default) means no inspector: `AdvancedVizDispatch` skips
 * publishing entirely and nothing changes for the popovers.
 */
export type AdvancedVizInspectorPublisher = (
  componentId: string,
  payload: AdvancedVizExtrasPayload | null,
) => void;

export const AdvancedVizInspectorContext = createContext<AdvancedVizInspectorPublisher | null>(
  null,
);

export const AdvancedVizInspectorProvider: React.FC<{
  value: AdvancedVizInspectorPublisher | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <AdvancedVizInspectorContext.Provider value={value}>
    {children}
  </AdvancedVizInspectorContext.Provider>
);

export function useAdvancedVizInspector(): AdvancedVizInspectorPublisher | null {
  return useContext(AdvancedVizInspectorContext);
}
