import React from 'react';
import { AdvancedVizSettingsPopover } from '../advanced_viz/AdvancedVizExtras';
import { VizControlGroup, VizSwitch } from '../advanced_viz/controls/VizControls';

/** The section of the settings popover a toggle is listed under. */
export type ViewMenuGroup = 'View' | 'Loading' | 'Interaction';

export interface ViewMenuItem {
  key: string;
  label: string;
  /** One line under the label, for a toggle whose effect is not obvious. */
  description?: string;
  group: ViewMenuGroup;
  checked: boolean;
  onChange: () => void;
}

interface ViewMenuProps {
  items: ViewMenuItem[];
  disabled?: boolean;
}

const GROUP_ORDER: ViewMenuGroup[] = ['View', 'Loading', 'Interaction'];

/**
 * The browser's display options (header, overview ruler, status bar, force
 * load, click-to-filter) behind the tile's settings action: the same icon,
 * colour and popover as every other tile's viz settings, with one switch per
 * option grouped like the advanced-viz controls. The popover portals into the
 * fullscreen element itself (`useFullscreenPortalTarget`).
 */
const ViewMenu: React.FC<ViewMenuProps> = ({ items, disabled }) => (
  <AdvancedVizSettingsPopover
    controls={GROUP_ORDER.map((group) => {
      const rows = items.filter((item) => item.group === group);
      if (rows.length === 0) return null;
      return (
        <VizControlGroup key={group} title={group}>
          {rows.map((item) => (
            <VizSwitch
              key={item.key}
              label={item.label}
              description={item.description}
              checked={item.checked}
              disabled={disabled}
              onChange={item.onChange}
              data-testid={`jbrowse-option-${item.key}`}
            />
          ))}
        </VizControlGroup>
      );
    })}
  />
);

export default ViewMenu;
