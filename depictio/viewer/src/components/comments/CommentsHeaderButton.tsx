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
  // The badge and the tooltip count the same threads: open plus proposed.
  const pending = open + proposed;
  const parts = [
    open ? `${open} open` : '',
    proposed ? `${proposed} awaiting review` : '',
    stale ? `${stale} with changed data` : '',
  ].filter(Boolean);
  const tooltip = pending
    ? `${pending} thread${pending === 1 ? '' : 's'} to follow: ${parts.join(', ')}`
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
          pending > 0 ? (
            <Badge size="xs" variant="filled" color={open > 0 ? 'blue' : 'violet'} circle>
              {pending}
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
