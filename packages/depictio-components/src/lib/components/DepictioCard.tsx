import React from 'react';
import { Card, Stack, Text, Group, Box, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import './DepictioCard.css';

/**
 * Depictio Card — visually mirrors the DMC card produced by
 * ``depictio.dash.modules.card_component.utils.build_card`` /
 * ``_build_card_component`` / ``_create_card_content``:
 *
 *   - Outer ``Card`` (withBorder, shadow="sm", radius "sm" or "8px" if custom bg)
 *     - height 100%, minHeight 120px, box-sizing content-box
 *   - Inner ``Card.Section`` with content padding, flex column, justify center
 *     - Icon overlay (absolute top-right, opacity 0.3, 40px iconify)
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

const DepictioCard: React.FC<DepictioCardProps> = ({
  title = '',
  value = null,
  icon_name,
  icon_color,
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
        {/* The watermark icon has no corner left in the compact layout, so it
            moves beside the title — small, full-opacity, in its own color. */}
        {icon_name && (
          <Icon
            icon={icon_name}
            width={16}
            height={16}
            style={{
              color: icon_color || title_color || 'currentColor',
              flexShrink: 0,
              // Optically centred on the title's first line now that the row
              // is top-aligned.
              marginTop: 2,
            }}
          />
        )}
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
  ) : (
    <>
      <Text
        size={title_font_size}
        fw={700}
        c={title_color || undefined}
        style={{ margin: 0, marginLeft: -2 }}
      >
        {title}
      </Text>

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
      shadow="sm"
      radius={hasCustomBg ? 8 : 'sm'}
      padding={0}
      className="depictio-card"
      style={{
        boxSizing: 'content-box',
        height: '100%',
        minHeight: CARD_MIN_CONTENT_HEIGHT,
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
        backgroundColor: background_color || 'var(--mantine-color-body)',
      }}
    >
      {/* Icon overlay — top-right (narrow) or vertically-centred right
          watermark (wide) via container queries in DepictioCard.css.
          Inline ``width``/``height`` removed so the CSS controls sizing —
          @iconify/react renders an <svg> we can size via .depictio-card-icon
          svg{...} rules. */}
      {icon_name && !inline_header && (
        <Box className="depictio-card-icon">
          <Icon
            icon={icon_name}
            style={{ color: icon_color || title_color || 'currentColor' }}
          />
        </Box>
      )}

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
          minHeight: CARD_MIN_CONTENT_HEIGHT,
          width: '100%',
          minWidth: 0,
        }}
      >
      {/* Content section — flex column, vertically centered, padding xs.
          Matches dmc.CardSection(p='xs', justifyContent='center'). When a
          ``secondaryStrip`` is present, drop the bottom padding so the strip
          (e.g. box-plot) sits closer to the value, not separated by a wide
          gap. */}
      <Card.Section
        p={hasCustomBg ? '1rem' : 'xs'}
        pb={secondaryStrip ? 0 : undefined}
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
        <Stack gap={4}>
          {header_tooltip ? (
            <Tooltip label={header_tooltip} withArrow openDelay={300} multiline w={240}>
              <Box style={{ cursor: 'help', minWidth: 0 }}>{header}</Box>
            </Tooltip>
          ) : (
            header
          )}

          {aggregation_description && (
            <Text size="xs" c="dimmed" style={{ marginLeft: -2 }}>
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
