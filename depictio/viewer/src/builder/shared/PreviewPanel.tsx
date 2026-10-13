/**
 * Right-side live preview pane for the component design step.
 *
 * Mirrors the Dash `component-container` div: a bordered box that re-renders
 * every time the form below it changes. Provides loading + error states so
 * each builder doesn't reimplement them.
 */
import React from 'react';
import { Card, Center, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import PreviewLoading from './PreviewLoading';

interface Props {
  loading?: boolean;
  /** Overrides the loading label — see `PreviewLoading`. */
  loadingLabel?: string;
  error?: string | null;
  empty?: boolean;
  emptyMessage?: string;
  minHeight?: number | string;
  children?: React.ReactNode;
}

const PreviewPanel: React.FC<Props> = ({
  loading,
  loadingLabel,
  error,
  empty,
  emptyMessage,
  minHeight = 360,
  children,
}) => {
  return (
    <Card
      withBorder
      radius="md"
      p="md"
      style={{
        minHeight,
        height: '100%',
        position: 'relative',
        background: 'var(--mantine-color-body)',
      }}
    >
      {loading && <PreviewLoading label={loadingLabel} />}
      {error && !loading && (
        <Group gap="xs" align="flex-start" mt="sm">
          <Icon icon="mdi:alert-circle" width={18} color="var(--mantine-color-red-6)" />
          <Text size="sm" c="red">
            {error}
          </Text>
        </Group>
      )}
      {empty && !loading && !error && (
        <Center style={{ minHeight }}>
          <Text size="sm" c="dimmed">
            {emptyMessage || 'Configure the form to see a live preview.'}
          </Text>
        </Center>
      )}
      {!empty && children}
    </Card>
  );
};

export default PreviewPanel;
