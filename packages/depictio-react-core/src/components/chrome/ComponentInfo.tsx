import React from 'react';
import {
  ActionIcon,
  Anchor,
  Box,
  Code,
  Divider,
  Group,
  List,
  Popover,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { type Block, parseBlocks } from '../blockMarkdown';
import Glyph from '../Glyph';
import { parseInlineMarkdown } from '../inlineMarkdown';
import { type TabLinkResolver, useTabLinkResolver } from '../tabLinks';
import { TILE_ACTION_STYLE } from './actionStyles';
import {
  firstSentence,
  hasMoreThanSubtitle,
  linkifySource,
  parseSections,
  type Section,
  splitSources,
  splitValues,
  VALUE_SECTIONS,
} from './descriptionText';
import { useTabHue } from '../../tabColor';
import { useFullscreenPortalTarget } from './useFullscreenPortalTarget';

/**
 * A tile's description, shown the one way everywhere.
 *
 * `description` in the dashboard YAML is the single source. It reaches the
 * viewer as:
 *   - a one-line subtitle under the title (`TileSubtitle`: the first
 *     sentence), so the tile keeps the room for its figure;
 *   - an info icon next to the title (`ComponentInfo`, `trigger="title"`)
 *     opening the full text in a popover;
 *   - the same popover from the toolbar icon (`trigger="toolbar"`) on tiles
 *     whose header has no title row to carry it (cards, maps, images...).
 *
 * Both triggers are this one component, so the popover cannot drift between
 * them. It opens on click, Enter or Space and closes on Escape or a click
 * outside; nothing opens on hover alone, so touch and keyboard reach it. It is
 * closed at rest and never opens by itself, which is what keeps it out of the
 * screenshot pipeline's captures.
 */

type Inline = (text: string, values?: boolean) => React.ReactNode[];

/** The popover's accent: the tile's tab hue, else the theme's primary colour. */
const FALLBACK_ACCENT = 'var(--mantine-primary-color-filled)';

/** An inline token's React node. Links keep the body grammar's allowlist: only
 *  http(s), site-relative paths and a resolvable `tab:` name become anchors. */
function inlineNodes(
  text: string,
  resolveTab: TabLinkResolver | null,
  accent: string,
  values = false,
): React.ReactNode[] {
  return parseInlineMarkdown(text).map((token, idx) => {
    switch (token.type) {
      case 'bold':
        return (
          // The full text colour, so a keyword stands out of the dimmed body.
          <Text key={idx} span inherit fw={600} style={{ color: 'var(--mantine-color-text)' }}>
            {token.value}
          </Text>
        );
      case 'italic':
        return <em key={idx}>{token.value}</em>;
      case 'code':
        return (
          <Code
            key={idx}
            style={{
              fontSize: '0.88em',
              color: 'var(--mantine-color-text)',
              // A tint of the accent over whatever the popover sits on, so it
              // shows in both colour schemes.
              background: `color-mix(in srgb, ${accent} 16%, transparent)`,
            }}
          >
            {token.value}
          </Code>
        );
      case 'icon':
        return (
          <Glyph
            key={idx}
            icon={token.name}
            size={16}
            style={{ display: 'inline-block', verticalAlign: '-0.15em' }}
          />
        );
      case 'swatch':
        // A colour key has no meaning without the tile's palette in view.
        return <React.Fragment key={idx}>{token.label}</React.Fragment>;
      case 'link': {
        const { href } = token;
        if (href.startsWith('tab:')) {
          // Navigates in-app, like a tab link in a text tile.
          const target = resolveTab?.(href.slice(4)) ?? null;
          return target ? (
            <Anchor key={idx} href={target.href} inherit fw={600} c={accent} underline="always">
              {token.value}
            </Anchor>
          ) : (
            <React.Fragment key={idx}>{token.value}</React.Fragment>
          );
        }
        if (/^https?:\/\//.test(href)) {
          return (
            <Anchor
              key={idx}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              inherit
              c={accent}
              underline="always"
              style={{ overflowWrap: 'anywhere' }}
            >
              {token.value}
              <Icon
                icon="tabler:external-link"
                width={12}
                height={12}
                aria-hidden
                style={{ marginLeft: 3, verticalAlign: '-0.1em' }}
              />
            </Anchor>
          );
        }
        if (href.startsWith('/')) {
          return (
            <Anchor key={idx} href={href} inherit c={accent} underline="always">
              {token.value}
            </Anchor>
          );
        }
        // `section:`, `params:`, `locus:` act on a dashboard this popover is
        // not part of: the label stays, the dead anchor does not.
        return <React.Fragment key={idx}>{token.value}</React.Fragment>;
      }
      default:
        // In a section that describes what is drawn, a number and its unit
        // are set apart: the full text colour, bold, on the dimmed body, so
        // the value of a line or a zone is found at a glance.
        return values ? (
          <React.Fragment key={idx}>
            {splitValues(token.value).map((seg, i) =>
              seg.value ? (
                <Text
                  key={i}
                  span
                  inherit
                  fw={700}
                  data-value
                  style={{ color: 'var(--mantine-color-text)', whiteSpace: 'nowrap' }}
                >
                  {seg.text}
                </Text>
              ) : (
                <React.Fragment key={i}>{seg.text}</React.Fragment>
              ),
            )}
          </React.Fragment>
        ) : (
          <React.Fragment key={idx}>{token.value}</React.Fragment>
        );
    }
  });
}

/** How a section sets its paragraphs and lists. */
interface BlockStyle {
  size: 'xs' | 'sm' | 'md';
  fw?: number;
  /** Mantine colour prop; unset is the text colour. */
  c?: 'dimmed';
  /** Set the numbers and their units apart (see `splitValues`). */
  values?: boolean;
}

const BlockView: React.FC<{ block: Block; inline: Inline; style: BlockStyle }> = ({
  block,
  inline,
  style,
}) => {
  switch (block.type) {
    case 'heading':
      return (
        <Title order={5} mt={4}>
          {inline(block.text, style.values)}
        </Title>
      );
    case 'paragraph':
      // Authored line breaks inside a paragraph are kept.
      return (
        <Text size={style.size} fw={style.fw} c={style.c} style={{ whiteSpace: 'pre-line' }}>
          {inline(block.text, style.values)}
        </Text>
      );
    case 'list':
      return (
        <List
          size={style.size === 'md' ? 'sm' : style.size}
          c={style.c}
          type={block.ordered ? 'ordered' : 'unordered'}
          spacing={4}
        >
          {block.items.map((item, i) => (
            <List.Item key={i}>{inline(item, style.values)}</List.Item>
          ))}
        </List>
      );
    case 'table':
      return (
        <Table fz="xs" withRowBorders verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              {block.header.map((cell, i) => (
                <Table.Th key={i} ta={block.align[i]}>
                  {inline(cell)}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {block.rows.map((row, r) => (
              <Table.Tr key={r}>
                {row.map((cell, i) => (
                  <Table.Td key={i} ta={block.align[i]}>
                    {inline(cell, style.values)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
    case 'rule':
      return <Divider />;
    case 'div':
      return (
        <>
          {block.blocks.map((inner, i) => (
            <BlockView key={i} block={inner} inline={inline} style={style} />
          ))}
        </>
      );
  }
};

/** The small uppercase heading of a labelled block, callout or footer. */
const SectionLabel: React.FC<{ children: React.ReactNode; color?: string; icon?: string }> = ({
  children,
  color,
  icon,
}) => (
  <Group gap={5} wrap="nowrap" align="center">
    {icon && (
      <Icon icon={icon} width={14} height={14} aria-hidden style={{ color, flex: 'none' }} />
    )}
    <Text
      size="xs"
      fw={700}
      tt="uppercase"
      c={color ? undefined : 'dimmed'}
      style={{ letterSpacing: '0.05em', color }}
    >
      {children}
    </Text>
  </Group>
);

const SectionView: React.FC<{
  section: Section;
  first: boolean;
  inline: Inline;
  accent: string;
}> = ({ section, first, inline, accent }) => {
  const blocks = React.useMemo(() => parseBlocks(section.text), [section.text]);
  const view = (style: BlockStyle) =>
    blocks.map((block, i) => <BlockView key={i} block={block} inline={inline} style={style} />);
  switch (section.kind) {
    case 'lead':
      // What the tile is: the text colour and a step larger than the rest,
      // which is dimmed. Regular weight: bold is for the keywords and values
      // the author marked, so it stays a signal.
      return <Stack gap={6}>{view({ size: 'md' })}</Stack>;
    case 'labelled':
      return (
        <Stack gap={4}>
          {!first && <Divider />}
          <SectionLabel color={accent} icon={section.icon}>
            {section.label}
          </SectionLabel>
          {view({ size: 'sm', c: 'dimmed', values: VALUE_SECTIONS.has(section.label ?? '') })}
        </Stack>
      );
    case 'callout': {
      // A `Note:` follows the tile's tab hue. A `Warning:` or `Caution:` keeps
      // the theme's yellow, which says "careful" whatever the tab. Both use a
      // tint over whatever the popover sits on, so they read in both schemes.
      const warns = section.tone === 'warning' || section.tone === 'caution';
      const tone = warns ? 'var(--mantine-color-yellow-filled)' : accent;
      return (
        <Box
          role="note"
          data-tone={section.tone}
          p="xs"
          style={{
            background: warns
              ? 'var(--mantine-color-yellow-light)'
              : `color-mix(in srgb, ${accent} 10%, transparent)`,
            borderLeft: `3px solid ${tone}`,
            borderRadius: 'var(--mantine-radius-sm)',
          }}
        >
          <Stack gap={4}>
            <SectionLabel
              color={warns ? 'var(--mantine-color-yellow-light-color)' : accent}
              icon={section.icon}
            >
              {section.label}
            </SectionLabel>
            {view({ size: 'sm' })}
          </Stack>
        </Box>
      );
    }
    case 'source': {
      // A footer: each citation on a line, its URLs and DOIs as links.
      const entries = splitSources(section.text);
      return (
        <Stack gap={4}>
          {!first && <Divider />}
          <SectionLabel color={accent} icon={section.icon}>
            {section.label}
          </SectionLabel>
          {entries.map((entry, i) => (
            <Text key={i} size="xs" c="dimmed">
              {inline(linkifySource(entry))}
            </Text>
          ))}
        </Stack>
      );
    }
    default:
      return <Stack gap={6}>{view({ size: 'sm', c: 'dimmed' })}</Stack>;
  }
};

/**
 * The description as real markdown, in sections (see `parseSections`): a lead,
 * dimmed body paragraphs, labelled blocks under a small heading, `Note:` style
 * callouts and a `Source:` footer. A description that is one run-on line (a
 * folded YAML scalar) is first broken into short paragraphs at its sentence
 * boundaries; one with structure of its own is left as written. Links and the
 * accent take the tile's tab hue.
 */
export const DescriptionBody: React.FC<{ text: string; accent?: string }> = ({
  text,
  accent = FALLBACK_ACCENT,
}) => {
  const resolveTab = useTabLinkResolver();
  const sections = React.useMemo(() => parseSections(text), [text]);
  const inline = React.useCallback<Inline>(
    (t, values) => inlineNodes(t, resolveTab, accent, values),
    [resolveTab, accent],
  );
  return (
    <Stack gap="sm" data-testid="component-info-body">
      {sections.map((section, i) => (
        <SectionView key={i} section={section} first={i === 0} inline={inline} accent={accent} />
      ))}
    </Stack>
  );
};

export interface ComponentInfoProps {
  /** The author's description (markdown). Nothing renders when empty. */
  description: string;
  /** The component's title, heading the popover; a generic label when unset. */
  title?: string;
  /** `title`: the small info icon beside the tile's title. `toolbar`: the
   *  action in the tile's hover row, for tiles with no title row of their own. */
  trigger: 'title' | 'toolbar';
  /** Show the title-row icon even when the subtitle already says it all (a
   *  one-line header that has no room for the subtitle). */
  always?: boolean;
}

const TOOLBAR = TILE_ACTION_STYLE.description;

const ComponentInfo: React.FC<ComponentInfoProps> = ({ description, title, trigger, always }) => {
  const portalTarget = useFullscreenPortalTarget();
  // Context crosses the portal, so the popover reads the tile's tab hue too.
  const accent = useTabHue() ?? FALLBACK_ACCENT;
  const text = description.trim();
  if (!text) return null;
  // Beside the title the icon is only worth its pixels when there is more to
  // read than the subtitle shows.
  if (trigger === 'title' && !always && !hasMoreThanSubtitle(text)) return null;

  const heading = title?.trim() || TOOLBAR.label;
  const label = title?.trim() ? `About ${title.trim()}` : TOOLBAR.label;
  const button =
    trigger === 'toolbar' ? (
      <ActionIcon variant="subtle" color={TOOLBAR.color} size="sm" aria-label={label}>
        <Icon icon={TOOLBAR.icon} width={16} height={16} />
      </ActionIcon>
    ) : (
      <ActionIcon
        variant="subtle"
        color="gray"
        size="xs"
        radius="xl"
        aria-label={label}
        data-testid="component-info-icon"
      >
        <Icon icon={TOOLBAR.icon} width={14} height={14} />
      </ActionIcon>
    );

  const popover = (
    <Popover
      position="bottom-start"
      withArrow
      shadow="md"
      width={440}
      // Escape closes (Mantine's default) and gives the focus back to the icon;
      // the trap moves it into the text so the keyboard can scroll and follow
      // links. A click outside closes it too; nothing here opens on hover.
      trapFocus
      returnFocus
      portalProps={{ target: portalTarget }}
    >
      <Popover.Target>
        <Tooltip label={TOOLBAR.label} withArrow openDelay={300}>
          {button}
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="sm" style={{ maxWidth: 'calc(100vw - 24px)' }} aria-label={heading}>
        <Group
          gap={6}
          wrap="nowrap"
          mb={6}
          // The accent as a rule on the title row.
          style={{ borderLeft: `3px solid ${accent}`, paddingLeft: 8 }}
        >
          <Icon
            icon={TOOLBAR.icon}
            width={16}
            height={16}
            aria-hidden
            style={{ color: accent, flex: 'none' }}
          />
          <Text fw={600} size="sm" truncate>
            {heading}
          </Text>
        </Group>
        <Divider mb="xs" />
        {/* Native scrolling: it works under touch, and the region takes the
            focus (`data-autofocus`) so the arrow keys scroll it. */}
        <div
          tabIndex={0}
          data-autofocus
          role="region"
          aria-label={`${heading}, description`}
          style={{ maxHeight: 'min(70vh, 520px)', overflowY: 'auto', outlineOffset: 2 }}
        >
          <DescriptionBody text={text} accent={accent} />
        </div>
      </Popover.Dropdown>
    </Popover>
  );

  // The tile is a drag handle in the editor and a click target elsewhere: the
  // wrapper keeps a press on the icon from starting either.
  return (
    <span
      className="dgl-no-drag"
      style={{ display: 'inline-flex', alignItems: 'center', flex: 'none' }}
      onMouseDown={(e) => e.stopPropagation()}
      onTouchStart={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {popover}
    </span>
  );
};

export default ComponentInfo;

/** The one-line subtitle under a title: the description's first sentence. */
export const TileSubtitle: React.FC<{ description: string }> = ({ description }) => {
  const line = firstSentence(description);
  if (!line) return null;
  return (
    <Text size="xs" c="dimmed" truncate data-testid="tile-subtitle">
      {line}
    </Text>
  );
};

/**
 * The title row of a tile that carries a description: the title, the info icon,
 * then the tile's own chips. Wrapped with `TileSubtitle` under it by the
 * renderers (see `titleCarriesDescription`).
 */
export const TileTitleRow: React.FC<{
  title: string;
  description: string;
  badges?: React.ReactNode;
}> = ({ title, description, badges }) => (
  <Group gap="xs" wrap="nowrap" className="dc-tile-title-row" style={{ minWidth: 0 }}>
    <Text fw={600} size="sm" truncate style={{ minWidth: 0, flex: '0 1 auto' }}>
      {title}
    </Text>
    <ComponentInfo description={description} title={title} trigger="title" />
    {badges}
  </Group>
);
