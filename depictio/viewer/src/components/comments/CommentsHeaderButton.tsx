import React from 'react';
import { ChromeButton, useCommentsControl } from 'depictio-react-core';

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
    <ChromeButton
      role="secondary"
      collapse
      icon="comments"
      label="Comments"
      tooltip={tooltip}
      badge={open > 0 ? open : proposed}
      onClick={() => control.openDrawer(null)}
      data-tour-id="comments-header"
    />
  );
};

export default CommentsHeaderButton;
