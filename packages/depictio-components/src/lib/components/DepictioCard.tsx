import React from 'react';
import { Card, Stack, Text, Group, Box, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import IconBadge from './IconBadge';
import './DepictioCard.css';

/**
 * Depictio Card — visually mirrors the DMC card produced by
 * ``depictio.dash.modules.card_component.utils.build_card`` /
 * ``_build_card_component`` / ``_create_card_content``:
 *
 *   - Outer ``Card`` (withBorder, shadow="sm", radius "sm" or "8px" if custom bg)
 *     - height 100%, minHeight 120px, box-sizing content-box
 *   - Inner ``Card.Section`` with content padding, flex column, justify center
 *     - Icon: right-hand watermark (opacity 0.3, always visible), beside the
 *       title only on the compact analysis-mode header
 *     - Title text (bold, marginLeft -2px)
 *     - Hero value (bold, marginLeft -2px)
 *     - Optional aggregation description / comparison row
 *     - Optional secondary metrics stack
 *
 * Props mirror the keys persisted in Depictio's Dashboard.stored_metadata.
 */
export interface SecondaryMetric {
  label: string;
  value: string | number;
  aggregation?: string;
}

export interface CardComparison {
  base_value?: number | string | null;
  is_same?: boolean;
}

export interface DepictioCardProps {
  id?: string | Record<string, string>;
  title?: string;
  value?: string | number | null;
  icon_name?: string;
  icon_color?: string;
  /** `watermark` (default): a large faint mark revealed on hover. `badge`: a
   *  small icon on a tint of its colour, always shown beside the title. */
  icon_style?: 'watermark' | 'badge';
  /** `headline`: a key figure for a landing page — a large value, and the
   *  icon resting faint on the right instead of appearing on hover.
   *  `compact`: a low card for a strip of many small numbers — title and value
   *  share one line when the card is wide enough, the icon sits small beside
   *  the title. `minimal`: headline type with no frame, shadow or background,
   *  for figures sitting on a tinted section or among prose. `accent`: a
   *  headline card with a rail of its colour down the left edge and a faint
   *  wash of it behind the value, the full strip kept — a few cards singled
   *  out on an analysis tab. `split`: a stat tile, the icon in a tinted block
   *  on the left and title, value and caption beside it. */
  variant?: 'default' | 'headline' | 'compact' | 'minimal' | 'accent' | 'split';
  title_color?: string;
  background_color?: string;
  /** Mantine size token: xs / sm / md / lg / xl. Mirrors `dmc.Text size=...`. */
  title_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  value_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  aggregation_description?: string;
  secondary_metrics?: SecondaryMetric[];
  /** Optional ReactNode rendered INSIDE the bordered Card frame, below the
   *  Card.Section. Used by callers to inject a richer secondary strip (e.g.
   *  the SecondaryMetrics box-plot / compact row from depictio-react-core)
   *  while keeping everything inside the card's visible border. */
  secondaryStrip?: React.ReactNode;
  comparison?: CardComparison;
  filter_applied?: boolean;
  /** Render the title and hero value on ONE line (value beside the title,
   *  slightly smaller) — used when a rich secondaryStrip needs the height the
   *  stacked hero row normally takes. */
  inline_header?: boolean;
  /** Tooltip shown when hovering the title/value header — carries the
   *  aggregation description when the visible line is dropped. */
  header_tooltip?: React.ReactNode;
  /** Attached to the single height-auto element the card's content lives in.
   *
   *  The card frame itself is `height: 100%`, so it reports the tile it was
   *  given and never the room its content needs. A caller that wants to size
   *  the tile to the card (the dashboard grid does) has nothing to measure
   *  without this. Exposed as a ref rather than found by class name because
   *  Mantine's class names are generated and are not ours to depend on. */
  contentRef?: React.Ref<HTMLDivElement>;
  setProps?: (props: Partial<DepictioCardProps>) => void;
}

/** Shortest the card ever draws itself, whatever it holds. Carried by the
 *  content wrapper as well as the frame, so what a caller measures off the
 *  wrapper is the room the card will really take and not just the room its
 *  content needs. */
const CARD_MIN_CONTENT_HEIGHT = 120;

/** A compact card's floor: one line of title and value, one of caption. Low
 *  enough that a row of them reads as a strip of numbers rather than as cards,
 *  and still the same for every card of the row so they line up. */
const COMPACT_MIN_CONTENT_HEIGHT = 56;

/** The tallest secondary strip (a box plot over its three numbers). */
const HEADLINE_STRIP_MIN_PX = 60;

const DepictioCard: React.FC<DepictioCardProps> = ({
  title = '',
  value = null,
  icon_name,
  icon_color,
  icon_style = 'watermark',
  variant = 'default',
  title_color,
  background_color,
  title_font_size = 'md',
  value_font_size = 'xl',
  aggregation_description,
  secondary_metrics,
  secondaryStrip,
  comparison,
  filter_applied = false,
  inline_header = false,
  header_tooltip,
  contentRef,
}) => {
  const hasCustomBg = !!background_color;
  // The one-line header a group comparison asks for overrides every style: it
  // is what buys the strip its height.
  const minimal = variant === 'minimal' && !inline_header;
  const compact = variant === 'compact' && !inline_header;
  const accent = variant === 'accent' && !inline_header;
  const split = variant === 'split' && !inline_header;
  // Minimal and accent cards are headline cards with a different frame (none,
  // or a coloured rail): same type, same resting icon, same held heights, so
  // they line up beside a headline card.
  const headline = (variant === 'headline' || minimal || accent) && !inline_header;
  // The heights a row of cards is aligned on (two caption lines, the tallest
  // strip), held by every style drawn as a large figure.
  const heldHeights = headline || split;
  // The colour that marks an accent rail or a split tile's icon block: the
  // card's own, else the brand's primary.
  const markColor = icon_color || title_color || 'var(--mantine-primary-color-filled)';
  const iconColor = icon_color || title_color || 'currentColor';
  const badge = icon_name && icon_style === 'badge' && !headline && !compact && !split;
  const minContentHeight = compact ? COMPACT_MIN_CONTENT_HEIGHT : CARD_MIN_CONTENT_HEIGHT;
  // Where the icon goes. Every card keeps the right-hand watermark, always
  // visible, except the compact analysis-mode header (groups compared), which
  // has no corner left: there the icon sits beside the title, small and
  // full-opacity. A badge, a compact row and a split tile's block draw the
  // icon themselves.
  const iconBesideTitle = !!icon_name && inline_header;
  const titleIcon = iconBesideTitle ? (
    <Icon
      icon={icon_name as string}
      width={16}
      height={16}
      style={{
        color: iconColor,
        flexShrink: 0,
        // Optically centred on the title's first line.
        marginTop: 2,
      }}
    />
  ) : null;
  const iconNode =
    icon_name && !iconBesideTitle && !badge && !compact && !split ? (
      <Box className={headline ? 'depictio-card-icon depictio-card-icon--rest' : 'depictio-card-icon'}>
        <Icon icon={icon_name} style={{ color: iconColor }} />
      </Box>
    ) : null;

  const header = inline_header ? (
    // Title left, value right: glued side by side the two bold texts read as
    // one string — pushing the value to the opposite edge keeps both
    // identifiable on a single line.
    <Group
      gap={8}
      // Top, not baseline: the title may wrap to a second line and the value
      // has to stay level with the first one.
      align="flex-start"
      wrap="nowrap"
      justify="space-between"
      style={{ marginLeft: -2, minWidth: 0 }}
    >
      <Group gap={6} wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
        {titleIcon}
        <Text
          size={title_font_size}
          fw={700}
          c={title_color || undefined}
          // Two lines rather than one truncated one. The value keeps its
          // natural width, so on a narrow card a single clipped line left
          // titles as "Shann…" — unreadable, and the tooltip that carries the
          // full text only helps a reader who already suspects what it says.
          lineClamp={2}
          style={{ margin: 0, minWidth: 0, lineHeight: 1.25, overflowWrap: 'break-word' }}
        >
          {title}
        </Text>
      </Group>
      {/* The value is the number the card exists for: hero-sized even on the
          compact one-line header, only the title yields. */}
      <Text
        fw={700}
        c={title_color || undefined}
        style={{
          margin: 0,
          flexShrink: 0,
          // Scales with the card, not fixed at 28px: on a two-column card a
          // hero-sized number took most of the row and left the title breaking
          // mid-word ("Tempera / ture at…"). The container query unit is the
          // card's own width — see the `container-type: inline-size` wrapper in
          // DepictioCard.css.
          fontSize: 'clamp(18px, 11cqw, 28px)',
          lineHeight: 1,
        }}
      >
        {value !== null && value !== undefined ? value : '—'}
      </Text>
    </Group>
  ) : compact ? (
    // Title and value side by side when the card is wide enough, stacked
    // tight when it is not (DepictioCard.css flips the row on the card's own
    // width): a strip of small cards is often eight to a row, too narrow for
    // both on one line.
    <div className="depictio-card-compact-row">
      <Group gap={6} wrap="nowrap" align="center" style={{ minWidth: 0 }}>
        {/* No corner to hide a watermark in on a card this low: the icon
            moves beside the title, small and in its own colour. */}
        {icon_name && (
          <Icon
            icon={icon_name}
            width={16}
            height={16}
            style={{ color: icon_color || title_color || 'currentColor', flexShrink: 0 }}
          />
        )}
        <Text
          size={title_font_size === 'md' ? 'xs' : title_font_size}
          fw={600}
          c={title_color || undefined}
          lineClamp={2}
          style={{ margin: 0, minWidth: 0, lineHeight: 1.25, overflowWrap: 'break-word' }}
        >
          {title}
        </Text>
      </Group>
      <Text
        fw={800}
        c={title_color || undefined}
        style={{
          margin: 0,
          flexShrink: 0,
          // Scales with the card like the headline value, on a lower ceiling:
          // the number still leads, but the card stays a line high.
          fontSize: 'clamp(18px, 12cqw, 24px)',
          lineHeight: 1.1,
          letterSpacing: '-0.01em',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value !== null && value !== undefined ? value : '—'}
      </Text>
    </div>
  ) : split ? (
    // A stat tile: the icon in a block of its colour on the left reads first,
    // then title and value as one column beside it. On a card too narrow for
    // both the block goes (DepictioCard.css) and the column takes the width.
    <Group gap={12} wrap="nowrap" align="center" style={{ minWidth: 0 }}>
      {icon_name && (
        <Box className="depictio-card-split-icon" style={{ color: markColor }}>
          <Icon icon={icon_name} width={28} height={28} />
        </Box>
      )}
      <Stack gap={2} style={{ minWidth: 0 }}>
        <Text
          size={title_font_size === 'md' ? 'sm' : title_font_size}
          fw={600}
          c={title_color || 'dimmed'}
          lineClamp={2}
          style={{ margin: 0, lineHeight: 1.3, overflowWrap: 'break-word' }}
        >
          {title}
        </Text>
        <Text
          fw={800}
          c={title_color || undefined}
          style={{
            margin: 0,
            // Between the compact and the headline value: the tile's block
            // takes some of the width a headline figure would have.
            fontSize: 'clamp(22px, 13cqw, 34px)',
            lineHeight: 1.05,
            letterSpacing: '-0.02em',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {value !== null && value !== undefined ? value : '—'}
        </Text>
      </Stack>
    </Group>
  ) : headline ? (
    <>
      <Text
        size={title_font_size === 'md' ? 'sm' : title_font_size}
        fw={600}
        c={title_color || undefined}
        style={{ margin: 0, lineHeight: 1.3 }}
      >
        {title}
      </Text>
      <Text
        fw={800}
        c={title_color || undefined}
        style={{
          margin: 0,
          // The number is what the card is for. Scales with the card (see the
          // container on .depictio-card) so a narrow card still fits it.
          fontSize: 'clamp(26px, 15cqw, 40px)',
          lineHeight: 1.05,
          letterSpacing: '-0.02em',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value !== null && value !== undefined ? value : '—'}
      </Text>
    </>
  ) : (
    <>
      {badge ? (
        // The badge leads the title: a row of headline cards reads by colour
        // and glyph before a word of it is read.
        <Group gap={10} wrap="nowrap" align="center" style={{ marginLeft: -2, minWidth: 0 }}>
          <IconBadge icon={icon_name as string} color={icon_color || title_color || undefined} />
          <Text
            size={title_font_size}
            fw={700}
            c={title_color || undefined}
            style={{ margin: 0, minWidth: 0, lineHeight: 1.25 }}
          >
            {title}
          </Text>
        </Group>
      ) : (
        <Text
          size={title_font_size}
          fw={700}
          c={title_color || undefined}
          style={{ margin: 0, marginLeft: -2 }}
        >
          {title}
        </Text>
      )}

      <Text
        size={value_font_size}
        fw={700}
        c={title_color || undefined}
        style={{ margin: 0, marginLeft: -2 }}
      >
        {value !== null && value !== undefined ? value : '—'}
      </Text>
    </>
  );

  return (
    <Card
      withBorder
      // No shadow on a minimal card: with the frame gone it would be the one
      // edge left, floating under nothing.
      shadow={minimal ? undefined : 'sm'}
      radius={hasCustomBg ? 8 : 'sm'}
      padding={0}
      className={
        'depictio-card' +
        (minimal ? ' depictio-card--minimal' : '') +
        (compact ? ' depictio-card--compact' : '') +
        (accent ? ' depictio-card--accent' : '') +
        (split ? ' depictio-card--split' : '')
      }
      style={{
        // Read by the accent rail and wash in DepictioCard.css.
        ...(accent ? { ['--depictio-card-accent' as string]: markColor } : {}),
        boxSizing: 'content-box',
        height: '100%',
        minHeight: minContentHeight,
        position: 'relative',
        // Flex column with ``justifyContent: center`` so the content cluster
        // (Card.Section) and the optional ``secondaryStrip`` are vertically
        // centred as a unit, with no dead space between them. The old
        // ``height: 100%`` on Card.Section left no room for the strip,
        // which then rendered below the card's clipped overflow and
        // disappeared.
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        // Border is set in DepictioCard.css with !important to win over
        // Mantine's ``withBorder`` shorthand. See the .depictio-card rule.
        //
        // Mantine's Card defaults to `dark.6` (#25262b) in dark mode, one
        // shade lighter than `--mantine-color-body` (#1A1B1E) which is what
        // Paper-based renderers (figures, tables, interactives) use. Force
        // body so cards visually match the rest of the dashboard. Custom
        // YAML-supplied colors still win.
        // A minimal card shows what it sits on — a tinted section, a page —
        // unless the author gave it a colour of its own.
        backgroundColor:
          background_color || (minimal ? 'transparent' : 'var(--mantine-color-body)'),
      }}
    >
      {/* Icon overlay — top-right (narrow) or vertically-centred right
          watermark (wide) via container queries in DepictioCard.css.
          Inline ``width``/``height`` removed so the CSS controls sizing —
          @iconify/react renders an <svg> we can size via .depictio-card-icon
          svg{...} rules. */}
      {!headline && iconNode}

      {/* The card's content, in one height-auto box.
          Two jobs. It is what a caller measures: the frame above is
          ``height: 100%`` and can only report the tile it was handed, while
          this box is as tall as what it holds and no taller, which is the
          number a grid needs to size the tile to the card. And because it is
          height-auto it cannot be told a height by the tile, so measuring it
          can never feed a resize back into itself.
          A flex column, matching the formatting context the section and the
          strip had as direct children of the frame; ``justifyContent: center``
          and ``minHeight`` keep a short card's content centred in the 120px
          the frame gives it, exactly where the frame's own centring put it. */}
      <div
        ref={contentRef}
        style={{
          // ``flex: 0 0 auto`` is what makes this box measurable, not just a
          // style preference. A flex item shrinks to its container by default,
          // so content taller than the card would be squeezed back to the
          // card's height and would report the tile again, and report it short
          // at that, since a centred overflow spills past the top edge where
          // ``scrollHeight`` cannot see it.
          flex: '0 0 auto',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          minHeight: minContentHeight,
          width: '100%',
          minWidth: 0,
          // A headline card's icon rests inside the content, level with the
          // title wherever the centred content lands in the tile.
          position: headline ? 'relative' : undefined,
        }}
      >
      {headline && iconNode}
      {/* Content section — flex column, vertically centered, padding xs.
          Matches dmc.CardSection(p='xs', justifyContent='center'). When a
          ``secondaryStrip`` is present, drop the bottom padding so the strip
          (e.g. box-plot) sits closer to the value, not separated by a wide
          gap. */}
      <Card.Section
        p={hasCustomBg || (headline && !minimal) || split ? '1rem' : 'xs'}
        // A minimal card has no frame to keep its text off: a sliver of side
        // padding lines its title up with the section heading above it.
        px={minimal && !hasCustomBg ? 4 : compact ? 'sm' : undefined}
        pb={secondaryStrip ? 0 : undefined}
        // Clear of the resting icon, so a long value never runs under it — and
        // not on a card too narrow to keep the icon (see DepictioCard.css).
        className={headline && icon_name ? 'depictio-card-clear-icon' : undefined}
        style={{
          // ``flex: 0 0 auto`` so Card.Section sizes to its content rather
          // than stretching to fill the card. The outer Card's
          // ``justifyContent: center`` then vertically centres Card.Section
          // + secondaryStrip as a unit, with the strip sitting flush against
          // the value text (no dead whitespace between them).
          flex: '0 0 auto',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}
      >
        <Stack gap={compact ? 2 : 4}>
          {header_tooltip ? (
            <Tooltip label={header_tooltip} withArrow openDelay={300} multiline w={240}>
              <Box style={{ cursor: 'help', minWidth: 0 }}>{header}</Box>
            </Tooltip>
          ) : (
            header
          )}

          {aggregation_description && (
            <Text
              size="xs"
              c="dimmed"
              // One line on a compact card, so a row of them keeps one height.
              lineClamp={compact ? 1 : undefined}
              // Under the value on a split tile, not under its icon block.
              className={split && icon_name ? 'depictio-card-split-indent' : undefined}
              style={{
                marginLeft: -2,
                // Two lines held on a headline card, whether its caption wraps
                // or not: a row of cards centres its contents, and a caption a
                // line shorter than its neighbours' moved the whole card off
                // their line.
                ...(heldHeights
                  ? { minHeight: 'calc(2 * var(--mantine-line-height-xs) * var(--mantine-font-size-xs))' }
                  : {}),
              }}
            >
              {aggregation_description}
            </Text>
          )}

          {filter_applied && comparison && comparison.base_value != null && (
            <Group gap="xs" align="center" justify="flex-start" style={{ marginLeft: -2 }}>
              <Text size="xs" c="dimmed">
                {comparison.is_same
                  ? `Same as unfiltered (${comparison.base_value})`
                  : `Unfiltered: ${comparison.base_value}`}
              </Text>
            </Group>
          )}

          {secondary_metrics && secondary_metrics.length > 0 && (
            <Stack gap={4} mt="xs">
              {secondary_metrics.map((m, idx) => (
                <Group key={idx} justify="space-between" wrap="nowrap">
                  <Text size="sm" c="dimmed">
                    {m.label}:
                  </Text>
                  <Text size="sm" fw={500}>
                    {m.value}
                  </Text>
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      </Card.Section>
      {/* Optional rich secondary strip — sits INSIDE the bordered Card so
          it doesn't escape the frame. Caller is responsible for padding /
          spacing; we just provide the visual containment. */}
      {secondaryStrip ? (
        <Box
          style={{
            width: '100%',
            // Horizontal-only overflow clipping: keep outlier dots / wide
            // labels inside the card width, BUT allow vertical overflow so
            // SecondaryMetrics' negative top margin (which pulls the strip
            // up to sit tight under the value text) doesn't get clipped.
            // ``hidden visible`` resolves to ``overflow-x: hidden; overflow-y: visible``.
            overflow: 'hidden visible',
            // A headline card's strip holds the height of the tallest one (a
            // box plot): the cards of a row centre their contents, and equal
            // contents put every title and value on one line across the row.
            ...(heldHeights ? { minHeight: HEADLINE_STRIP_MIN_PX } : {}),
            // With the compact header the strip is the card's main content:
            // let it take the freed height and distribute it (the strip's own
            // containers justify space-evenly) instead of pooling dead space
            // under a top-packed list.
            // ``justifyContent: center`` centres strips that don't stretch
            // themselves (the default SecondaryMetrics); the group-compare
            // strip declares its own ``flex: 1`` and distributes instead.
            ...(inline_header
              ? {
                  flex: '1 1 auto',
                  minHeight: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                }
              : {}),
          }}
        >
          {secondaryStrip}
        </Box>
      ) : null}
      </div>
    </Card>
  );
};

export default DepictioCard;
