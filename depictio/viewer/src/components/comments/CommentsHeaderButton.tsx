import React from 'react';
import { ChromeButton, useCommentsControl } from 'depictio-react-core';

const sum = (m: Record<string, number>) => Object.values(m).reduce((a, b) => a + b, 0);

/** Header entry point to every comment on the tab. Renders nothing unless the
 *  comments context is mounted: the user may comment, or is a guest who could
 *  by signing in (the button then says so and asks them to). */
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
  const tooltip = !control.canComment
    ? 'Sign in to comment on this dashboard'
    : pending
      ? `${pending} thread${pending === 1 ? '' : 's'} to follow: ${parts.join(', ')}`
      : 'Comment on this dashboard';
  return (
    <ChromeButton
      role="secondary"
      collapse
      icon="comments"
      label="Comments"
      tooltip={tooltip}
      badge={pending}
      onClick={() => control.openDrawer(null)}
      data-tour-id="comments-header"
    />
  );
};

export default CommentsHeaderButton;
