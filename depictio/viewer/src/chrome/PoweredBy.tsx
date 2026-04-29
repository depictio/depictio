import React from 'react';
import { Anchor, Group, Text } from '@mantine/core';

import { useColorScheme } from '../hooks/useColorScheme';

/**
 * "Powered by Depictio" badge — themed Depictio logo + label, linking to docs.
 * Visual parity with `_create_powered_by_section()` in
 * `depictio/dash/layouts/header.py`.
 */
interface PoweredByProps {
  /** When true, renders the right-border + right-padding seen in the Dash header. */
  withRightBorder?: boolean;
}

const PoweredBy: React.FC<PoweredByProps> = ({ withRightBorder = false }) => {
  const { colorScheme } = useColorScheme();

  // Both `logo_black.svg` and `logo_white.svg` are byte-identical (a base64-
  // embedded PNG inside an SVG wrapper), so swapping `src` does nothing.
  // Apply a CSS filter on dark mode to invert the embedded raster while
  // preserving brand hues — the standard treatment for single-asset wordmarks.
  const groupStyle: React.CSSProperties = withRightBorder
    ? {
        marginRight: 15,
        paddingRight: 15,
        borderRight: '1px solid var(--mantine-color-default-border)',
      }
    : {};

  return (
    <Anchor
      href="https://depictio.github.io/depictio-docs/"
      target="_blank"
      rel="noopener noreferrer"
      underline="never"
      style={{ color: 'inherit' }}
    >
      <Group gap={5} align="center" wrap="nowrap" style={groupStyle}>
        <Text size="xs" c="dimmed" fw={700}>
          Powered by
        </Text>
        <img
          src="/dashboard-beta/logos/logo_black.svg"
          alt="Depictio"
          style={{
            height: 20,
            width: 'auto',
            display: 'block',
            filter: colorScheme === 'dark' ? 'invert(1) hue-rotate(180deg)' : undefined,
          }}
        />
      </Group>
    </Anchor>
  );
};

export default PoweredBy;
