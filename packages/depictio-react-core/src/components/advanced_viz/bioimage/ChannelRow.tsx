import React, { useState } from 'react';
import {
  Box,
  Checkbox,
  ColorPicker,
  ColorSwatch,
  Popover,
  RangeSlider,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  isColorValid,
} from '@mantine/core';

import { useFullscreenPortalTarget } from '../../chrome/useFullscreenPortalTarget';
import { VIZ_CONTROL_HEIGHT, VIZ_SLIDER_CONTROL_PX } from '../controls/VizControls';

/** Colours offered in the picker: the usual fluorescence channels. */
const CHANNEL_SWATCHES = [
  '#0000ff',
  '#00ff00',
  '#ff0000',
  '#ff00ff',
  '#00ffff',
  '#ffff00',
  '#ff8800',
  '#ffffff',
];

export interface ChannelRowProps {
  name: string;
  color: string;
  visible: boolean;
  /** Why the channel cannot be turned on (viv's channel limit), or null. */
  blockedReason?: string | null;
  domain: readonly [number, number];
  step: number;
  contrastLimits: readonly [number, number];
  onVisibleChange: (visible: boolean) => void;
  onColourCommit: (hex: string) => void;
  /** While dragging: the tile redraws, nothing is saved. */
  onContrastChange: (limits: [number, number]) => void;
  /** On release: the window is saved. */
  onContrastCommit: (limits: [number, number]) => void;
}

function formatValue(v: number, step: number): string {
  if (step >= 1) return Math.round(v).toLocaleString();
  return Number(v.toPrecision(3)).toString();
}

/**
 * One channel on one line: a checkbox in the channel's colour shows or hides
 * it, the swatch beside it opens the colour picker, and the slider is the
 * contrast window (values at or below its left end are black, at or above its
 * right end full colour). Three rows per channel made an 8-channel store a
 * long scroll; this keeps each channel one input tall.
 */
const ChannelRow: React.FC<ChannelRowProps> = ({
  name,
  color,
  visible,
  blockedReason,
  domain,
  step,
  contrastLimits,
  onVisibleChange,
  onColourCommit,
  onContrastChange,
  onContrastCommit,
}) => {
  const portalTarget = useFullscreenPortalTarget();
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? color;
  const checkbox = (
    <Checkbox
      size="xs"
      color={color}
      autoContrast
      checked={visible}
      disabled={Boolean(blockedReason)}
      aria-label={`Show ${name}`}
      onChange={(e) => onVisibleChange(e.currentTarget.checked)}
    />
  );
  return (
    <Box
      role="group"
      aria-label={`Channel ${name}`}
      data-testid="bioimage-channel-row"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        minHeight: VIZ_CONTROL_HEIGHT,
        minWidth: 0,
      }}
    >
      {blockedReason ? (
        <Tooltip label={blockedReason} withArrow openDelay={250}>
          <span>{checkbox}</span>
        </Tooltip>
      ) : (
        checkbox
      )}
      <Popover
        withinPortal
        portalProps={{ target: portalTarget }}
        position="bottom-start"
        shadow="md"
        onClose={() => setDraft(null)}
      >
        <Popover.Target>
          <UnstyledButton
            aria-label={`${name} colour`}
            title="Change colour"
            disabled={!visible}
            style={{ display: 'flex', opacity: visible ? 1 : 0.4 }}
          >
            <ColorSwatch color={color} size={14} radius="xs" />
          </UnstyledButton>
        </Popover.Target>
        <Popover.Dropdown p="xs">
          <Stack gap={6}>
            <ColorPicker
              size="xs"
              format="hex"
              value={isColorValid(shown) ? shown : color}
              swatches={CHANNEL_SWATCHES}
              swatchesPerRow={8}
              onChange={(v) => {
                setDraft(v);
                onColourCommit(v);
              }}
            />
            <TextInput
              size="xs"
              aria-label={`${name} colour hex`}
              value={shown}
              onChange={(e) => {
                const v = e.currentTarget.value;
                setDraft(v);
                if (isColorValid(v)) onColourCommit(v);
              }}
            />
          </Stack>
        </Popover.Dropdown>
      </Popover>
      <Text
        size="xs"
        fw={500}
        truncate
        title={name}
        c={visible ? undefined : 'dimmed'}
        style={{ flex: '0 1 auto', minWidth: 0, maxWidth: '45%' }}
      >
        {name}
      </Text>
      <Box style={{ flex: '1 1 0', minWidth: 64, maxWidth: VIZ_SLIDER_CONTROL_PX, marginLeft: 'auto' }}>
        <RangeSlider
          size="xs"
          color={color}
          min={domain[0]}
          max={domain[1]}
          step={step}
          minRange={0}
          value={[contrastLimits[0], contrastLimits[1]]}
          disabled={!visible}
          label={(v) => formatValue(v, step)}
          aria-label={`${name} contrast`}
          thumbFromLabel={`${name} contrast, black at`}
          thumbToLabel={`${name} contrast, full colour at`}
          onChange={onContrastChange}
          onChangeEnd={onContrastCommit}
        />
      </Box>
    </Box>
  );
};

export default ChannelRow;
