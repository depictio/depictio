import React from 'react';
import { ActionIcon, Indicator, Menu, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { MapPanel } from './useMapPanel';
import type { MapPanelMode } from './useMapPanelState';

const MODE_ITEMS: Array<{ mode: MapPanelMode; label: string; icon: string }> = [
  { mode: 'floating', label: 'Floating card', icon: 'mdi:dock-window' },
  { mode: 'docked', label: 'Docked in the filter panel', icon: 'mdi:dock-bottom' },
  { mode: 'hidden', label: 'Hidden', icon: 'mdi:eye-off-outline' },
];

export interface MapPanelControlProps {
  panel: MapPanel;
}

/**
 * Header entry point for the dashboard's map panel.
 *
 * The panel is dashboard-wide, so its control belongs with the other
 * dashboard-wide controls rather than as a floating button over the canvas —
 * same reasoning, and same shape, as `RealtimeIndicator` next to it. The badge
 * is what tells a viewer that a map selection made on another tab is still
 * filtering what they are looking at.
 */
const MapPanelControl: React.FC<MapPanelControlProps> = ({ panel }) => {
  const { state, setMode, totalSelected, clearSelection, available } = panel;
  if (!available) return null;

  const hidden = state.mode === 'hidden';
  const filtering = totalSelected > 0;
  const label = filtering
    ? `Map panel — ${totalSelected} value${totalSelected > 1 ? 's' : ''} filtering the dashboard`
    : hidden
      ? 'Map panel — hidden'
      : 'Map panel';

  return (
    /* The count rides on the button's *corner*, so the Indicator wraps the whole
       control rather than the glyph. Wrapping the glyph put an orange badge on
       an orange fill, half-covering the pin, which read as a broken icon rather
       than as a count. For the same reason the glyph no longer changes with the
       filter state and the active fill is `light`: the pin has to stay
       recognisably a pin, and the badge needs a surface it can be read against.
       Orange is the app's "this is filtering" colour, as on the chrome's
       ResetButton and the panel's own "Reset all".

       Outside the Menu, not between it and its target: `Menu.Target` hands its
       click and keyboard props to whatever element it wraps, and that has to
       stay the button.

       The count hangs off the BOTTOM corner, which is the only one with room.
       This control sits in a 50px app header with a 28px button centred in it,
       so a badge on the top corner reaches within a couple of pixels of the
       window's own top edge and gets shaved there. Below the button there is
       nothing to collide with, and the pin tapers to a point, so its
       bottom-right is the emptiest part of the glyph. */
    <Indicator
      color="orange"
      withBorder
      position="bottom-end"
      size={16}
      offset={2}
      label={totalSelected}
      disabled={!filtering}
    >
      <Menu position="bottom-end" withinPortal>
        <Menu.Target>
          <Tooltip label={label} withArrow>
            <ActionIcon
              variant={filtering ? 'light' : 'subtle'}
              color={filtering ? 'orange' : 'gray'}
              aria-label={label}
              data-testid="map-panel-control"
              data-filtering={filtering || undefined}
            >
              <Icon
                icon={hidden ? 'mdi:map-marker-off-outline' : 'mdi:map-marker-multiple'}
                width={18}
                height={18}
              />
            </ActionIcon>
          </Tooltip>
        </Menu.Target>
        <Menu.Dropdown miw={220}>
          <Menu.Label>Map panel</Menu.Label>
          {MODE_ITEMS.map((item) => (
            <Menu.Item
              key={item.mode}
              leftSection={<Icon icon={item.icon} width={16} />}
              rightSection={
                state.mode === item.mode ? <Icon icon="mdi:check" width={14} /> : undefined
              }
              onClick={() => setMode(item.mode)}
            >
              {item.label}
            </Menu.Item>
          ))}
          {totalSelected > 0 && (
            <>
              <Menu.Divider />
              <Menu.Label>
                <Text size="xs" c="dimmed">
                  {totalSelected} value{totalSelected > 1 ? 's' : ''} selected on the map
                </Text>
              </Menu.Label>
              <Menu.Item
                color="red"
                leftSection={<Icon icon="mdi:selection-remove" width={16} />}
                onClick={clearSelection}
              >
                Clear map selection
              </Menu.Item>
            </>
          )}
        </Menu.Dropdown>
      </Menu>
    </Indicator>
  );
};

export default MapPanelControl;
