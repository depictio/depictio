import React from 'react';

import { InteractiveFilter, StoredMetadata } from '../api';
import MultiQCFigure from './multiqc/MultiQCFigure';
import MultiQCGeneralStats from './multiqc/MultiQCGeneralStats';

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
 * Reads `selected_module` / `selected_plot` from stored_metadata and routes:
 *   - "general_stats" (either field) → `MultiQCGeneralStats` (stretch goal,
 *     currently a placeholder; regular plots ship first)
 *   - everything else → `MultiQCFigure` (regular Plotly figure backed by
 *     the pure `create_multiqc_plot()` Python helper)
 */
const MultiQCRenderer: React.FC<MultiQCRendererProps> = ({
  dashboardId,
  metadata,
  filters,
  refreshTick,
}) => {
  const selectedModule = metadata.selected_module as string | undefined;
  const selectedPlot = metadata.selected_plot as string | undefined;
  const isGeneralStats =
    selectedModule === 'general_stats' || selectedPlot === 'general_stats';

  if (isGeneralStats) {
    return (
      <MultiQCGeneralStats
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        refreshTick={refreshTick}
      />
    );
  }

  return (
    <MultiQCFigure
      dashboardId={dashboardId}
      metadata={metadata}
      filters={filters}
      refreshTick={refreshTick}
    />
  );
};

export default MultiQCRenderer;
