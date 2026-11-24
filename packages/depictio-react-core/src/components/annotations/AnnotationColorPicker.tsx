import React from 'react';
import {
  ColorSwatch,
  Group,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { annotationColorValue } from '../../annotations/resolveColor';
import { ANNOTATION_COLORS, ANNOTATION_INK } from '../../annotations/types';
import type { AnnotationColorName } from '../../annotations/types';

export interface AnnotationColorPickerProps {
  /** The current colour; the neutral default (`ink`) highlights no swatch. */
  value: AnnotationColorName;
  onChange: (color: AnnotationColorName) => void;
  /**
   * Offer the neutral ink as the first swatch. Only where it can be stored,
   * i.e. as "no colour": a new annotation, or one that has none yet.
   */
  allowInk?: boolean;
}

/**
 * Palette swatches of an annotation. Colours are Mantine palette names
 * resolved like the shapes (default palette, light/dark aware), so a brand
 * theme cannot change what the swatches show.
 */
const AnnotationColorPicker: React.FC<AnnotationColorPickerProps> = ({ value, onChange, allowInk = false }) => {
  const scheme = useComputedColorScheme('light');
  return (
    <Stack gap={4}>
      <Text size="xs" fw={500}>
        Color
      </Text>
      <Group gap={4}>
        {(allowInk ? [ANNOTATION_INK, ...ANNOTATION_COLORS] : ANNOTATION_COLORS).map((c) => (
          <Tooltip key={c} label={c === ANNOTATION_INK ? 'neutral (default)' : c} withArrow openDelay={300}>
            <UnstyledButton onClick={() => onChange(c)} aria-label={`Color ${c}`} aria-pressed={value === c}>
              <ColorSwatch color={annotationColorValue(c, scheme)} size={18} withShadow={value === c}>
                {value === c && (
                  <Icon icon="mdi:check" width={12} style={{ color: 'var(--mantine-color-white)' }} />
                )}
              </ColorSwatch>
            </UnstyledButton>
          </Tooltip>
        ))}
      </Group>
    </Stack>
  );
};

export default AnnotationColorPicker;
