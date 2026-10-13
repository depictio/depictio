import React from 'react';
import { Text, UnstyledButton } from '@mantine/core';
import { useElementSize } from '@mantine/hooks';

import Glyph, { glyphColorVar } from './Glyph';
import { balancedColumns, TabLinkResolver, TabTileItem } from './tabLinks';
import { CARD_FRAME } from './cardFrame';
import './tabTiles.css';

/** The narrowest a tile gets before the row wraps, and the gap between tiles. */
const TILE_MIN_PX = 240;
const TILE_GAP_PX = 12;

/**
 * A list of tab links drawn as a grid of tiles: the tab's name, what it
 * answers, and its icon resting faint on the right, framed like a metric card
 * so a landing page of key figures, findings and tiles reads as one system.
 * The landing-page table of contents.
 *
 * A tile's line is the text the author wrote after the link, else the tab's
 * own subtitle, so a template can list its tabs by name alone and stay in step
 * with them. An ordered list numbers the tiles (01, 02…): a suggested reading order.
 *
 * A tab the family does not have is left out, numbering included. Import drops
 * a tab whose data a run lacks, so a template's landing page names tabs that a
 * given instance may not carry; a dimmed dead tile there reads as broken.
 */
const TabTiles: React.FC<{
  items: TabTileItem[];
  ordered: boolean;
  resolveTab: TabLinkResolver;
  /** Draws the author's line, filling its live values (see textValues.ts). */
  fill?: (text: string) => React.ReactNode;
}> = ({ items, ordered, resolveTab, fill }) => {
  const present = items.flatMap((item) => {
    const target = resolveTab(item.tab);
    return target ? [{ item, target }] : [];
  });
  const { ref, width } = useElementSize();
  if (!present.length) return null;
  // Before the first measurement, one column per tile up to four: the common
  // case, and what the measured layout usually confirms.
  const columns = width
    ? balancedColumns(present.length, width, TILE_MIN_PX, TILE_GAP_PX)
    : Math.min(present.length, 4);
  return (
    <div
      ref={ref}
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gap: TILE_GAP_PX,
        width: '100%',
      }}
    >
      {present.map(({ item, target }, i) => {
        const color = glyphColorVar(target.color ?? 'gray');
        const line =
          item.text === null ? target.description ?? null : fill ? fill(item.text) : item.text;
        const icon = target.icon ? (
          // The tab's mark at rest, as on a headline metric card.
          <span className="depictio-tab-tile-icon" aria-hidden>
            <Glyph icon={target.icon} color={target.color} size={ordered ? 30 : 36} />
          </span>
        ) : null;
        const words = (
          <span style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
            <Text fw={700} size="md" lh={1.3}>
              {item.label}
            </Text>
            {line ? (
              <Text size="sm" c="dimmed" lh={1.4}>
                {line}
              </Text>
            ) : null}
          </span>
        );
        // A numbered tile is a step: its number leads, large and in the tab's
        // colour, so the row reads as a path before a word of it is read. The
        // tab's mark sits opposite it, the name and question underneath.
        const inner = ordered ? (
          <span style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0, flex: 1 }}>
            <span style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <span
                aria-label={`Step ${i + 1}`}
                style={{
                  color,
                  fontSize: 30,
                  fontWeight: 800,
                  lineHeight: 1,
                  letterSpacing: '-0.02em',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              {icon}
            </span>
            {words}
          </span>
        ) : (
          <>
            <span style={{ flex: 1, minWidth: 0 }}>{words}</span>
            {icon}
          </>
        );
        const style: React.CSSProperties = {
          ...CARD_FRAME,
          display: 'flex',
          alignItems: ordered ? 'stretch' : 'center',
          gap: 14,
          padding: ordered ? '18px 20px 20px' : '20px 22px',
          textAlign: 'left',
          minHeight: ordered ? 0 : 96,
          ['--tile-tint' as string]: `color-mix(in srgb, ${color} 6%, var(--mantine-color-body))`,
          ['--tile-edge' as string]: color,
        };
        return (
          <UnstyledButton
            key={i}
            component="a"
            href={target.href}
            className="depictio-tab-tile"
            style={style}
          >
            {inner}
          </UnstyledButton>
        );
      })}
    </div>
  );
};

export default TabTiles;
