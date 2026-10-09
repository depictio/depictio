import React, { createContext, useContext, useMemo } from 'react';
import Plot from 'react-plotly.js';

/**
 * Whether the advanced viz drawn below hides its Plotly legend: the tile's
 * `hide_legend`, which a highlight takes over from its source. The renderers
 * build their own layouts and know nothing of it, so the dispatch provides it
 * and every renderer's `Plot` reads it here.
 */
export const HideLegendContext = createContext(false);

/** react-plotly.js's `Plot`, with `showlegend: false` when the tile asks. */
const LegendAwarePlot: React.FC<React.ComponentProps<typeof Plot>> = (props) => {
  const hide = useContext(HideLegendContext);
  const layout = useMemo(
    () => (hide ? { ...props.layout, showlegend: false } : props.layout),
    [hide, props.layout],
  );
  return <Plot {...props} layout={layout} />;
};

export default LegendAwarePlot;
