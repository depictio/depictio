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
import { ANNOTATION_COLORS } from '../../annotations/types';
import type { AnnotationColor } from '../../annotations/types';

export interface AnnotationColorPickerProps {
  value: AnnotationColor;
  onChange: (color: AnnotationColor) => void;
}

/**
 * Palette swatches of an annotation. Colours are Mantine palette names
 * resolved like the shapes (default palette, light/dark aware), so a brand
 * theme cannot change what the swatches show.
 */
const AnnotationColorPicker: React.FC<AnnotationColorPickerProps> = ({ value, onChange }) => {
  const scheme = useComputedColorScheme('light');
  return (
    <Stack gap={4}>
      <Text size="xs" fw={500}>
        Color
      </Text>
      <Group gap={4}>
        {ANNOTATION_COLORS.map((c) => (
          <Tooltip key={c} label={c} withArrow openDelay={300}>
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
