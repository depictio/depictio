import React from 'react';
import { Modal } from '@mantine/core';

import { Z_LAYERS } from '../../zLayers';
import { useFullscreenPortalTarget } from '../chrome/useFullscreenPortalTarget';

/**
 * The show-data table enlarged, to filter and read many columns at once: a
 * popover that size would run off the screen. Holds the same `DataGridBody`
 * the popover does, whose header carries the way back and the close button.
 *
 * Outside clicks do not close it, for the popover's reason: AG Grid portals
 * its column menus to the page, and a click on one reads as outside.
 */
const DataGridModal: React.FC<{
  opened: boolean;
  onClose: () => void;
  children: React.ReactNode;
}> = ({ opened, onClose, children }) => {
  const portalTarget = useFullscreenPortalTarget();
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      withCloseButton={false}
      closeOnClickOutside={false}
      centered
      size="min(1600px, 96vw)"
      padding="sm"
      zIndex={Z_LAYERS.overlay}
      portalProps={{ target: portalTarget }}
    >
      {children}
    </Modal>
  );
};

export default DataGridModal;
