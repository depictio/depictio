import React from 'react';
import { Center, SegmentedControl, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { INTERACTION_MODES, MODE_LABELS } from './interactionMode';
import type { InteractionMode } from './interactionMode';

interface Props {
  value: InteractionMode;
  onChange: (mode: InteractionMode) => void;
  /** Select draws the region brush: without a host that takes the region
   *  (a read-only preview) or with the region filter off, it is offered
   *  greyed out rather than hidden. */
  selectEnabled: boolean;
}

/**
 * The tile's interaction mode: what the pointer does on the genome axis.
 * Icons with a tooltip each, small enough for the header line; the mode is a
 * tool the reader switches, so it sits there and not in the Settings panel.
 */
const InteractionModeSwitch: React.FC<Props> = ({ value, onChange, selectEnabled }) => (
  <SegmentedControl
    size="xs"
    radius="sm"
    value={value}
    onChange={(v) => onChange(v as InteractionMode)}
    aria-label="Interaction mode"
    data-testid="genome-view-interaction-mode"
    data={INTERACTION_MODES.map((mode) => {
      const meta = MODE_LABELS[mode];
      const disabled = mode === 'select' && !selectEnabled;
      return {
        value: mode,
        disabled,
        label: (
          <Tooltip
            label={disabled ? 'Select is off: this tile does not filter on a region.' : meta.tooltip}
            multiline
            w={220}
            withArrow
            openDelay={250}
          >
            <Center data-testid={`genome-view-mode-${mode}`} aria-label={meta.label}>
              <Icon icon={meta.icon} width={14} />
            </Center>
          </Tooltip>
        ),
      };
    })}
  />
);

export default InteractionModeSwitch;
