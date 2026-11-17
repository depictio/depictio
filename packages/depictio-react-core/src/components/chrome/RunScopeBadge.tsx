import React from 'react';
import { Badge, Tooltip } from '@mantine/core';

import { useRunUnscoped } from '../../changeMarks';

/** Tiles that read rows: the ones a view on runs narrows or splits. */
const RUN_SCOPED_TYPES = new Set(['figure', 'table', 'card', 'advanced_viz', 'map']);

export const RUN_UNSCOPED_HINT =
  "This dataset's rows carry no run, so What's new shows it whole: it is not narrowed " +
  'to the new runs nor split by run.';

/**
 * "What's new" on runs (epic #1399) narrows, splits or colours each tile by
 * the run of its rows. A collection whose rows carry no run (a sample sheet
 * shared by every run, a table ingested before runs existed) is left whole,
 * which would otherwise read as "all of this is new". Renders nothing while
 * no view on runs is on.
 */
export const RunScopeBadge: React.FC<{ componentType: string; dcId?: string | null }> = ({
  componentType,
  dcId,
}) => {
  const unscoped = useRunUnscoped(dcId);
  if (!unscoped || !RUN_SCOPED_TYPES.has(componentType)) return null;
  return (
    <Tooltip label={RUN_UNSCOPED_HINT} withArrow multiline w={260}>
      <Badge size="xs" variant="default" data-testid="run-unscoped-badge">
        Not filtered by run
      </Badge>
    </Tooltip>
  );
};

export default RunScopeBadge;
