import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';

import { adaptGlTraces, PlotlyTrace, useWebglSlot } from '../../webglBudget';
import { useGestureGuardedSelection } from './selectionGesture';

/**
 * `react-plotly.js`'s `Plot` with the WebGL budget applied to its traces.
 *
 * Renderers that draw one marker cloud and nothing else can swap `Plot` for
 * this and get the fallback for free — see webglBudget for why a page can only
 * hold about five `scattergl` plots. Volcano, MA and Manhattan call
 * {@link useWebglSlot} directly instead, because their reduction badge has to
 * report how many points ended up on screen.
 *
 * `scatter3d` counts toward the budget but cannot be downgraded — there is no
 * SVG 3D renderer. A 3D plot that misses out still draws, so a dashboard
 * combining five marker clouds *and* a 3D embedding can still lose a context.
 *
 * `onSelected` is gesture-guarded (see selectionGesture): the empty
 * re-selection every `Plotly.react` emits never reaches the renderer.
 */
const AdvancedVizPlot: React.FC<
  { data: unknown[] } & Omit<React.ComponentProps<typeof Plot>, 'data'>
> = ({ data, onSelected, onSelecting, ...rest }) => {
  const guarded = useGestureGuardedSelection(onSelected);
  const handleSelecting = (event: Parameters<NonNullable<typeof onSelecting>>[0]) => {
    guarded.onSelecting?.();
    onSelecting?.(event);
  };
  const traces = (data as PlotlyTrace[]) || [];
  // Asked from the trace types rather than unconditionally: these renderers
  // appear once per dashboard, so acquisition order hardly matters, while
  // holding a slot for a plot that turned out to be SVG-native (a small
  // phylogeny, a subplot grid) would deny it to one that needs it.
  const needsGl = traces.some((t) => t?.type === 'scattergl' || t?.type === 'scatter3d');
  const glGranted = useWebglSlot(needsGl);
  const adapted = useMemo(() => adaptGlTraces(traces, glGranted), [data, glGranted]);
  return (
    <Plot
      data={adapted as never}
      {...rest}
      onSelecting={onSelected || onSelecting ? handleSelecting : undefined}
      onSelected={guarded.onSelected}
    />
  );
};

export default AdvancedVizPlot;
