import React from 'react';
import { Stack, Text, Title } from '@mantine/core';

import { StoredMetadata } from '../api';

interface TextRendererProps {
  metadata: StoredMetadata;
  /** When true (editor preview), show a dimmed placeholder if title is empty.
   *  Renderers in the viewer pass `false` so empty titles render as nothing. */
  placeholder?: boolean;
}

/**
 * Pure-presentational renderer for the `text` component_type — section
 * headings + optional body, used to document and organize a dashboard.
 *
 * Fields read from metadata:
 *   - title (string)
 *   - order (1-6 → H1..H6; clamped)
 *   - alignment ('left' | 'center' | 'right'; default 'left')
 *   - body (optional paragraph)
 *
 * No data fetching, no editing UI. Same shape in viewer and editor — the
 * editor injects its own action chrome (incl. the Edit menu) around it.
 */
const TextRenderer: React.FC<TextRendererProps> = ({ metadata, placeholder = false }) => {
  const rawTitle = typeof metadata.title === 'string' ? metadata.title : '';
  const rawOrder = Number(metadata.order);
  const order = (Number.isFinite(rawOrder)
    ? Math.min(6, Math.max(1, Math.trunc(rawOrder)))
    : 1) as 1 | 2 | 3 | 4 | 5 | 6;
  const alignmentRaw =
    typeof metadata.alignment === 'string' ? metadata.alignment : 'left';
  const alignment: 'left' | 'center' | 'right' =
    alignmentRaw === 'center' || alignmentRaw === 'right' ? alignmentRaw : 'left';
  const body = typeof metadata.body === 'string' ? metadata.body : '';

  const hasTitle = rawTitle.trim().length > 0;

  return (
    <Stack
      gap="xs"
      h="100%"
      justify="flex-start"
      style={{ textAlign: alignment, width: '100%' }}
    >
      {hasTitle ? (
        <Title order={order} ta={alignment} style={{ wordBreak: 'break-word' }}>
          {rawTitle}
        </Title>
      ) : placeholder ? (
        <Title order={order} ta={alignment} c="dimmed" style={{ fontStyle: 'italic' }}>
          Section title
        </Title>
      ) : null}
      {body ? (
        <Text ta={alignment} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {body}
        </Text>
      ) : null}
    </Stack>
  );
};

export default TextRenderer;
