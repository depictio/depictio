import React, { useState } from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { copyToClipboard } from '../../lib/listingUrl';

interface ShareViewButtonProps {
  /** What the copied link shows, for the confirmation notice: "12 dashboards"
   *  or "the current view". */
  describes: string;
  /** Rendered in the tooltip above the description. */
  label?: string;
}

/** Copies the current URL — which the listing keeps in step with its filters
 *  — so the view on screen can be handed to someone else exactly as it is.
 *
 *  The address bar already holds the same string; the button exists because
 *  "copy this link" is a far more discoverable instruction than "select the
 *  address bar", and because the confirmation says what the recipient will
 *  actually see. */
const ShareViewButton: React.FC<ShareViewButtonProps> = ({ describes, label }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const url = window.location.href;
    const ok = await copyToClipboard(url);
    if (!ok) {
      notifications.show({
        color: 'red',
        title: 'Could not copy the link',
        message: 'Copy it from the address bar instead.',
      });
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
    notifications.show({
      color: 'teal',
      title: 'Link copied',
      message: `Opens ${describes}.`,
      autoClose: 3000,
    });
  };

  return (
    <Tooltip label={label ?? 'Copy a link to this filtered view'} withinPortal>
      <ActionIcon
        variant="default"
        size="lg"
        radius="md"
        onClick={handleCopy}
        aria-label="Copy a link to this filtered view"
        data-testid="share-view-btn"
      >
        <Icon icon={copied ? 'mdi:check' : 'mdi:link-variant'} width={18} />
      </ActionIcon>
    </Tooltip>
  );
};

export default ShareViewButton;
