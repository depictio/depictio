import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useZoomSyncGroup } from '../highlight/zoomSync';
import { TILE_ACTION_STYLE } from './chrome/actionStyles';

/**
 * A section header's zoom sync button (see highlight/zoomSync.ts): adds every
 * tile of the section that can sync, or takes them all out once they are all
 * in. Filled when all are in, light when some are. The same icon as each
 * tile's own switch, so the two read as one control at two scopes.
 */
export const ZoomSyncSectionButton: React.FC<{ tiles: readonly string[] }> = ({ tiles }) => {
  const { state, setAll } = useZoomSyncGroup(tiles);
  const all = state === 'all';
  const label = all ? 'Stop syncing zoom in this section' : 'Sync zoom across this section';
  const tip = all
    ? 'Each tile of the section zooms on its own again'
    : state === 'some'
      ? 'Some tiles of the section already zoom together: add the others'
      : 'Zooming or scrolling one tile of the section shows the same residues in the others, and the 3D model frames them';
  return (
    <Tooltip label={tip} withArrow multiline w={240} openDelay={300}>
      <ActionIcon
        size="sm"
        variant={all ? 'filled' : state === 'some' ? 'light' : 'subtle'}
        color={state === 'none' ? 'gray' : undefined}
        aria-label={label}
        aria-pressed={all}
        data-testid="section-zoom-sync"
        data-sync-state={state}
        onClick={(event) => {
          event.stopPropagation();
          setAll(!all);
        }}
      >
        <Icon icon={TILE_ACTION_STYLE.zoomSync.icon} width={16} />
      </ActionIcon>
    </Tooltip>
  );
};

export default ZoomSyncSectionButton;
