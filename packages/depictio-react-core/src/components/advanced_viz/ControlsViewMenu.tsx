import React from 'react';
import { ActionIcon, Menu } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useChromeStyle } from '../../chrome';
import { TILE_ACTION_STYLE } from '../chrome/actionStyles';
import useFullscreenPortalTarget from '../chrome/useFullscreenPortalTarget';
import { CONTROLS_VIEWS, type ControlsView } from './controlsDock';

const VIEW_LABEL: Record<ControlsView, string> = {
  hidden: 'Hidden',
  overlay: 'Overlay',
  top: 'Top',
  right: 'Right',
};

const VIEW_ICON: Record<ControlsView, string> = {
  hidden: 'tabler:eye-off',
  overlay: 'tabler:picture-in-picture-top',
  top: 'tabler:layout-navbar',
  right: 'tabler:layout-sidebar-right',
};

/**
 * The button of a compact tile's header that says where its viz controls are
 * and moves them: hidden, floating over the plot, above it or beside it. The
 * icon is the settings icon the chrome uses, lit while the controls show; the
 * current view carries a check.
 */
const ControlsViewMenu: React.FC<{
  view: ControlsView;
  onPick: (view: ControlsView) => void;
}> = ({ view, onPick }) => {
  const style = useChromeStyle();
  // Over a fullscreen tile the dropdown has to live inside it to be painted.
  const portalTarget = useFullscreenPortalTarget();
  const shown = view !== 'hidden';
  return (
    <Menu
      position="bottom-end"
      shadow="md"
      width={160}
      withinPortal
      portalProps={{ target: portalTarget }}
    >
      <Menu.Target>
        <ActionIcon
          variant={shown ? 'light' : 'subtle'}
          color="gray"
          size="sm"
          radius={style.radius}
          aria-label={`Viz controls: ${VIEW_LABEL[view].toLowerCase()}`}
          title="Viz controls"
          style={{ flex: 'none', marginLeft: 'auto' }}
          data-testid="viz-controls-reveal"
          data-view={view}
        >
          <Icon icon={TILE_ACTION_STYLE.settings.icon} width={14} height={14} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Viz controls</Menu.Label>
        {CONTROLS_VIEWS.map((v) => {
          const selected = v === view;
          return (
            <Menu.Item
              key={v}
              role="menuitemradio"
              aria-checked={selected}
              leftSection={<Icon icon={VIEW_ICON[v]} width={14} height={14} />}
              rightSection={
                selected ? <Icon icon="tabler:check" width={14} height={14} /> : undefined
              }
              onClick={() => onPick(v)}
              data-testid={`viz-controls-view-${v}`}
              data-selected={selected || undefined}
            >
              {VIEW_LABEL[v]}
            </Menu.Item>
          );
        })}
      </Menu.Dropdown>
    </Menu>
  );
};

export default ControlsViewMenu;
