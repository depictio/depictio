import React from 'react';
import { Anchor, Group, Text } from '@mantine/core';

import DepictioLogo from './DepictioLogo';

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
        <DepictioLogo height={20} />
      </Group>
    </Anchor>
  );
};

export default PoweredBy;
