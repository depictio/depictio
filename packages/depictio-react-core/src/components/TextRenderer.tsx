import React, { useRef } from 'react';
import { Anchor, Divider, List, Stack, Table, Text, Title } from '@mantine/core';

import { StoredMetadata } from '../api';
import { useAutofitHeight } from './autofit';
import { parseBlocks } from './blockMarkdown';
import Glyph from './Glyph';
import { parseInlineMarkdown } from './inlineMarkdown';
import { TabLinkResolver, useTabLinkResolver } from './tabLinks';

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
const renderInlineMarkdown = (
  input: string,
  resolveTab: TabLinkResolver | null = null,
): React.ReactNode[] =>
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
        if (token.href.startsWith('tab:')) {
          // A tab link wears the tab's own icon and colour, so it reads as the
          // tab it opens. Unresolved (unknown name, or a renderer with no tab
          // family, like the editor preview), it stays plain text: a dead
          // anchor would be worse than none.
          const target = resolveTab?.(token.href.slice(4)) ?? null;
          if (!target) return <React.Fragment key={idx}>{token.value}</React.Fragment>;
          return (
            <Anchor
              key={idx}
              href={target.href}
              inherit
              fw={600}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, verticalAlign: 'bottom' }}
            >
              {target.icon ? <Glyph icon={target.icon} color={target.color} size={16} /> : null}
              {token.value}
            </Anchor>
          );
        }
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

const BODY_TEXT_STYLE: React.CSSProperties = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  margin: 0,
  lineHeight: 1.35,
};

/**
 * A body's blocks (see `blockMarkdown.ts`). A body with no block syntax is one
 * paragraph and renders as the single pre-wrapped paragraph bodies always were.
 * Headings start one level below the tile's own title scale (`#` → H3), so a
 * body never outshouts the title above it.
 */
const MarkdownBody: React.FC<{ body: string; alignment: 'left' | 'center' | 'right' }> = ({
  body,
  alignment,
}) => {
  const resolveTab = useTabLinkResolver();
  const inline = (text: string) => renderInlineMarkdown(text, resolveTab);
  return (
    <>
      {parseBlocks(body).map((block, idx) => {
        switch (block.type) {
          case 'heading':
            return (
              <Title
                key={idx}
                order={(block.level + 2) as 3 | 4 | 5}
                ta={alignment}
                style={{ margin: idx === 0 ? 0 : '8px 0 0', lineHeight: 1.2 }}
              >
                {inline(block.text)}
              </Title>
            );
          case 'list': {
            return (
              <List
                key={idx}
                type={block.ordered ? 'ordered' : 'unordered'}
                spacing={4}
                style={{ lineHeight: 1.45, textAlign: 'left' }}
              >
                {block.items.map((item, i) => (
                  <List.Item key={i}>{inline(item)}</List.Item>
                ))}
              </List>
            );
          }
          case 'table':
            return (
              <Table key={idx} withTableBorder={false} verticalSpacing={6} highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    {block.header.map((cell, i) => (
                      <Table.Th key={i} style={{ textAlign: block.align[i] ?? 'left' }}>
                        {inline(cell)}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {block.rows.map((row, r) => (
                    <Table.Tr key={r}>
                      {block.header.map((_, i) => (
                        <Table.Td key={i} style={{ textAlign: block.align[i] ?? 'left' }}>
                          {inline(row[i] ?? '')}
                        </Table.Td>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            );
          case 'rule':
            return <Divider key={idx} my={4} />;
          default:
            return (
              <Text key={idx} ta={alignment} style={BODY_TEXT_STYLE}>
                {inline(block.text)}
              </Text>
            );
        }
      })}
    </>
  );
};

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
        // 8px between blocks: paragraphs, lists and tables need air that a
        // title-over-paragraph pair never did.
        style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}
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
      {body ? <MarkdownBody body={body} alignment={alignment} /> : null}
      </div>
    </Stack>
  );
};

export default TextRenderer;
