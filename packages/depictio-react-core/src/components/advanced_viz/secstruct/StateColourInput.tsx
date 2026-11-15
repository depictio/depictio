import React from 'react';

import { VizColourInput } from '../controls/VizControls';

/** One class's colour: the shared compact colour input (see `VizColourInput`). */
const StateColourInput: React.FC<{
  label: string;
  /** The colour in effect for the class. */
  colour: string;
  swatches: string[];
  onCommit: (colour: string) => void;
}> = ({ label, colour, swatches, onCommit }) => (
  <VizColourInput label={label} value={colour} swatches={swatches} onCommit={onCommit} />
);

export default StateColourInput;
