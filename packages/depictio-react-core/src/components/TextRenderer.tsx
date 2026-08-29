import React, { useEffect, useRef } from 'react';
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
 * Emitted on every change to a text tile's natural content height, so the grid
 * can size the tile to its prose instead of the other way round.
 *
 * A CustomEvent rather than a prop: the only path from here to DashboardGrid
 * runs through ComponentRenderer, and threading a measurement callback through
 * every renderer to serve one of them is not worth it. The grid already listens
 * for panel events this way.
 */
export const TEXT_AUTOFIT_EVENT = 'depictio:text-autofit';

export interface TextAutofitDetail {
  index: string;
  /** Natural height of title + body, in px, independent of the tile. */
  height: number;
}

/**
 * Last height published per component index.
 *
 * The event alone is not enough: React runs a child's effects before its
 * parent's, so a text tile measures and dispatches before DashboardGrid has
 * added its listener, and that first measurement — the only one a tile whose
 * prose never reflows will ever make — is dispatched to nobody. The grid seeds
 * itself from here on mount and listens for the rest.
 */
const measuredHeights = new Map<string, number>();

/** Every height measured so far, for a consumer mounting after the tiles. */
export const textAutofitHeights = (): ReadonlyMap<string, number> => measuredHeights;

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
  useEffect(() => {
    const node = contentRef.current;
    if (!node || !index || typeof ResizeObserver === 'undefined') return;
    let last = -1;
    const publish = () => {
      const height = node.scrollHeight;
      // Only on change: the grid re-renders on receipt, which re-runs the
      // observer, and an unconditional dispatch would loop.
      if (height === last) return;
      last = height;
      measuredHeights.set(index, height);
      window.dispatchEvent(
        new CustomEvent<TextAutofitDetail>(TEXT_AUTOFIT_EVENT, {
          detail: { index, height },
        }),
      );
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => observer.disconnect();
  }, [index, rawTitle, body, order, alignment]);

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
