import React from 'react';
import { Group, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useGroupingColor } from '../../selectionGroups';

export interface GuideBullet {
  /** Iconify id, drawn on a tinted chip in the grouping colour. */
  icon: string;
  label: string;
  /** What follows the label: a short muted phrase, or nodes such as chips. */
  text?: React.ReactNode;
}

/**
 * Short icon-led lines in place of a paragraph, so the Analysis panel's guide
 * reads at a glance. `inline` lays them out as one row (labels only).
 */
const GuideBullets: React.FC<{ items: GuideBullet[]; inline?: boolean }> = ({
  items,
  inline = false,
}) => {
  const color = useGroupingColor();
  const rows = items.map((item) => (
    <Group key={item.label} gap={8} wrap="nowrap" align="center" className="dc-ap-bullet">
      <ThemeIcon size={22} radius="md" variant="light" color={color} className="dc-ap-bullet-icon">
        <Icon icon={item.icon} width={14} height={14} />
      </ThemeIcon>
      <Group gap={6} wrap="wrap" align="center" style={{ minWidth: 0 }}>
        <Text fz={13} fw={600} lh={1.4} className="dc-ap-bullet-label">
          {item.label}
        </Text>
        {typeof item.text === 'string' ? (
          <Text fz={13} lh={1.4} c="dimmed">
            {item.text}
          </Text>
        ) : (
          item.text
        )}
      </Group>
    </Group>
  ));
  return inline ? (
    <Group gap={14} className="dc-ap-bullets dc-ap-bullets--inline">
      {rows}
    </Group>
  ) : (
    <Stack gap={6} className="dc-ap-bullets">
      {rows}
    </Stack>
  );
};

export default GuideBullets;
