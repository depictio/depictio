/**
 * Keeps a builder's live preview in view while the control column scrolls.
 *
 * The builder pages scroll the window (AppShell adds no scroll container), so
 * `position: sticky` pins the preview under the fixed header while the author
 * opens accordions further down the control column. It sticks within its
 * parent, which therefore has to be as tall as the controls: a stretched grid
 * column, or a flex row where this box is not stretched.
 *
 * Capped at the space between the header and the stepper footer (absent in
 * the edit page, hence the 0px fallbacks), scrolling inside past that, so a
 * preview taller than the viewport keeps its bottom reachable.
 */
import React from 'react';
import { Box } from '@mantine/core';

const GAP = 'var(--mantine-spacing-md)';
const HEADER = 'var(--app-shell-header-offset, 0px)';
const FOOTER = 'var(--app-shell-footer-offset, 0px)';

export const STICKY_TOP = `calc(${HEADER} + ${GAP})`;

const StickyPreview: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box
    data-testid="builder-sticky-preview"
    style={{
      position: 'sticky',
      top: STICKY_TOP,
      maxHeight: `calc(100dvh - ${HEADER} - ${FOOTER} - 2 * ${GAP})`,
      overflowY: 'auto',
    }}
  >
    {children}
  </Box>
);

export default StickyPreview;
