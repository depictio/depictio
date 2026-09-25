import React from 'react';
import { Slider, Stack, Switch, Text } from '@mantine/core';

import { FILL_OPACITY_MAX, FILL_OPACITY_MIN } from '../../annotations/edit';

const percent = (v: number) => `${Math.round(v * 100)}%`;

export interface LabelledSliderProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  format?: (value: number) => string;
  testId?: string;
}

/** A small Mantine slider with its caption, for the annotation style controls. */
export const LabelledSlider: React.FC<LabelledSliderProps> = ({
  label,
  value,
  onChange,
  min,
  max,
  step,
  format,
  testId,
}) => (
  <Stack gap={2}>
    <Text size="xs" fw={500}>
      {label}
    </Text>
    <Slider
      size="sm"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={onChange}
      label={format ?? ((v) => String(v))}
      aria-label={label}
      data-testid={testId}
    />
  </Stack>
);

/** An opacity slider over the fill range (5% to 60%). */
export const OpacitySlider: React.FC<Omit<LabelledSliderProps, 'min' | 'max' | 'step' | 'format'>> = (
  props,
) => (
  <LabelledSlider {...props} min={FILL_OPACITY_MIN} max={FILL_OPACITY_MAX} step={0.05} format={percent} />
);

export interface RegionHighlightFieldsProps {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  opacity: number;
  onOpacityChange: (opacity: number) => void;
}

/** Switch and opacity of the shaded area behind lassoed or boxed points. */
export const RegionHighlightFields: React.FC<RegionHighlightFieldsProps> = ({
  enabled,
  onEnabledChange,
  opacity,
  onOpacityChange,
}) => (
  <Stack gap={6}>
    <Switch
      size="xs"
      label="Highlight the selected area"
      checked={enabled}
      onChange={(e) => onEnabledChange(e.currentTarget.checked)}
      data-testid="annotation-region-switch"
    />
    {enabled && (
      <OpacitySlider
        label="Area opacity"
        value={opacity}
        onChange={onOpacityChange}
        testId="annotation-region-opacity"
      />
    )}
  </Stack>
);
