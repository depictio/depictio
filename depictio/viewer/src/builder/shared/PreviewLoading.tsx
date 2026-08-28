import React from 'react';
import { Center, Loader, Stack, Text } from '@mantine/core';

/**
 * The builder's one loading treatment for a preview surface.
 *
 * Extracted from `PreviewPanel` so every preview that can be mid-flight shows
 * the same thing: the design-step panel, the advanced-viz live preview, and the
 * catalog picker's iframe. Absolutely positioned, so the caller keeps whatever
 * it was already showing underneath and only needs `position: relative`.
 */
const PreviewLoading: React.FC<{ label?: string }> = ({ label = 'Updating preview…' }) => (
  <Center style={{ position: 'absolute', inset: 0, zIndex: 2 }}>
    <Stack align="center" gap={4}>
      <Loader size="sm" />
      <Text size="xs" c="dimmed">
        {label}
      </Text>
    </Stack>
  </Center>
);

export default PreviewLoading;
