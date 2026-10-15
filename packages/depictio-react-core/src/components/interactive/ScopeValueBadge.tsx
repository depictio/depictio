/**
 * The unit a tab is scoped to, as a chip: in the scope banner and next to the
 * title of every tile that follows the scope. One component, so the two never
 * drift apart on colour, shape or truncation.
 *
 * The shape is the chrome's (`useChromeStyle().radius`: a pill in Paper, the
 * Classic corner otherwise), the colour the filter's accent (see
 * `scopeChipColor`), drawn `light` like the other value badges.
 */
import { Badge, Tooltip } from '@mantine/core';
import React from 'react';

import { useChromeStyle } from '../../chrome';

/** Characters past which the chip truncates and the tooltip names it. */
const LONG = 28;

export const ScopeValueBadge: React.FC<{
  value: string;
  color?: string;
  /** `md` in the banner, where the unit is the point; `sm` in a tile header. */
  size?: 'sm' | 'md';
  /** Who the value belongs to, for the tooltip ("Family"). */
  title?: string;
}> = ({ value, color, size = 'sm', title }) => {
  const style = useChromeStyle();
  const badge = (
    <Badge
      variant="light"
      color={color}
      radius={style.radius}
      size={size}
      tt="none"
      maw={size === 'md' ? 320 : 200}
      style={{ flexShrink: 1, minWidth: 0, fontWeight: 600 }}
      data-testid="scope-value-badge"
    >
      {value}
    </Badge>
  );
  if (value.length <= LONG && !title) return badge;
  return (
    <Tooltip label={title ? `${title}: ${value}` : value} withinPortal openDelay={300}>
      {badge}
    </Tooltip>
  );
};

export default ScopeValueBadge;
