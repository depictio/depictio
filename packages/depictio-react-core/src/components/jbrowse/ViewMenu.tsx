import React, { useEffect, useState } from 'react';
import { ActionIcon, Menu, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface ViewMenuItem {
  key: string;
  label: string;
  checked: boolean;
  onChange: () => void;
}

interface ViewMenuProps {
  items: ViewMenuItem[];
  /** The native fullscreen element when the tile is fullscreen: the dropdown
   *  must be portalled into it or it would not be painted. */
  portalTarget: HTMLElement | null;
  disabled?: boolean;
}

/**
 * One chrome-toolbar button for the browser's display options (header,
 * overview ruler, status bar, force load, click-to-filter). Same Mantine
 * Menu + subtle ActionIcon pattern as the other tile menus; the menu stays
 * open while options are flipped.
 */
const ViewMenu: React.FC<ViewMenuProps> = ({ items, portalTarget, disabled }) => {
  const [opened, setOpened] = useState(false);

  // Entering / leaving fullscreen moves the portal target: close rather than
  // leave a dropdown anchored to where the icon used to be.
  useEffect(() => setOpened(false), [portalTarget]);

  return (
    <Menu
      key={portalTarget ? 'fullscreen' : 'page'}
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      shadow="md"
      width={220}
      withinPortal
      closeOnItemClick={false}
      portalProps={portalTarget ? { target: portalTarget } : undefined}
    >
      <Menu.Target>
        <Tooltip label="Display options" withinPortal={false}>
          <ActionIcon
            variant={opened ? 'light' : 'subtle'}
            color="gray"
            size="md"
            aria-label="Display options"
            data-testid="jbrowse-toggle-view"
            disabled={disabled}
          >
            <Icon icon="mdi:tune-variant" width={18} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown data-testid="jbrowse-view-menu">
        <Menu.Label>Display</Menu.Label>
        {items.map((item) => (
          <Menu.Item
            key={item.key}
            data-testid={`jbrowse-option-${item.key}`}
            aria-pressed={item.checked}
            onClick={item.onChange}
            leftSection={
              <Icon
                icon={item.checked ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'}
                width={16}
              />
            }
          >
            {item.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
};

export default ViewMenu;
