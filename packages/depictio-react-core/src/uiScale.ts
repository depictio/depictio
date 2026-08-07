import { createContext, useContext } from 'react';

/**
 * Dashboard-wide UI scale (font-size) preference, default 1.0.
 *
 * Mantine surfaces scale through `theme.scale` (the viewer rebuilds its theme
 * from the same value), but Plotly figure fonts and AG Grid row metrics are
 * plain pixel numbers that Mantine never touches — those renderers read this
 * context instead. The provider lives in the viewer app; react-core only
 * defines the channel so shared components stay host-agnostic.
 */
export const UI_SCALE_STEPS = [0.85, 1.0, 1.15, 1.3] as const;
export const UI_SCALE_DEFAULT = 1.0;

export const UiScaleContext = createContext<number>(UI_SCALE_DEFAULT);

export function useUiScale(): number {
  return useContext(UiScaleContext);
}
