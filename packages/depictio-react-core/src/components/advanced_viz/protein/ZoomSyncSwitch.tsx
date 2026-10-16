import React from 'react';

import { useZoomSyncSwitch } from '../../../highlight/zoomSync';
import { VizSwitch } from '../controls/VizControls';

/**
 * The zoom sync switch, under a residue panel's width slider. One setting for
 * the whole view: any residue tile flips it for all of them, and the tile it
 * was flipped from leads. Hidden where there is nothing to sync with.
 */
const ZoomSyncSwitch: React.FC<{ index?: string }> = ({ index }) => {
  const { available, enabled, setEnabled } = useZoomSyncSwitch();
  if (!available) return null;
  return (
    <VizSwitch
      label="Sync zoom"
      title="Every residue tile of this view shows the residues this one shows, and follows when another is zoomed or scrolled"
      checked={enabled}
      onChange={(e) => setEnabled(e.currentTarget.checked, index)}
    />
  );
};

export default ZoomSyncSwitch;
