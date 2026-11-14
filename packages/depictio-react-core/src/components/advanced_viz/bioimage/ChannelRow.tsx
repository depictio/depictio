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

/** True for a colour too pale to read as a control on a light surface
 *  (white, the usual colour of a grey-scale channel such as EM). */
export function isPaleColour(hex: string): boolean {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return false;
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.85;
}

export interface ChannelRowProps {
  name: string;
  /** What the channel shows (the config's `description`), for the tooltip. */
  description?: string;
  /** Position along the image's channel axis, for a tooltip without one. */
  index?: number;
  /** The pixel type, so the tooltip can say what the slider's numbers are. */
  dtype?: string;
  color: string;
  visible: boolean;
  /** The image's only channel (a grey-scale EM, say): hiding it would leave
   *  nothing and its colour is rarely the point, so the row is its contrast
   *  window alone. A white swatch beside a checkbox read as two checkboxes. */
  only?: boolean;
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
  description,
  index,
  dtype,
  color,
  visible,
  only,
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
  // A white channel would draw a white checkbox and slider: use the theme's grey.
  const controlColour = isPaleColour(color) ? 'gray' : color;
  const [lo, hi] = contrastLimits;
  const what =
    description ?? (index != null ? `Channel ${index + 1} of the image` : `Channel ${name}`);
  const contrastHelp = (
    <Stack gap={2}>
      <Text size="xs" fw={600}>
        Contrast window of {name}
      </Text>
      <Text size="xs">
        Pixels at or below {formatValue(lo, step)} are drawn black, at or above{' '}
        {formatValue(hi, step)} in full colour, and the values between as a ramp. Narrow it to
        bring out faint detail; widen it if bright parts are flat.
      </Text>
      <Text size="xs" c="dimmed">
        The numbers are the image&apos;s raw {dtype ? `${dtype} ` : ''}pixel values, from{' '}
        {formatValue(domain[0], step)} to {formatValue(domain[1], step)} in this image.
      </Text>
    </Stack>
  );
  const checkbox = only ? null : (
    <Checkbox
      size="xs"
      color={controlColour}
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
      {checkbox ? (
        <Tooltip
          label={blockedReason ?? (visible ? `Hide ${name}` : `Show ${name}`)}
          withArrow
          openDelay={250}
        >
          <span style={{ display: 'flex' }}>{checkbox}</span>
        </Tooltip>
      ) : null}
      {only ? null : (
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
              title={`${name} is drawn in this colour: click to change it`}
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
      )}
      <Tooltip
        label={
          <Stack gap={2}>
            <Text size="xs" fw={600}>
              {name}
            </Text>
            <Text size="xs">{what}</Text>
          </Stack>
        }
        multiline
        maw={300}
        withArrow
        openDelay={250}
      >
        <Text
          size="xs"
          fw={500}
          truncate
          c={visible ? undefined : 'dimmed'}
          style={{
            flex: '0 1 auto',
            minWidth: 0,
            maxWidth: '45%',
            cursor: 'help',
            textDecoration: 'underline dotted',
            textUnderlineOffset: 3,
          }}
        >
          {only ? `${name} contrast` : name}
        </Text>
      </Tooltip>
      <Tooltip label={contrastHelp} multiline maw={320} withArrow openDelay={500}>
      <Box style={{ flex: '1 1 0', minWidth: 64, maxWidth: VIZ_SLIDER_CONTROL_PX, marginLeft: 'auto' }}>
        <RangeSlider
          size="xs"
          color={controlColour}
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
      </Tooltip>
      {/* The window as numbers, always in view: the thumbs only label on drag. */}
      <Text
        size="xs"
        c="dimmed"
        ff="monospace"
        style={{ flex: '0 0 auto', whiteSpace: 'nowrap', opacity: visible ? 1 : 0.5 }}
        data-testid="bioimage-channel-window"
      >
        {formatValue(lo, step)}–{formatValue(hi, step)}
      </Text>
    </Box>
  );
};

export default ChannelRow;
