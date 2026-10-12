import React from 'react';
import { Popover, Tooltip } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { Z_LAYERS } from 'depictio-react-core';

import { useUpdateNotice } from '../../hooks/useUpdateNotice';
import ServerInfoPanel from './ServerInfoPanel';

/**
 * The popover behind every server status element (the Classic badge, the
 * Glass sidebar foot). The trigger is the caller's, because each chrome draws
 * its own: it receives what it needs to dress itself (`opened`, and whether to
 * wear the update dot) and returns one element that takes a ref, which
 * becomes a real button for the keyboard and for screen readers.
 *
 * The panel opens beside a sidebar foot (`right-end`) and above a bar on a
 * phone (`top`); Escape and a click outside close it.
 */

export interface ServerInfoTrigger {
  opened: boolean;
  /** An unread update notice: the trigger wears the dot. */
  updateDot: boolean;
  /** The trigger's accessible name, with the update spelled out for those who
   *  cannot see the dot. */
  label: (base: string) => string;
}

export interface ServerInfoPopoverProps {
  children: (trigger: ServerInfoTrigger) => React.ReactElement;
  /** A tooltip for the trigger while the panel is closed (a folded sidebar). */
  tooltip?: string | null;
}

const ServerInfoPopover: React.FC<ServerInfoPopoverProps> = ({ children, tooltip }) => {
  const [opened, setOpened] = React.useState(false);
  const phone = useMediaQuery('(max-width: 47.99em)');
  const { show } = useUpdateNotice();

  const trigger = children({
    opened,
    updateDot: show,
    label: (base) => (show ? `${base}. Update available` : base),
  });

  return (
    // Uncontrolled on purpose: only an uncontrolled Popover toggles from its
    // target's click. `onChange` still mirrors the state for the tooltip and
    // for the trigger's `opened`.
    <Popover
      onChange={setOpened}
      position={phone ? 'top' : 'right-end'}
      width={300}
      offset={10}
      shadow="md"
      withinPortal
      zIndex={Z_LAYERS.nestedOverlay}
      closeOnEscape
      clickOutsideEvents={['mouseup', 'touchend']}
    >
      {/* Mantine's documented nesting: the Popover target outside, the
          Tooltip inside, so the click handler lands on the trigger itself. */}
      <Popover.Target>
        <Tooltip label={tooltip} disabled={!tooltip || opened} withArrow position="right" openDelay={200}>
          {trigger}
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="md" data-testid="server-info-popover">
        <ServerInfoPanel variant="popover" />
      </Popover.Dropdown>
    </Popover>
  );
};

export default ServerInfoPopover;
