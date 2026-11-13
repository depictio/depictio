/**
 * The three badges of the project pages, one look each so a badge says what
 * kind of thing it is before it is read:
 *
 *  - FactBadge: a plain fact about a thing (engine, version, "2 runs",
 *    "26 collections", a collection's kind). Outlined, never coloured.
 *  - StatusBadge: where a thing stands (found, empty for now, consistent...).
 *    A coloured dot on the label; the colour is the status.
 *  - NameChip: a name the reader may look for (a run, a file, a collection
 *    tag). Outlined, monospace.
 *
 * Flags that mark a thing out (public, edited, Recommended) stay light accent
 * badges where they are.
 */
import React from 'react';
import { Badge, type BadgeProps } from '@mantine/core';
import { Icon } from '@iconify/react';

type Size = 'xs' | 'sm' | 'md';

type Common = Omit<BadgeProps, 'variant' | 'children' | 'size'> & {
  size?: Size;
  children: React.ReactNode;
  'data-testid'?: string;
  [data: `data-${string}`]: unknown;
};

const ICON_WIDTH: Record<Size, number> = { xs: 10, sm: 12, md: 14 };

export const FactBadge: React.FC<Common & { icon?: string | React.ReactNode }> = ({
  size = 'sm',
  icon,
  children,
  style,
  ...rest
}) => (
  <Badge
    size={size}
    variant="default"
    radius="sm"
    tt="none"
    fw={500}
    leftSection={
      typeof icon === 'string' ? <Icon icon={icon} width={ICON_WIDTH[size]} /> : (icon ?? undefined)
    }
    style={{ flexShrink: 0, ...(style as React.CSSProperties) }}
    {...rest}
  >
    {children}
  </Badge>
);

export const StatusBadge: React.FC<Common & { color: string }> = ({ size = 'sm', color, children, style, ...rest }) => (
  <Badge
    size={size}
    variant="dot"
    color={color}
    radius="sm"
    tt="none"
    fw={500}
    style={{ flexShrink: 0, ...(style as React.CSSProperties) }}
    {...rest}
  >
    {children}
  </Badge>
);

export const NameChip: React.FC<Common & { icon?: React.ReactNode; dimmed?: boolean }> = ({
  size = 'sm',
  icon,
  dimmed,
  children,
  style,
  ...rest
}) => (
  <Badge
    size={size}
    variant="default"
    radius="sm"
    tt="none"
    fw={400}
    ff="monospace"
    c={dimmed ? 'dimmed' : undefined}
    leftSection={icon}
    style={{ flexShrink: 0, ...(style as React.CSSProperties) }}
    {...rest}
  >
    {children}
  </Badge>
);
