import React from 'react';
import { Anchor, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { IconBadge } from 'depictio-components';

import { glyphColorVar } from './Glyph';
import type { TabLinkTarget } from './tabLinks';

/**
 * The card header of a figure drawn in the `minimal` style: an icon badge,
 * the title in bold and a dimmed subtitle on the same line, as a landing
 * page's showcase tiles read ("Phylum composition  relative abundance per
 * sample").
 *
 * The plot under it has no title of its own (the server drops it), so this is
 * the figure's only heading. `badges` are the figure's status chips (sampled,
 * grouped), kept at the end of the line; `source` is the tab a highlighted
 * figure comes from, linked at the end of the line.
 */
export interface FigureHeaderProps {
  title?: string;
  subtitle?: string;
  /** Iconify id of the badge; no badge when unset. */
  icon?: string;
  /** Mantine palette name or CSS colour; the brand's primary when unset. */
  iconColor?: string;
  badges?: React.ReactNode;
  source?: TabLinkTarget | null;
}

const FigureHeader: React.FC<FigureHeaderProps> = ({
  title,
  subtitle,
  icon,
  iconColor,
  badges,
  source,
}) => {
  const color = iconColor ? glyphColorVar(iconColor) : 'var(--mantine-primary-color-filled)';
  return (
    <Group
      gap={10}
      wrap="nowrap"
      align="center"
      mb={6}
      // The tile's action column floats at the top right on hover; the header
      // leaves it that corner rather than running under it.
      pr={28}
      style={{ minWidth: 0 }}
      data-testid="figure-header"
    >
      {icon && <IconBadge icon={icon} color={color} />}
      <Group gap={8} wrap="nowrap" align="baseline" style={{ minWidth: 0, flex: '0 1 auto' }}>
        {title && (
          <Text fw={700} size="md" truncate style={{ lineHeight: 1.3, flex: '0 0 auto', maxWidth: '100%' }}>
            {title}
          </Text>
        )}
        {subtitle && (
          <Text size="sm" c="dimmed" truncate style={{ lineHeight: 1.3, minWidth: 0 }}>
            {subtitle}
          </Text>
        )}
      </Group>
      {badges}
      {source && (
        <Anchor
          href={source.href}
          size="xs"
          c="dimmed"
          underline="hover"
          ml="auto"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap', flex: 'none' }}
          data-testid="figure-header-source"
        >
          Open in {source.label}
          <Icon icon="mdi:arrow-right" width={13} />
        </Anchor>
      )}
    </Group>
  );
};

export default FigureHeader;
