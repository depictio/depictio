import React from 'react';
import { Group, Stack, Text } from '@mantine/core';

import { useGlassPages } from '../chrome/variants/glass/pages';

export interface Fact {
  label: string;
  value: React.ReactNode;
  /** A multi-line value (a list, a paragraph): the label aligns with its first line. */
  top?: boolean;
}

/**
 * The detail lines of an accordion row. Glass sets them as a definition list,
 * muted terms beside their values; Classic keeps the bold "Label:" lines.
 */
const Facts: React.FC<{ items: Fact[] }> = ({ items }) => {
  const glass = useGlassPages();
  if (glass) {
    return (
      <dl className="ga-facts">
        {items.map((f) => (
          <React.Fragment key={f.label}>
            <dt>{f.label}</dt>
            <dd>{f.value}</dd>
          </React.Fragment>
        ))}
      </dl>
    );
  }
  return (
    <Stack gap="xs">
      {items.map((f) => (
        <Group key={f.label} gap="xs" align={f.top ? 'flex-start' : 'center'}>
          <Text fw="bold" size="sm">
            {f.label}:
          </Text>
          {typeof f.value === 'string' ? <Text size="sm">{f.value}</Text> : f.value}
        </Group>
      ))}
    </Stack>
  );
};

export default Facts;
