import React from 'react';
import { Badge, Tooltip } from '@mantine/core';

import { isDataVersionActive, useDataVersions, type DataVersionState } from '../../dataVersions';

/**
 * Component types whose data endpoints do not read data pins: MultiQC reports,
 * JBrowse sessions and every advanced visualisation (record cards included),
 * plus the filter funnel (`funnel`, its overview modal). They draw the latest
 * data whatever the dashboard is pinned to.
 */
const CURRENT_DATA_ONLY_TYPES = new Set(['multiqc', 'jbrowse', 'advanced_viz', 'funnel']);

/** Is this a component type that never reads a data pin? */
export function isCurrentDataOnlyType(componentType: string | null | undefined): boolean {
  return Boolean(componentType) && CURRENT_DATA_ONLY_TYPES.has(componentType as string);
}

/** Does a tile of this type show today's data while the rest of the screen
 *  shows a past version's? */
export function showsCurrentDataOnly(componentType: string, state: DataVersionState): boolean {
  return isCurrentDataOnlyType(componentType) && isDataVersionActive(state);
}

export const CURRENT_DATA_HINT =
  'This component cannot show past data: it reads the latest data while the rest of the ' +
  'dashboard shows the selected version.';

/**
 * Says so on the tile. A banner naming a version over a tile that ignores it
 * would otherwise let the tile pass for the past. Renders nothing while no
 * data version is active, so a live dashboard is unchanged.
 */
export const CurrentDataBadge: React.FC<{ componentType: string }> = ({ componentType }) => {
  const state = useDataVersions();
  if (!showsCurrentDataOnly(componentType, state)) return null;
  return (
    <Tooltip label={CURRENT_DATA_HINT} withArrow multiline w={260}>
      <Badge size="xs" variant="default" data-testid="current-data-badge">
        Current data
      </Badge>
    </Tooltip>
  );
};

export default CurrentDataBadge;
