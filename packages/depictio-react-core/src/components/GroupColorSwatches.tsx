import React from 'react';
import { ColorSwatch, Group } from '@mantine/core';

import { TAB10_PALETTE } from '../colors';

/**
 * The selection-group palette as a clickable swatch row.
 *
 * Shared by every place a group's color is picked — the Analysis panel's
 * create and rename popovers and the per-component "save selection as group"
 * chrome action — so the selected-swatch affordance stays identical across
 * them. `value` is the *effective* color (the pending pick, or the default the
 * group would get), not necessarily an explicit user choice.
 */
const GroupColorSwatches: React.FC<{
  value: string;
  onSelect: (color: string) => void;
  mt?: number;
}> = ({ value, onSelect, mt }) => (
  <Group gap={4} mt={mt} wrap="wrap">
    {TAB10_PALETTE.map((c) => (
      <ColorSwatch
        key={c}
        color={c}
        size={16}
        style={{
          cursor: 'pointer',
          outline: value === c ? '2px solid var(--mantine-color-blue-5)' : 'none',
          outlineOffset: 1,
        }}
        onClick={() => onSelect(c)}
      />
    ))}
  </Group>
);

export default GroupColorSwatches;
