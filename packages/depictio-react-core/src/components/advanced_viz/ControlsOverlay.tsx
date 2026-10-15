import React from 'react';
import { ActionIcon, Paper } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useChromeStyle } from '../../chrome';
import './controlsDock.css';
import './controlsOverlay.css';

/**
 * A renderer's controls floating over its plot, top right, for a tile with no
 * room to dock them (see `overlay` in controlsDock.ts).
 *
 * Absolutely positioned in the plot's slot, so the figure keeps its full size:
 * nothing here takes part in the tile's layout. The panel is capped at the
 * slot's height and its body scrolls under a header that stays, with a close
 * button. Every control of the tile is listed, as in the settings popover: the
 * "More options" fold is for panels that share their row or column with the
 * plot.
 */
const ControlsOverlay: React.FC<{
  controls: React.ReactNode;
  /** A view switch a router put ahead of the controls (see `ControlsLeadContext`). */
  lead?: React.ReactNode;
  onClose: () => void;
}> = ({ controls, lead, onClose }) => {
  const style = useChromeStyle();
  return (
    <Paper
      className="dpx-viz-overlay"
      shadow="md"
      withBorder
      role="region"
      aria-label="Viz controls"
      data-testid="viz-controls-overlay"
    >
      <div className="dpx-viz-overlay__head">
        <span className="dpx-viz-dock__title">
          <Icon icon="tabler:adjustments-horizontal" width={13} height={13} />
          Controls
        </span>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="xs"
          radius={style.radius}
          aria-label="Close controls"
          title="Close controls"
          onClick={onClose}
          data-testid="viz-controls-overlay-close"
        >
          <Icon icon="tabler:x" width={12} height={12} />
        </ActionIcon>
      </div>
      <div className="dpx-viz-overlay__body">
        {lead ? <div className="dpx-viz-overlay__lead">{lead}</div> : null}
        {controls}
      </div>
    </Paper>
  );
};

export default ControlsOverlay;
