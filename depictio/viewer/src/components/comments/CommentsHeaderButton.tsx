import React from 'react';
import { Badge, Button, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useCommentsControl } from 'depictio-react-core';

const sum = (m: Record<string, number>) => Object.values(m).reduce((a, b) => a + b, 0);

/** Header entry point to every comment on the tab. Renders nothing unless the
 *  comments context is mounted, i.e. unless the user may comment. */
const CommentsHeaderButton: React.FC = () => {
  const control = useCommentsControl();
  if (!control) return null;
  const open = sum(control.openCounts);
  const proposed = sum(control.proposedCounts);
  const stale = sum(control.staleCounts);
  const tooltip =
    open || proposed
      ? `${open} open thread${open === 1 ? '' : 's'}${proposed ? `, ${proposed} awaiting review` : ''}${
          stale ? `, ${stale} with changed data` : ''
        }`
      : 'Comment on this dashboard';
  return (
    <Tooltip label={tooltip} withArrow openDelay={400}>
      <Button
        // `xs` + a 14px icon, matching the Analysis / Edit buttons beside it.
        size="xs"
        variant="light"
        color="blue"
        leftSection={<Icon icon="mdi:comment-text-multiple-outline" width={14} height={14} />}
        rightSection={
          open > 0 || proposed > 0 ? (
            <Badge size="xs" variant="filled" color={open > 0 ? 'blue' : 'violet'} circle>
              {open > 0 ? open : proposed}
            </Badge>
          ) : undefined
        }
        onClick={() => control.openDrawer(null)}
        data-tour-id="comments-header"
      >
        Comments
      </Button>
    </Tooltip>
  );
};

export default CommentsHeaderButton;
