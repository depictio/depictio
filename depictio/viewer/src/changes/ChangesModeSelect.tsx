import React from 'react';
import { SegmentedControl } from '@mantine/core';

import type { MarkMode } from 'depictio-react-core';

const OPTIONS = [
  { value: 'sticky', label: 'Until I mark them seen' },
  { value: 'previous_visit', label: 'Since my previous visit' },
];

/** When "changed" restarts: only when the reader says so, or at every visit. */
const ChangesModeSelect: React.FC<{
  value: MarkMode;
  onChange: (mode: MarkMode) => void;
  fullWidth?: boolean;
}> = ({ value, onChange, fullWidth = true }) => (
  <SegmentedControl
    size="xs"
    fullWidth={fullWidth}
    data={OPTIONS}
    value={value}
    onChange={(v) => onChange(v as MarkMode)}
    aria-label="What counts as changed"
    data-testid="changes-mode"
  />
);

export default ChangesModeSelect;
