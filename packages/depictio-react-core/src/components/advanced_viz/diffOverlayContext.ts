import { createContext } from 'react';

import type { ComponentDiff } from '../../api';

/**
 * The before/after of the advanced viz drawn below, when the reader switched
 * "Compare with last visit" on (#1397). `AdvancedVizDispatch` provides it and
 * the shared `LegendAwarePlot` reads it, so a kind that draws rows with their
 * id in `customdata`, `ids` or `text` gets the new rows ringed without a
 * change of its own. Null everywhere else.
 */
export const AdvancedVizDiffContext = createContext<ComponentDiff | null>(null);
