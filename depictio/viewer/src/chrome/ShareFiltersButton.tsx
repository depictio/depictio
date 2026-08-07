/**
 * "Copy link with filters" — captures the current view (issue #936).
 *
 * Builds a `#filters=<base64url>` URL for the current dashboard and copies it
 * to the clipboard. The recipient's viewer decodes the fragment on load and
 * applies the filters, so the link reproduces the exact filtered view; with no
 * active filters it degrades to the plain dashboard URL, which keeps the
 * button predictable. Very large selections (thousands of image/table ids)
 * can exceed what survives chat apps and proxies — those refuse to copy and
 * say why instead of producing a link that breaks in transit.
 */

import React, { useState } from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { useClipboard } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { buildFilterShareUrl } from 'depictio-react-core';
import type { InteractiveFilter } from 'depictio-react-core';

interface ShareFiltersButtonProps {
  filters: InteractiveFilter[];
  activeCount: number;
}

const ShareFiltersButton: React.FC<ShareFiltersButtonProps> = ({ filters, activeCount }) => {
  const clipboard = useClipboard({ timeout: 1500 });
  const [tooLarge, setTooLarge] = useState(false);

  const handleCopy = () => {
    const url = buildFilterShareUrl(activeCount > 0 ? filters : []);
    if (url === null) {
      setTooLarge(true);
      window.setTimeout(() => setTooLarge(false), 2500);
      return;
    }
    clipboard.copy(url);
  };

  const label = tooLarge
    ? 'Selection too large to share as a link'
    : clipboard.copied
      ? 'Link copied!'
      : activeCount > 0
        ? 'Copy link with current filters'
        : 'Copy dashboard link';

  return (
    <Tooltip label={label} withArrow opened={clipboard.copied || tooLarge ? true : undefined}>
      <ActionIcon
        variant="subtle"
        color={tooLarge ? 'red' : clipboard.copied ? 'teal' : 'gray'}
        size="lg"
        aria-label="Copy link with current filters"
        onClick={handleCopy}
      >
        <Icon
          icon={clipboard.copied ? 'mdi:check' : 'mdi:link-variant'}
          width={18}
          height={18}
        />
      </ActionIcon>
    </Tooltip>
  );
};

export default ShareFiltersButton;
