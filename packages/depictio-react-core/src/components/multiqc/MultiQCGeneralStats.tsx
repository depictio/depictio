import React from 'react';
import { Paper, Text, Stack } from '@mantine/core';

import { StoredMetadata } from '../../api';

interface MultiQCGeneralStatsProps {
  dashboardId: string;
  metadata: StoredMetadata;
}

/**
 * Placeholder for the MultiQC General Statistics table + violin plot.
 *
 * The Dash version (`build_general_stats_content` in
 * `multiqc_component/general_stats.py`) returns a `dash_table.DataTable` tree
 * directly — not a JSON-serializable shape. Porting cleanly requires extracting
 * a sibling pure function that returns `{rows, columns, violins}` JSON. That
 * surgical refactor is suggested in the report but **not yet applied**, so this
 * component intentionally renders a placeholder. Regular MultiQC Plotly plots
 * already work via `MultiQCFigure`.
 */
const MultiQCGeneralStats: React.FC<MultiQCGeneralStatsProps> = ({ metadata }) => {
  const titleText =
    (metadata.title as string | undefined) || 'MultiQC General Statistics';

  return (
    <Paper p="sm" withBorder radius="md" style={{ minHeight: 200 }}>
      <Stack gap="xs">
        <Text fw={600} size="sm">
          {titleText}
        </Text>
        <Text size="sm" c="dimmed">
          General Stats not yet ported to the React viewer. The regular MultiQC
          plots are available — open this component in the Dash viewer to see
          the colorized table and violin overlay.
        </Text>
      </Stack>
    </Paper>
  );
};

export default MultiQCGeneralStats;
