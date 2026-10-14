/**
 * "Copy a link with these filters" — the share half of issue #936.
 *
 * `useFilterShareLink` builds the dashboard URL carrying the filters in its
 * `#filters=` fragment and copies it. `ShareFiltersLink` is the small icon the
 * active-filters summary wears, so the gesture sits where the filters are read
 * rather than in a settings page: you see what you are about to share, then
 * share it from the same row.
 *
 * A selection too large to survive chat apps and proxies cannot become a link;
 * it is reported (the icon says so) instead of producing one that breaks in
 * transit.
 */

import React, { useCallback, useState } from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { useClipboard } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import type { InteractiveFilter } from '../../api';
import { buildFilterShareUrl } from '../../filterShare';

/** The link for `filters` (null when they are too large to encode) and a
 *  `copy` that puts it on the clipboard. Built on demand, not per render: the
 *  encoding walks every entry, and most renders never share. */
export function useFilterShareLink(filters: InteractiveFilter[]) {
  const clipboard = useClipboard({ timeout: 1600 });
  const [tooLarge, setTooLarge] = useState(false);

  const copy = useCallback(() => {
    const url = buildFilterShareUrl(filters);
    if (url === null) {
      setTooLarge(true);
      window.setTimeout(() => setTooLarge(false), 2600);
      return;
    }
    clipboard.copy(url);
  }, [filters, clipboard]);

  return { copy, copied: clipboard.copied, tooLarge };
}

const ShareFiltersLink: React.FC<{ filters: InteractiveFilter[] }> = ({ filters }) => {
  const { copy, copied, tooLarge } = useFilterShareLink(filters);
  const label = tooLarge
    ? 'Too many selected values to put in a link'
    : copied
      ? 'Link copied'
      : 'Copy a link with these filters';
  return (
    <Tooltip label={label} withArrow position="left" openDelay={tooLarge || copied ? 0 : 400}>
      <ActionIcon
        variant="subtle"
        color={tooLarge ? 'red' : copied ? 'teal' : 'gray'}
        size="xs"
        aria-label="Copy a link with these filters"
        onClick={copy}
        style={{ flexShrink: 0 }}
        data-testid="share-filters-link"
      >
        <Icon
          icon={tooLarge ? 'mdi:link-variant-off' : copied ? 'mdi:check' : 'mdi:link-variant'}
          width={14}
          height={14}
        />
      </ActionIcon>
    </Tooltip>
  );
};

export default ShareFiltersLink;
