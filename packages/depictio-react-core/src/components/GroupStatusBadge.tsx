import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useGroupingColor } from '../selectionGroups';

export interface GroupStatusBadgeProps {
  /** "grouped", "grouped (1 of 2)", "not grouped", "by <column>". */
  label: string;
  /** The override actually repainted the tile: drawn light rather than outlined. */
  colored: boolean;
  /** A fault rather than an honest mismatch: drawn gray. */
  faulted?: boolean;
  /** Hover lines saying why. None means no tooltip. */
  reasons?: string[];
}

/**
 * The tag a tile wears when the dashboard asks for analysis grouping.
 *
 * Wears the Analysis feature's own colour and mark rather than a generic blue:
 * this badge and the "save as group" action on the tile are two ends of one
 * feature, and a badge in some other hue reads as a different thing entirely.
 * `useGroupingColor` is the same source the action and the component outline
 * read, so a branded instance restains all three at once.
 *
 * Shared by figures and advanced viz so "not grouped" looks, and explains
 * itself, the same way on both.
 */
const GroupStatusBadge: React.FC<GroupStatusBadgeProps> = ({
  label,
  colored,
  faulted = false,
  reasons,
}) => {
  const groupingColor = useGroupingColor();
  const badge = (
    <Badge
      variant={colored ? 'light' : 'outline'}
      color={faulted ? 'gray' : groupingColor}
      size="xs"
      radius="sm"
      leftSection={<Icon icon="mdi:select-group" width={11} height={11} />}
    >
      {label}
    </Badge>
  );
  if (!reasons || reasons.length === 0) return badge;
  return (
    <Tooltip
      withArrow
      multiline
      w={260}
      openDelay={200}
      label={reasons.join('\n')}
      style={{ whiteSpace: 'pre-line' }}
    >
      <span>{badge}</span>
    </Tooltip>
  );
};

/** A group badge handed to `AdvancedVizFrame` by the dispatch, so the frame
 *  can draw it under the title without every renderer threading a prop. */
export const GroupStatusBadgeContext = React.createContext<React.ReactNode>(null);

export default GroupStatusBadge;
