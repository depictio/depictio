import React from 'react';
import { ActionIcon, Indicator, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface CommentsButtonProps {
  componentId: string;
  openCount: number;
  proposedCount: number;
  /** Unsettled threads whose data or component changed since they were written. */
  staleCount?: number;
  onOpen: (componentId: string) => void;
}

/**
 * Opens the comments drawer on this component. Only rendered when the app
 * provides a `CommentsContext`, i.e. when the user may comment.
 *
 * The badge counts open threads; agent proposals awaiting review add a small
 * dot instead of inflating that number, since they are not discussions yet.
 * Threads that no longer match the data or the component turn the icon
 * orange, so staleness shows on the dashboard and not only in the drawer.
 */
const CommentsButton: React.FC<CommentsButtonProps> = ({
  componentId,
  openCount,
  proposedCount,
  staleCount = 0,
  onOpen,
}) => {
  const parts: string[] = [];
  if (openCount > 0) parts.push(`${openCount} open`);
  if (proposedCount > 0) parts.push(`${proposedCount} proposed`);
  if (staleCount > 0) parts.push(`${staleCount} with changed data`);
  const label = parts.length ? `Comments (${parts.join(', ')})` : 'Comments';
  const hasAny = openCount > 0 || proposedCount > 0 || staleCount > 0;
  const stale = staleCount > 0;
  return (
    <Tooltip label={label} withArrow>
      <Indicator
        disabled={openCount === 0 && proposedCount === 0}
        label={openCount > 0 ? openCount : undefined}
        size={openCount > 0 ? 14 : 8}
        color={openCount > 0 ? 'blue' : 'violet'}
        offset={3}
        withBorder
        processing={openCount === 0 && proposedCount > 0}
        // Indicator's root is a block div by default; flex keeps the icon on
        // the same line and baseline as its sibling action icons.
        style={{ display: 'flex' }}
      >
        <ActionIcon
          variant={hasAny ? 'light' : 'subtle'}
          color={stale ? 'orange' : 'blue'}
          size="sm"
          onClick={() => onOpen(componentId)}
          aria-label={label}
        >
          <Icon
            icon={
              stale
                ? 'mdi:comment-alert-outline'
                : hasAny
                  ? 'mdi:comment-text-outline'
                  : 'mdi:comment-plus-outline'
            }
            width={16}
            height={16}
          />
        </ActionIcon>
      </Indicator>
    </Tooltip>
  );
};

export default CommentsButton;
