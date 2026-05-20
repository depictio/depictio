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
 * Tiny inline-markdown parser for the body field. Handles the three formats
 * users reach for in section descriptions:
 *   `**bold**`   -> <strong>
 *   `*italic*`   -> <em>
 *   \`code\`     -> <code>
 *
 * We deliberately do NOT pull in react-markdown / remark / rehype — the body
 * is a single paragraph, and a regex pass is ~30 lines vs ~30 KB of deps.
 * Anything more complex (links, lists, images) should use a proper image /
 * table / link component instead.
 */
const renderInlineMarkdown = (input: string): React.ReactNode[] => {
  // Pattern order matters: `code` first (greedy backticks), then `**bold**`
  // (two-asterisk), then `*italic*` (single-asterisk). The capture groups
  // come back in lockstep with the split() chunks.
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g;
  const parts = input.split(pattern);
  return parts.map((part, idx) => {
    if (!part) return null;
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length >= 3) {
      return <em key={idx}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length >= 3) {
      return (
        <code
          key={idx}
          style={{
            background: 'var(--mantine-color-default-hover, rgba(127,127,127,0.12))',
            padding: '1px 4px',
            borderRadius: 3,
            fontSize: '0.92em',
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
};

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
      gap={4}
      h="100%"
      justify="flex-start"
      style={{ textAlign: alignment, width: '100%', padding: 0 }}
    >
      {hasTitle ? (
        <Title
          order={order}
          ta={alignment}
          style={{ wordBreak: 'break-word', margin: 0, lineHeight: 1.15 }}
        >
          {rawTitle}
        </Title>
      ) : placeholder ? (
        <Title
          order={order}
          ta={alignment}
          c="dimmed"
          style={{ fontStyle: 'italic', margin: 0, lineHeight: 1.15 }}
        >
          Section title
        </Title>
      ) : null}
      {body ? (
        <Text
          ta={alignment}
          style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            margin: 0,
            lineHeight: 1.35,
          }}
        >
          {renderInlineMarkdown(body)}
        </Text>
      ) : null}
    </Stack>
  );
};

export default TextRenderer;
