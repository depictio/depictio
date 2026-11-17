import React, { useEffect, useState } from 'react';
import { ActionIcon, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { TILE_ACTION_STYLE } from '../chrome/actionStyles';
import FullscreenButton from '../chrome/FullscreenButton';

/** True while `ref`'s element is the page's fullscreen element. */
export function useIsFullscreen(ref: React.RefObject<HTMLElement | null>): boolean {
  const [full, setFull] = useState(false);
  useEffect(() => {
    const sync = () => setFull(document.fullscreenElement != null && document.fullscreenElement === ref.current);
    sync();
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, [ref]);
  return full;
}

interface Props {
  /** The element that goes fullscreen: the table and its controls. */
  fullscreenRef: React.RefObject<HTMLDivElement | null>;
  /** Back to the unfiltered, unsorted table. */
  onReset: () => void;
  /** Download the table as CSV; may be async (a server-paged table). */
  onDownload: () => void | Promise<void>;
  /** Disable the download while there is nothing to export. */
  downloadDisabled?: boolean;
}

/**
 * The table actions a regular table tile gets from its chrome (reset,
 * download CSV, fullscreen), for the two tables the genome browser draws
 * itself. Same icons, colours and labels (`TILE_ACTION_STYLE`) and the same
 * fullscreen button as the chrome's.
 */
const TableActions: React.FC<Props> = ({ fullscreenRef, onReset, onDownload, downloadDisabled }) => {
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      await onDownload();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Group gap={2} wrap="nowrap" data-testid="jbrowse-table-actions">
      <Tooltip label="Reset filters and sorting" withArrow>
        <ActionIcon
          variant="subtle"
          color={TILE_ACTION_STYLE.reset.color}
          size="sm"
          onClick={onReset}
          aria-label="Reset filters and sorting"
        >
          <Icon icon={TILE_ACTION_STYLE.reset.icon} width={16} height={16} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label={TILE_ACTION_STYLE.download.label} withArrow>
        <ActionIcon
          variant="subtle"
          color={TILE_ACTION_STYLE.download.color}
          size="sm"
          loading={busy}
          disabled={downloadDisabled}
          onClick={download}
          aria-label={TILE_ACTION_STYLE.download.label}
        >
          <Icon icon={TILE_ACTION_STYLE.download.icon} width={16} height={16} />
        </ActionIcon>
      </Tooltip>
      <FullscreenButton fullscreenRef={fullscreenRef} />
    </Group>
  );
};

export default TableActions;
