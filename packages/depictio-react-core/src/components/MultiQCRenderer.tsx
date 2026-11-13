import React from 'react';

import { InteractiveFilter, StoredMetadata } from '../api';
import MultiQCFigure from './multiqc/MultiQCFigure';

interface MultiQCRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
}

/**
 * Top-level dispatcher for MultiQC components.
 *
 * `MultiQCFigure` reads `selected_module` / `selected_plot` from
 * stored_metadata and routes "general_stats" to `MultiQCGeneralStats`,
 * everything else to a regular Plotly figure backed by the pure
 * `create_multiqc_plot()` Python helper.
 */
const MultiQCRenderer: React.FC<MultiQCRendererProps> = ({
  dashboardId,
  metadata,
  filters,
  refreshTick,
}) => (
  // MultiQCFigure routes General Stats itself, and owns the "what's new"
  // split, so both kinds go through it.
  <MultiQCFigure
    dashboardId={dashboardId}
    metadata={metadata}
    filters={filters}
    refreshTick={refreshTick}
  />
);

export default MultiQCRenderer;
