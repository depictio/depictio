import React, { useLayoutEffect, useRef, useState } from 'react';
import { Anchor, Divider, List, Stack, Table, Text, Title } from '@mantine/core';

import { StoredMetadata } from '../api';
import { useAutofitHeight } from './autofit';
import {
  Block,
  Fact,
  isLinksOnly,
  LinkRow,
  parseBlocks,
  parseFact,
  parseLinkRow,
  parseStatRow,
  StatRow,
} from './blockMarkdown';
import { CARD_FRAME, CARD_RULE, RESTING_ICON_OPACITY } from './cardFrame';
import Glyph, { glyphColorVar } from './Glyph';
import { parseInlineMarkdown } from './inlineMarkdown';
import { openRunParameters } from '../utils/runParameters';
import StepFlow from './StepFlow';
import TabTiles from './TabTiles';
import { parseTabTile, TabLinkResolver, TabTileItem, useTabLinkResolver } from './tabLinks';

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
      case 'icon':
        return (
          <Glyph
            key={idx}
            icon={token.name}
            size={16}
            style={{ display: 'inline-block', verticalAlign: '-0.15em' }}
          />
        );
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
              // In the tab's colour as well as its icon: the link is the tab.
              c={target.color ? glyphColorVar(target.color) : undefined}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, verticalAlign: 'bottom' }}
            >
              {target.icon ? <Glyph icon={target.icon} color={target.color} size={16} /> : null}
              {token.value}
            </Anchor>
          );
        }
        if (token.href.startsWith('params:')) {
          // The run's parameters, opened in the viewer's dialog rather than
          // navigated to: there is no page of them to go to.
          const query = token.href.slice('params:'.length);
          return (
            <Anchor
              key={idx}
              component="button"
              type="button"
              inherit
              fw={600}
              onClick={() => openRunParameters(query)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, verticalAlign: 'bottom' }}
            >
              <Glyph icon="mdi:tune-variant" color="currentColor" size={16} />
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

/**
 * A tile's accent as CSS: a palette name, a literal colour, or `tab:<name>`
 * for the colour that tab wears in the sidebar. Null when unset or when the
 * tab is unknown here (the editor preview has no tab family).
 */
function resolveAccent(raw: unknown, resolveTab: TabLinkResolver | null): string | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const accent = raw.trim();
  if (accent.startsWith('tab:')) {
    const target = resolveTab?.(accent.slice(4)) ?? null;
    return target?.color ? glyphColorVar(target.color) : null;
  }
  return glyphColorVar(accent);
}

const PAD_Y = 16;

/** The icon of a `tab:<name>` accent: a finding card rests its tab's mark. */
function accentIcon(raw: unknown, resolveTab: TabLinkResolver | null): string | null {
  if (typeof raw !== 'string' || !raw.trim().startsWith('tab:')) return null;
  return resolveTab?.(raw.trim().slice(4))?.icon ?? null;
}

/**
 * The frame a surface draws, and the height it adds around the prose. `card`
 * matches a metric card's border and radius so the two sit in one row; its
 * accent is a rule along the top. `tinted` lays the prose on a wash of the
 * accent, grey without one.
 */
function surfaceStyle(
  surface: 'none' | 'card' | 'tinted',
  accent: string | null,
): { style: React.CSSProperties; extra: number } {
  if (surface === 'card') {
    // A metric card's frame, so a finding sits in a row of key figures as one
    // of them; the accent moves to the resting icon and the footer link.
    return {
      style: { ...CARD_FRAME, padding: `${PAD_Y}px 18px`, position: 'relative' },
      extra: PAD_Y * 2 + 3,
    };
  }
  if (surface === 'tinted') {
    const base = accent ?? 'var(--mantine-color-gray-6)';
    return {
      style: {
        padding: `${PAD_Y}px 18px`,
        borderRadius: 'var(--mantine-radius-md)',
        background: `color-mix(in srgb, ${base} 8%, var(--mantine-color-body))`,
      },
      extra: PAD_Y * 2,
    };
  }
  return { style: {}, extra: 0 };
}

const BODY_TEXT_STYLE: React.CSSProperties = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  margin: 0,
  lineHeight: 1.35,
};

/**
 * Prose stops at a reading measure. A full-width tile on a wide screen ran
 * paragraphs to ~180 characters a line, where the eye loses the next line's
 * start. Tables, tiles and strips keep the tile's width.
 */
const PROSE_MEASURE = '80ch';
function proseWidth(alignment: 'left' | 'center' | 'right'): React.CSSProperties {
  return {
    maxWidth: PROSE_MEASURE,
    marginInline: alignment === 'center' ? 'auto' : alignment === 'right' ? 'auto 0' : undefined,
  };
}

/**
 * A list of `![](icon:…) **Label** value` items, drawn as one line of
 * metadata under a title: a quiet icon, a dimmed label, the value. Unframed
 * and in grey on purpose: a study's method (pipeline, markers, databases,
 * sites, period) is context for the page, not one more box competing with
 * the cards below it. Wraps to as many lines as the width needs.
 */
const FactLine: React.FC<{
  facts: Fact[];
  inline: (text: string) => React.ReactNode[];
}> = ({ facts, inline }) => (
  <div
    style={{
      display: 'flex',
      flexWrap: 'wrap',
      gap: '6px 22px',
      width: '100%',
      margin: '2px 0 6px',
      fontSize: 'var(--mantine-font-size-sm)',
      lineHeight: 1.4,
    }}
  >
    {facts.map((fact, i) => (
      <span
        key={i}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
      >
        {fact.icon ? (
          <Glyph icon={fact.icon} color="var(--mantine-color-dimmed)" size={15} />
        ) : null}
        <span style={{ color: 'var(--mantine-color-dimmed)' }}>{fact.label}</span>
        <span style={{ fontWeight: 600 }}>{inline(fact.value)}</span>
      </span>
    ))}
  </div>
);

/**
 * The same facts on a framed tile: a two-column table, labels over a hairline
 * per row. A card beside the prose (a study's method and run parameters) is
 * read as a reference, down a column, where a line of facts is read across.
 */
const FactTable: React.FC<{
  facts: Fact[];
  inline: (text: string) => React.ReactNode[];
}> = ({ facts, inline }) => (
  <div
    style={{
      display: 'grid',
      gridTemplateColumns: 'max-content minmax(0, 1fr)',
      columnGap: 18,
      width: '100%',
      fontSize: 'var(--mantine-font-size-sm)',
      lineHeight: 1.4,
    }}
  >
    {facts.map((fact, i) => {
      const cell: React.CSSProperties = {
        padding: '6px 0',
        borderTop: i === 0 ? undefined : `1px solid ${CARD_RULE}`,
      };
      return (
        <React.Fragment key={i}>
          <span
            style={{
              ...cell,
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              color: 'var(--mantine-color-dimmed)',
            }}
          >
            {fact.icon ? (
              <Glyph icon={fact.icon} color="var(--mantine-color-dimmed)" size={15} />
            ) : null}
            {fact.label}
          </span>
          <span style={{ ...cell, fontWeight: 600, minWidth: 0 }}>{inline(fact.value)}</span>
        </React.Fragment>
      );
    })}
  </div>
);

/**
 * A list of `**41%** Claim — context [Tab](tab:Name)` items, drawn as result
 * rows: the figure in its tab's colour, the claim over its context, the way
 * in on the right. Reads like an abstract's key results, set apart from the
 * metric cards a landing page also carries (which state what was measured,
 * not what was found), and as one panel it takes the height its rows need
 * instead of a card's worth of grid rows each.
 */
const StatList: React.FC<{
  rows: StatRow[];
  inline: (text: string) => React.ReactNode[];
  resolveTab: TabLinkResolver | null;
}> = ({ rows, inline, resolveTab }) => (
  <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
    {rows.map((row, i) => {
      const tabName = row.link ? /\]\(tab:(.+)\)$/.exec(row.link)?.[1] ?? null : null;
      const color = tabName ? resolveTab?.(tabName)?.color ?? null : null;
      return (
        <div
          key={i}
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            columnGap: 20,
            rowGap: 4,
            padding: '12px 0',
            borderTop: i === 0 ? undefined : `1px solid ${CARD_RULE}`,
          }}
        >
          <span
            style={{
              flex: '0 0 auto',
              minWidth: 92,
              fontSize: 28,
              fontWeight: 800,
              lineHeight: 1.05,
              letterSpacing: '-0.02em',
              fontVariantNumeric: 'tabular-nums',
              color: color ? glyphColorVar(color) : undefined,
            }}
          >
            {row.stat}
          </span>
          <span style={{ flex: '1 1 260px', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <Text size="sm" fw={700} lh={1.35}>
              {inline(row.claim)}
            </Text>
            {row.context ? (
              <Text size="sm" c="dimmed" lh={1.35}>
                {inline(row.context)}
              </Text>
            ) : null}
          </span>
          {row.link ? (
            <Text size="sm" style={{ flex: '0 0 auto', marginLeft: 'auto' }}>
              {inline(row.link)}
            </Text>
          ) : null}
        </div>
      );
    })}
  </div>
);

/**
 * A paragraph of links (see `parseLinkRow`), drawn as one small row: the
 * label dimmed, each link kept whole on its line. A link to a tab this
 * dashboard does not have is dropped rather than left as dead text — a run
 * without that tab's data never gets it, and the row stays true to what is
 * there.
 */
const LinkLine: React.FC<{
  row: LinkRow;
  alignment: 'left' | 'center' | 'right';
  inline: (text: string) => React.ReactNode[];
  resolveTab: TabLinkResolver | null;
}> = ({ row, alignment, inline, resolveTab }) => {
  const links = row.links.filter((link) => {
    const tab = /\]\(tab:(.+)\)$/.exec(link)?.[1];
    return !tab || !resolveTab || resolveTab(tab) !== null;
  });
  if (!links.length) return null;
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent:
          alignment === 'center' ? 'center' : alignment === 'right' ? 'flex-end' : 'flex-start',
        gap: '4px 18px',
        fontSize: 'var(--mantine-font-size-sm)',
        lineHeight: 1.5,
      }}
    >
      {row.label ? (
        <span style={{ color: 'var(--mantine-color-dimmed)', fontWeight: 600 }}>{row.label}</span>
      ) : null}
      {links.map((link, i) => (
        <span key={i} style={{ whiteSpace: 'nowrap' }}>
          {inline(link)}
        </span>
      ))}
    </div>
  );
};

/** A short heading carrying a number: `41%`, `7.08`, `×3`, `n = 85`. */
function isFigure(text: string): boolean {
  return /\d/.test(text) && text.trim().length <= 12;
}

/**
 * A body's blocks (see `blockMarkdown.ts`). A body with no block syntax is one
 * paragraph and renders as the single pre-wrapped paragraph bodies always were.
 * Headings start one level below the tile's own title scale (`#` → H3), so a
 * body never outshouts the title above it.
 */
const MarkdownBody: React.FC<{
  blocks: Block[];
  alignment: 'left' | 'center' | 'right';
  /** The tile's accent, for what a body tints (a fact strip's icons). */
  accentColor?: string | null;
  /** On a framed tile: a leading heading becomes the headline figure, the
   *  line under it its caption. */
  framed?: boolean;
}> = ({ blocks, alignment, accentColor = null, framed = false }) => {
  const resolveTab = useTabLinkResolver();
  const inline = (text: string) => renderInlineMarkdown(text, resolveTab);
  // A framed tile opening on a figure (`# 41%`) sets it as a headline number;
  // a framed tile opening on a word (`### Study`) keeps it a heading.
  const first = blocks[0];
  const figureHead = framed && first?.type === 'heading' && isFigure(first.text);
  return (
    <>
      {blocks.map((block, idx) => {
        switch (block.type) {
          case 'heading':
            if (figureHead && idx === 0) {
              // A finding card opens on its number ("# 41%"), set as a
              // headline metric card sets its value.
              return (
                <Text
                  key={idx}
                  ta={alignment}
                  fw={800}
                  style={{
                    fontSize: block.level === 1 ? 40 : block.level === 2 ? 30 : 24,
                    lineHeight: 1.05,
                    letterSpacing: '-0.02em',
                    fontVariantNumeric: 'tabular-nums',
                    margin: 0,
                  }}
                >
                  {inline(block.text)}
                </Text>
              );
            }
            return (
              <Title
                key={idx}
                order={(block.level + 2) as 3 | 4 | 5}
                ta={alignment}
                // Air above a heading that follows other blocks, so it opens
                // what comes next rather than closing what came before.
                style={{ margin: idx === 0 ? '0 0 2px' : '14px 0 2px', lineHeight: 1.2 }}
              >
                {inline(block.text)}
              </Title>
            );
          case 'list': {
            const stats = block.items.map(parseStatRow);
            if (stats.length && stats.every(Boolean)) {
              return (
                <StatList
                  key={idx}
                  rows={stats as StatRow[]}
                  inline={inline}
                  resolveTab={resolveTab}
                />
              );
            }
            const facts = block.items.map(parseFact);
            if (facts.length && facts.every(Boolean)) {
              // Numbered facts are steps: their order is what they say.
              if (block.ordered) {
                return (
                  <StepFlow
                    key={idx}
                    steps={facts as Fact[]}
                    inline={inline}
                    accentColor={accentColor}
                  />
                );
              }
              return framed ? (
                <FactTable key={idx} facts={facts as Fact[]} inline={inline} />
              ) : (
                <FactLine key={idx} facts={facts as Fact[]} inline={inline} />
              );
            }
            const tiles = resolveTab ? block.items.map(parseTabTile) : [];
            if (tiles.length && tiles.every(Boolean)) {
              return (
                <TabTiles
                  key={idx}
                  items={tiles as TabTileItem[]}
                  ordered={block.ordered}
                  resolveTab={resolveTab as TabLinkResolver}
                />
              );
            }
            return (
              <List
                key={idx}
                type={block.ordered ? 'ordered' : 'unordered'}
                spacing={4}
                // Mantine lays an item out as an inline-flex wrapper, which
                // sizes to its text instead of the tile: long items ran past
                // the edge and were clipped. Inline flow wraps them.
                styles={{ itemWrapper: { display: 'inline' }, itemLabel: { display: 'inline' } }}
                style={{
                  lineHeight: 1.45,
                  textAlign: 'left',
                  paddingRight: 4,
                  ...proseWidth(alignment),
                }}
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
          default: {
            const linkRow = parseLinkRow(block.text);
            if (linkRow) {
              return (
                <LinkLine
                  key={idx}
                  row={linkRow}
                  alignment={alignment}
                  inline={inline}
                  resolveTab={resolveTab}
                />
              );
            }
            if (framed) {
              // On a card: the line under its number is that number's caption,
              // dimmed like a metric card's; the prose after it is card text.
              const caption = idx === 1 && figureHead;
              return (
                <Text
                  key={idx}
                  ta={alignment}
                  size="sm"
                  c={caption ? 'dimmed' : undefined}
                  style={{ ...BODY_TEXT_STYLE, lineHeight: 1.45, marginTop: caption ? -4 : 0 }}
                >
                  {inline(block.text)}
                </Text>
              );
            }
            return (
              <Text key={idx} ta={alignment} style={{ ...BODY_TEXT_STYLE, ...proseWidth(alignment) }}>
                {inline(block.text)}
              </Text>
            );
          }
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
 *   - surface ('none' | 'card' | 'tinted'; default 'none') and accent
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

  const resolveTab = useTabLinkResolver();
  const surface =
    metadata.surface === 'card' || metadata.surface === 'tinted' ? metadata.surface : 'none';
  const accentColor = resolveAccent(metadata.accent, resolveTab);
  const frame = surfaceStyle(surface, accentColor);
  const restingIcon = surface === 'card' ? accentIcon(metadata.accent, resolveTab) : null;

  // On a framed tile, a closing paragraph of links is the card's footer: it
  // sits on the bottom edge, so the links of a row of cards line up however
  // long each card's prose runs.
  const allBlocks = body ? parseBlocks(body) : [];
  const last = allBlocks[allBlocks.length - 1];
  const footer =
    surface !== 'none' && allBlocks.length > 1 && last?.type === 'paragraph' && isLinksOnly(last.text)
      ? last
      : null;
  const blocks = footer ? allBlocks.slice(0, -1) : allBlocks;
  const footerRef = useRef<HTMLDivElement | null>(null);
  const [footerPx, setFooterPx] = useState(0);
  useLayoutEffect(() => {
    // Outside the measured prose (it is pushed to the bottom, so measuring it
    // with the prose would report the tile), so its height is added back.
    setFooterPx(footerRef.current ? footerRef.current.offsetHeight + 12 : 0);
  }, [footer?.type === 'paragraph' ? footer.text : null]);

  // Measure the prose itself, not the tile. The Stack below is `h="100%"`, so
  // it always reports the height it was given; this inner wrapper is
  // height-auto, so its scrollHeight is what the text actually needs.
  const contentRef = useRef<HTMLDivElement | null>(null);
  const index = typeof metadata.index === 'string' ? metadata.index : '';
  useAutofitHeight(
    index,
    contentRef,
    [rawTitle, body, order, alignment, surface, footerPx],
    // The frame's padding and borders, and a footer, sit outside the measured
    // prose.
    frame.extra || footerPx ? (h) => h + frame.extra + footerPx : undefined,
  );

  return (
    <Stack
      gap={4}
      h="100%"
      justify={justify}
      // `flex` alongside `h="100%"`: the chrome wrapper and the builder's
      // preview Card are both column flex containers whose height can be
      // indefinite, where a percentage height alone collapses to the content
      // and vertical alignment would have no room to act.
      style={{
        flex: '1 1 auto',
        textAlign: alignment,
        width: '100%',
        padding: 0,
        boxSizing: 'border-box',
        ...frame.style,
      }}
    >
      {restingIcon ? (
        // The tab's mark, resting faint in the corner as a headline metric
        // card rests its icon: which tab a finding comes from, at a glance.
        <span
          aria-hidden
          style={{
            position: 'absolute',
            top: 16,
            right: 16,
            opacity: RESTING_ICON_OPACITY,
            pointerEvents: 'none',
          }}
        >
          <Glyph icon={restingIcon} color={accentColor} size={36} />
        </span>
      ) : null}
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
      {blocks.length ? (
        <MarkdownBody
          blocks={blocks}
          alignment={alignment}
          accentColor={surface !== 'none' ? accentColor : null}
          framed={surface !== 'none'}
        />
      ) : null}
      </div>
      {footer ? (
        <div ref={footerRef} style={{ marginTop: 'auto', paddingTop: 12 }}>
          <MarkdownBody blocks={[footer]} alignment={alignment} />
        </div>
      ) : null}
    </Stack>
  );
};

export default TextRenderer;
