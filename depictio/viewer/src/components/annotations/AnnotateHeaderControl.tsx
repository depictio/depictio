import React from 'react';
import { Badge, Drawer, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { ChromeButton, getChromeStyle, Z_LAYERS } from 'depictio-react-core';

/** Wide enough for a key, a few annotations and some context columns. It
 *  overlays the right of the dashboard rather than padding it: the charts on
 *  the left stay visible and react as labels change. */
const PANEL_WIDTH = 'min(760px, 92vw)';

/**
 * Header home of session annotations: label samples in a grid, and each label
 * of the "Compare by" annotation becomes a group of the Analysis panel.
 *
 * A non-modal dock like the Analysis panel (no overlay, no focus trap, no
 * scroll lock, no close on outside click), so the dashboard stays live
 * underneath. The app keeps it and the Analysis panel from being open at once:
 * both sit on the right.
 */
const AnnotateHeaderControl: React.FC<{
  opened: boolean;
  onOpenedChange: (opened: boolean) => void;
  /** Annotations kept for this dashboard. */
  count: number;
  children: React.ReactNode;
}> = ({ opened, onOpenedChange, count, children }) => (
  <>
    <ChromeButton
      role="toggle"
      collapse
      active={opened}
      icon="mdi:tag-text-outline"
      label="Annotate"
      tooltip="Label samples for this session and compare the groups, without changing the data"
      badge={count}
      aria-pressed={opened}
      onClick={() => onOpenedChange(!opened)}
      data-testid="annotate-button"
    />
    <Drawer
      opened={opened}
      onClose={() => onOpenedChange(false)}
      position="right"
      size={PANEL_WIDTH}
      padding="md"
      zIndex={Z_LAYERS.overlay}
      withOverlay={false}
      trapFocus={false}
      lockScroll={false}
      closeOnClickOutside={false}
      shadow="xl"
      styles={{ inner: { top: getChromeStyle().layout.headerHeight } }}
      title={
        <Group gap="xs">
          <Icon icon="mdi:tag-text-outline" width={20} height={20} />
          <Text fw={600} size="md">
            Annotate
          </Text>
          {count > 0 && (
            <Badge size="sm" variant="light">
              {count} annotation{count === 1 ? '' : 's'}
            </Badge>
          )}
        </Group>
      }
      data-testid="annotation-panel"
    >
      {opened ? children : null}
    </Drawer>
  </>
);

export default AnnotateHeaderControl;
