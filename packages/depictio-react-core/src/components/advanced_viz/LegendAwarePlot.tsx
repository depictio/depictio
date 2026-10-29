import React, { createContext, useContext, useMemo } from 'react';
import Plot from 'react-plotly.js';

import { tintSingleSeries } from '../../figureTint';
import { useTabHue } from '../../tabColor';

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
  // A single-series figure that still wears the template's default colour is
  // drawn in the tab's hue (figureTint); anything coloured by data is left be.
  const tabHue = useTabHue();
  const tinted = useMemo(
    () =>
      tintSingleSeries(
        props.data as unknown[],
        props.layout as Record<string, unknown> | undefined,
        tabHue,
      ),
    [props.data, props.layout, tabHue],
  );
  const layout = useMemo(
    () => (hide ? { ...tinted.layout, showlegend: false } : tinted.layout),
    [hide, tinted],
  );
  return <Plot {...props} data={tinted.data as never} layout={layout as never} />;
};

export default LegendAwarePlot;
