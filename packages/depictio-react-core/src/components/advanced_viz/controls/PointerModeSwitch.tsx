import React from 'react';
import { Center, SegmentedControl, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface PointerMode<M extends string> {
  value: M;
  label: string;
  icon: string;
  tooltip: string;
  /** Offered greyed out with this reason, rather than hidden. */
  disabledReason?: string | null;
}

interface Props<M extends string> {
  value: M;
  modes: readonly PointerMode<M>[];
  onChange: (mode: M) => void;
  'aria-label'?: string;
  /** `data-testid` of the control; each mode gets `${testIdPrefix}-${mode}`. */
  testId?: string;
  testIdPrefix?: string;
}

/**
 * What the pointer does on a tile's canvas (pan, select a region, lasso
 * cells): icons with a tooltip each, small enough for the header line. The
 * mode is a tool the reader switches, so it sits there and not in Settings.
 * Shared by the genome view and the bioimage viewer.
 */
export default function PointerModeSwitch<M extends string>({
  value,
  modes,
  onChange,
  'aria-label': ariaLabel = 'Interaction mode',
  testId,
  testIdPrefix,
}: Props<M>): React.ReactElement {
  return (
    <SegmentedControl
      size="xs"
      radius="sm"
      value={value}
      onChange={(v) => onChange(v as M)}
      aria-label={ariaLabel}
      data-testid={testId}
      data={modes.map((mode) => ({
        value: mode.value,
        disabled: Boolean(mode.disabledReason),
        label: (
          <Tooltip
            label={mode.disabledReason || mode.tooltip}
            multiline
            w={220}
            withArrow
            openDelay={250}
          >
            <Center
              data-testid={testIdPrefix ? `${testIdPrefix}-${mode.value}` : undefined}
              aria-label={mode.label}
            >
              <Icon icon={mode.icon} width={14} />
            </Center>
          </Tooltip>
        ),
      }))}
    />
  );
}
