import React from 'react';
import { Text } from '@mantine/core';

import { zoomModifierLabel } from './useWheelZoom';

/**
 * A slider label with a dimmed "(Ctrl + wheel)" suffix, so the modifier-wheel
 * zoom is visible in the control strip and not only in a tooltip. The key is
 * named for the platform: the Command symbol on a Mac, `Ctrl` elsewhere.
 */
const ZoomHintLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <>
    {children}{' '}
    <Text component="span" size="xs" c="dimmed" fw={400}>
      ({zoomModifierLabel()} + wheel)
    </Text>
  </>
);

export default ZoomHintLabel;
