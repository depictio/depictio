import React from 'react';
import { Text, UnstyledButton } from '@mantine/core';

import Glyph, { glyphColorVar } from './Glyph';
import { TabLinkResolver, TabTileItem } from './tabLinks';
import { CARD_FRAME } from './cardFrame';
import './tabTiles.css';

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
}> = ({ items, ordered, resolveTab }) => {
  const present = items.flatMap((item) => {
    const target = resolveTab(item.tab);
    return target ? [{ item, target }] : [];
  });
  if (!present.length) return null;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(min(260px, 100%), 1fr))',
        gap: 10,
        width: '100%',
      }}
    >
      {present.map(({ item, target }, i) => {
        const color = glyphColorVar(target.color ?? 'gray');
        const line = item.text ?? target.description ?? null;
        const inner = (
          <>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, flex: 1 }}>
              {ordered ? (
                <Text
                  size="xs"
                  fw={700}
                  c="dimmed"
                  style={{ letterSpacing: '0.06em', fontVariantNumeric: 'tabular-nums' }}
                  aria-label={`Step ${i + 1}`}
                >
                  {String(i + 1).padStart(2, '0')}
                </Text>
              ) : null}
              <Text fw={700} size="sm" lh={1.3}>
                {item.label}
              </Text>
              {line ? (
                <Text size="xs" c="dimmed" lh={1.4}>
                  {line}
                </Text>
              ) : null}
            </span>
            {target.icon ? (
              // The tab's mark at rest, as on a headline metric card.
              <span className="depictio-tab-tile-icon" aria-hidden>
                <Glyph icon={target.icon} color={target.color} size={32} />
              </span>
            ) : null}
          </>
        );
        const style: React.CSSProperties = {
          ...CARD_FRAME,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '14px 16px',
          textAlign: 'left',
          minHeight: 72,
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
