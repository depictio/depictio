import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface ClearSelectionButtonProps {
  onClear: () => void;
  /** Values currently selected on the tile; 0 leaves the count out. */
  count?: number;
}

/** Tooltip and accessible name of the tile's clear-selection action. */
export function clearSelectionLabel(count: number | undefined): string {
  return count && count > 0 ? `Clear selection (${count})` : 'Clear selection';
}

/**
 * The one affordance every selection source shares for dropping its own
 * selection: a table's rows, a scatter's lasso, an advanced viz pick or brush.
 *
 * It exists only while the tile has something selected. ComponentChrome puts
 * it in the action row, as the one slot that stays visible without hover, so
 * showing it does not drag the rest of the actions and the row's frame into
 * view. `light` carries its own tint, which is what lets it stand without that
 * frame.
 */
const ClearSelectionButton: React.FC<ClearSelectionButtonProps> = ({ onClear, count }) => {
  const label = clearSelectionLabel(count);
  return (
    <Tooltip label={label} withArrow position="bottom-end">
      <ActionIcon variant="light" color="orange" size="sm" onClick={onClear} aria-label={label}>
        <Icon icon="bx:reset" width={16} height={16} />
      </ActionIcon>
    </Tooltip>
  );
};

export default ClearSelectionButton;
