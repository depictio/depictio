import React from 'react';
import { Box } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface IconBadgeProps {
  /** Iconify id. */
  icon: string;
  /** Any CSS colour: the icon is drawn in it, on a faint tint of it. Unset
   *  draws the icon in the text colour on a grey tint. */
  color?: string;
  /** Side of the square, in px. */
  size?: number;
  /** Side of the icon, in px. */
  iconSize?: number;
  /** Share of the colour in the tint behind the icon, in percent. */
  tint?: number;
}

/**
 * A small icon on a rounded square of its own colour's tint.
 *
 * Leads a title wherever a tile is recognised by colour and glyph before a word
 * of it is read: a metric card's `badge` icon, a figure's showcase header. One
 * component so the two stay the same mark.
 */
const IconBadge: React.FC<IconBadgeProps> = ({
  icon,
  color,
  size = 30,
  iconSize = 18,
  tint = 13,
}) => (
  <Box
    aria-hidden
    style={{
      width: size,
      height: size,
      borderRadius: Math.round(size * 0.27),
      flex: 'none',
      display: 'grid',
      placeItems: 'center',
      background: `color-mix(in srgb, ${color || 'var(--mantine-color-gray-6)'} ${tint}%, var(--mantine-color-body))`,
    }}
  >
    <Icon
      icon={icon}
      width={iconSize}
      height={iconSize}
      style={{ color: color || 'currentColor' }}
    />
  </Box>
);

export default IconBadge;
