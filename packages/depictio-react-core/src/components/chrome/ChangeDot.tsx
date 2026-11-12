import React, { useContext } from 'react';
import { Menu, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { ChangeMarksContext, useChangeMark, useChangeMarkDetails } from '../../changeMarks';
import { useBrandScopeAttributes } from '../branding';
import { Z_LAYERS } from '../../zLayers';

/** Component types whose figure can show the before/after overlay. */
const COMPARABLE_TYPES = new Set(['figure', 'multiqc', 'advanced_viz']);

const REASON_LABEL = {
  definition: 'Changed since your last visit',
  data: 'Data refreshed since your last visit',
} as const;

/**
 * The small "updated" dot on a tile whose definition or data changed since the
 * reader's last visit (#1397). Renders nothing when the change-marks context is
 * empty (the editor, every other host, the feature off), so it costs nothing
 * where it is not wanted.
 *
 * The menu holds the three things a reader does with a mark: dismiss it, lay
 * the previous state over the figure, open the side-by-side view. "Mark as
 * seen" is absent in a read-only view (`?since=`), which never moves a mark.
 */
const ChangeDot: React.FC<{ componentType: string; index: string }> = ({ componentType, index }) => {
  const { reasons, key, comparing } = useChangeMark(index);
  const { dismiss, toggleCompare, openCompare, readOnly } = useContext(ChangeMarksContext);
  const details = useChangeMarkDetails(key);
  const brandScope = useBrandScopeAttributes();
  if (!key || reasons.length === 0) return null;

  const lines = details.length > 0 ? details : reasons.map((r) => REASON_LABEL[r]);
  const comparable = COMPARABLE_TYPES.has(componentType);

  return (
    <Menu
      position="top-start"
      withinPortal
      shadow="md"
      width={220}
      zIndex={Z_LAYERS.tooltip}
      trigger="click-hover"
      openDelay={80}
      closeDelay={200}
    >
      <Menu.Target>
        <button
          type="button"
          className="depictio-updated-dot"
          aria-label="Updated since your last visit"
          data-testid="component-updated-dot"
          data-change-reasons={reasons.join(',')}
        >
          <Tooltip
            label={
              <>
                {lines.map((line) => (
                  <Text key={line} size="xs">
                    {line}
                  </Text>
                ))}
              </>
            }
            withArrow
            multiline
            w={240}
            position="top-start"
            zIndex={Z_LAYERS.tooltip}
          >
            <span className="depictio-updated-dot__mark" />
          </Tooltip>
        </button>
      </Menu.Target>
      <Menu.Dropdown
        className={brandScope?.className}
        data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
        data-testid="component-updated-menu"
      >
        {!readOnly && (
          <Menu.Item
            leftSection={<Icon icon="mdi:check" width={14} />}
            onClick={() => dismiss(key)}
            data-testid="component-updated-seen"
          >
            Mark as seen
          </Menu.Item>
        )}
        {comparable && (
          <Menu.Item
            leftSection={<Icon icon="mdi:compare-horizontal" width={14} />}
            rightSection={comparing ? <Icon icon="mdi:check" width={14} /> : undefined}
            onClick={() => toggleCompare(key)}
            data-testid="component-updated-compare"
          >
            Compare with last visit
          </Menu.Item>
        )}
        <Menu.Item
          leftSection={<Icon icon="mdi:view-split-vertical" width={14} />}
          onClick={() => openCompare(key)}
          data-testid="component-updated-before-now"
        >
          Before | Now
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
};

export default ChangeDot;
