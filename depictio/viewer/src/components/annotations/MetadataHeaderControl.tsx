import React from 'react';
import { Badge, Drawer, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  ChromeButton,
  dispatchPanelToggle,
  getChromeStyle,
  METADATA_PANEL_TOGGLE_EVENT,
  Z_LAYERS,
} from 'depictio-react-core';

/** The panel holds a grid, so it is wider than Analysis. Pixels, so the apps
 *  pad their content column by exactly this much. */
export const METADATA_PANEL_WIDTH_PX = 760;

/** Capped in vw like the Analysis panel, so a phone keeps a strip of dashboard. */
const PANEL_WIDTH = `min(${METADATA_PANEL_WIDTH_PX}px, 92vw)`;
/** Mantine's Drawer default, which the content column's padding matches. */
const PANEL_TRANSITION_MS = 250;

/**
 * Header home of the Metadata panel: the dashboard's metadata tables
 * (samplesheet, metadata sheet) in a grid, where a reader adds session labels
 * and, with the right to, edits the table.
 *
 * Built like the Analysis panel (`GroupingHeaderControl`) on purpose: same
 * button, same docked non-modal drawer below the header, same width
 * announcement to the grid. The two share the right edge, so the app opens
 * one at a time.
 */
const MetadataHeaderControl: React.FC<{
  /** Label columns across every metadata table, shown on the button. */
  labelCount: number;
  opened: boolean;
  onOpenedChange: (opened: boolean) => void;
  /** Whether the app pads its content column for this panel (false on a phone). */
  pushesContent: boolean;
  children: React.ReactNode;
}> = ({ labelCount, opened, onOpenedChange, pushesContent, children }) => {
  // Announce only real toggles: the grid applies the swing as a delta.
  const announced = React.useRef(false);
  React.useEffect(() => {
    if (!announced.current) {
      announced.current = true;
      return;
    }
    if (!pushesContent) return;
    dispatchPanelToggle(METADATA_PANEL_TOGGLE_EVENT, {
      willBeOpen: opened,
      swingPx: METADATA_PANEL_WIDTH_PX,
      durationMs: PANEL_TRANSITION_MS,
    });
  }, [opened, pushesContent]);

  return (
    <>
      <ChromeButton
        role="toggle"
        collapse
        active={opened}
        icon="metadata"
        label="Metadata"
        tooltip="See the sample metadata, label samples to compare them, edit the table"
        badge={labelCount}
        aria-pressed={opened}
        data-testid="metadata-button"
        onClick={() => onOpenedChange(!opened)}
      />
      <Drawer
        opened={opened}
        onClose={() => onOpenedChange(false)}
        position="right"
        size={PANEL_WIDTH}
        classNames={{ content: 'dc-analysis-panel', inner: 'dc-analysis-panel-inner' }}
        padding="md"
        zIndex={Z_LAYERS.overlay}
        // A dock, not a modal: the charts stay live while labels change.
        withOverlay={false}
        trapFocus={false}
        lockScroll={false}
        closeOnClickOutside={false}
        // Escape in a grid cell cancels the edit; it must not close the panel.
        closeOnEscape={false}
        shadow="xl"
        styles={{ inner: { top: getChromeStyle().layout.headerHeight } }}
        title={
          <Group gap="xs">
            <Icon icon="mdi:table-edit" width={20} height={20} className="dc-ap-title-icon" />
            <Text fw={600} size="md" className="dc-ap-title">
              Metadata
            </Text>
            {labelCount > 0 && (
              <Badge size="sm" variant="light" color="gray" className="dc-ap-title-count">
                {labelCount} label column{labelCount === 1 ? '' : 's'}
              </Badge>
            )}
          </Group>
        }
        data-testid="metadata-panel"
      >
        {children}
      </Drawer>
    </>
  );
};

export default MetadataHeaderControl;
