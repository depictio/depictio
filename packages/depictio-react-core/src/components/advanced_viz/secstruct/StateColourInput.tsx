import React, { useEffect, useState } from 'react';
import { ColorInput, isColorValid } from '@mantine/core';

import { useFullscreenPortalTarget } from '../../chrome/useFullscreenPortalTarget';
import { VizInlineField } from '../controls/VizControls';

/**
 * One class's colour: a compact Mantine ColorInput with a swatch popover. What
 * is typed is held here until it is a whole colour, so a half-typed `#1` never
 * reaches the tile (or its saved config); a valid colour is committed at once.
 */
const StateColourInput: React.FC<{
  label: string;
  /** The colour in effect for the class. */
  colour: string;
  swatches: string[];
  onCommit: (colour: string) => void;
}> = ({ label, colour, swatches, onCommit }) => {
  const portalTarget = useFullscreenPortalTarget();
  const [draft, setDraft] = useState<string | null>(null);
  // A colour that changes under the input (Reset, another surface) replaces the draft.
  useEffect(() => setDraft(null), [colour]);
  return (
    <VizInlineField label={label}>
      <ColorInput
        size="xs"
        aria-label={`${label} colour`}
        format="hex"
        withEyeDropper={false}
        popoverProps={{ withinPortal: true, portalProps: { target: portalTarget } }}
        swatches={swatches}
        value={draft ?? colour}
        onChange={(v) => {
          setDraft(v);
          if (v && isColorValid(v)) onCommit(v);
        }}
      />
    </VizInlineField>
  );
};

export default StateColourInput;
