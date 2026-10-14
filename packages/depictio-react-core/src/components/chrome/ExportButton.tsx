import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { TILE_ACTION_STYLE } from './actionStyles';
import type { ComponentExportTarget } from './ExportContext';

interface ExportButtonProps {
  target: ComponentExportTarget;
  onOpen: (target: ComponentExportTarget) => void;
}

/**
 * Opens the app's export dialog on this component: its API URL as a Plotly
 * spec or as a self-contained page, ready to copy. Only rendered when the app
 * provides a `ComponentExportContext`, i.e. when the server's export API is on.
 */
const ExportButton: React.FC<ExportButtonProps> = ({ target, onOpen }) => (
  <Tooltip label={TILE_ACTION_STYLE.export.label} withArrow>
    <ActionIcon
      variant="subtle"
      color={TILE_ACTION_STYLE.export.color}
      size="sm"
      onClick={() => onOpen(target)}
      aria-label={TILE_ACTION_STYLE.export.label}
      data-testid="tile-export"
    >
      <Icon icon={TILE_ACTION_STYLE.export.icon} width={16} height={16} />
    </ActionIcon>
  </Tooltip>
);

export default ExportButton;
