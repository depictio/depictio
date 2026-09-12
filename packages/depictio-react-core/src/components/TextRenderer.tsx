import React, { useRef } from 'react';
import { Anchor, Stack, Text, Title } from '@mantine/core';

import { StoredMetadata } from '../api';
import { useAutofitHeight } from './autofit';
import { parseInlineMarkdown } from './inlineMarkdown';

interface TextRendererProps {
  metadata: StoredMetadata;
  /** When true (editor preview), show a dimmed placeholder if title is empty.
   *  Renderers in the viewer pass `false` so empty titles render as nothing. */
  placeholder?: boolean;
}

/**
 * Maps the body's inline-markdown tokens to React nodes. The grammar itself
 * lives in `inlineMarkdown.ts` so it can be unit-tested without a DOM.
 */
const renderInlineMarkdown = (input: string): React.ReactNode[] =>
  parseInlineMarkdown(input).map((token, idx) => {
    switch (token.type) {
      case 'bold':
        return <strong key={idx}>{token.value}</strong>;
      case 'italic':
        return <em key={idx}>{token.value}</em>;
      case 'code':
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
            {token.value}
          </code>
        );
      case 'link':
        return (
          <Anchor
            key={idx}
            href={token.href}
            // A dashboard is a working surface: an outbound link opens beside
            // it, never over it. Same-origin paths navigate in place.
            target={token.external ? '_blank' : undefined}
            rel={token.external ? 'noopener noreferrer' : undefined}
            inherit
          >
            {token.value}
          </Anchor>
        );
      default:
        return <React.Fragment key={idx}>{token.value}</React.Fragment>;
    }
  });

/**
 * Pure-presentational renderer for the `text` component_type — section
 * headings + optional body, used to document and organize a dashboard.
 *
 * Fields read from metadata:
 *   - title (string)
 *   - order (1-6 → H1..H6; clamped)
 *   - alignment ('left' | 'center' | 'right'; default 'left')
 *   - vertical_alignment ('top' | 'center' | 'bottom'; default 'center')
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
  const vAlignRaw =
    typeof metadata.vertical_alignment === 'string' ? metadata.vertical_alignment : 'center';
  // Flex `justify` on the column Stack — visible only where the tile is taller
  // than the text it holds.
  const justify =
    vAlignRaw === 'center' ? 'center' : vAlignRaw === 'bottom' ? 'flex-end' : 'flex-start';
  const body = typeof metadata.body === 'string' ? metadata.body : '';

  const hasTitle = rawTitle.trim().length > 0;

  // Measure the prose itself, not the tile. The Stack below is `h="100%"`, so
  // it always reports the height it was given; this inner wrapper is
  // height-auto, so its scrollHeight is what the text actually needs.
  const contentRef = useRef<HTMLDivElement | null>(null);
  const index = typeof metadata.index === 'string' ? metadata.index : '';
  useAutofitHeight(index, contentRef, [rawTitle, body, order, alignment]);

  return (
    <Stack
      gap={4}
      h="100%"
      justify={justify}
      // `flex` alongside `h="100%"`: the chrome wrapper and the builder's
      // preview Card are both column flex containers whose height can be
      // indefinite, where a percentage height alone collapses to the content
      // and vertical alignment would have no room to act.
      style={{ flex: '1 1 auto', textAlign: alignment, width: '100%', padding: 0 }}
    >
      <div
        ref={contentRef}
        style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%' }}
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
      </div>
    </Stack>
  );
};

export default TextRenderer;
