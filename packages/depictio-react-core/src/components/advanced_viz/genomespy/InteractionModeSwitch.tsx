import React from 'react';

import PointerModeSwitch from '../controls/PointerModeSwitch';
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

/** The genome view's interaction mode: what the pointer does on the genome axis. */
const InteractionModeSwitch: React.FC<Props> = ({ value, onChange, selectEnabled }) => (
  <PointerModeSwitch
    value={value}
    onChange={onChange}
    testId="genome-view-interaction-mode"
    testIdPrefix="genome-view-mode"
    modes={INTERACTION_MODES.map((mode) => ({
      value: mode,
      ...MODE_LABELS[mode],
      disabledReason:
        mode === 'select' && !selectEnabled
          ? 'Select is off: this tile does not filter on a region.'
          : null,
    }))}
  />
);

export default InteractionModeSwitch;
