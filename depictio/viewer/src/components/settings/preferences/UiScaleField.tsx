import React from 'react';
import { ActionIcon, Button, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useUiScalePref } from '../../../hooks/useUiScalePref';
import { Field } from '../SettingsSections';

/** A− / percent / A+ control for the dashboard content font-size preference
 *  (#854). Scales figures, tables and the other dashboard tiles — never the
 *  app chrome — and is a per-browser preference, so it renders wherever a
 *  reader's own preferences live (the dashboard settings drawer, the account
 *  settings page). */
const UiScaleField: React.FC = () => {
  const { scale, increase, decrease, reset, canIncrease, canDecrease } = useUiScalePref();

  return (
    <Field
      label="Font size"
      description="Scales the figures, tables and cards. While editing, a figure can also carry its own font size from its tile menu."
      testId="font-size-section"
    >
      <Group gap="xs">
        <ActionIcon.Group data-testid="font-size-control">
          <Tooltip label="Decrease font size" withArrow>
            <ActionIcon
              variant="default"
              size="input-xs"
              onClick={decrease}
              disabled={!canDecrease}
              data-testid="font-size-decrease"
              aria-label="Decrease font size"
            >
              <Icon icon="mdi:format-font-size-decrease" width={14} />
            </ActionIcon>
          </Tooltip>
          <Button
            variant="default"
            size="compact-xs"
            h="var(--input-height-xs)"
            style={{ pointerEvents: 'none' }}
            data-testid="font-size-value"
            tabIndex={-1}
          >
            {Math.round(scale * 100)}%
          </Button>
          <Tooltip label="Increase font size" withArrow>
            <ActionIcon
              variant="default"
              size="input-xs"
              onClick={increase}
              disabled={!canIncrease}
              data-testid="font-size-increase"
              aria-label="Increase font size"
            >
              <Icon icon="mdi:format-font-size-increase" width={14} />
            </ActionIcon>
          </Tooltip>
        </ActionIcon.Group>
        {scale !== 1 && (
          <Button variant="subtle" size="compact-xs" onClick={reset} data-testid="font-size-reset">
            Reset
          </Button>
        )}
      </Group>
    </Field>
  );
};

export default UiScaleField;
