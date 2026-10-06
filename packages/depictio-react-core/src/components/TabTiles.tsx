import React from 'react';
import { Text, UnstyledButton } from '@mantine/core';

import Glyph, { glyphColorVar } from './Glyph';
import { TabLinkResolver, TabTileItem } from './tabLinks';
import './tabTiles.css';

/**
 * A list of tab links drawn as a grid of tiles: the tab's icon on a tint of its
 * colour, its name, and what it answers. The landing-page table of contents.
 *
 * A tile's line is the text the author wrote after the link, else the tab's
 * own subtitle, so a template can list its tabs by name alone and stay in step
 * with them. An ordered list numbers the tiles: a suggested reading order.
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
            <span
              style={{
                width: 38,
                height: 38,
                borderRadius: '50%',
                flex: 'none',
                display: 'grid',
                placeItems: 'center',
                background: `color-mix(in srgb, ${color} 12%, var(--mantine-color-body))`,
              }}
            >
              {target.icon ? <Glyph icon={target.icon} color={target.color} size={20} /> : null}
            </span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, flex: 1 }}>
              <Text fw={600} size="sm" lh={1.3}>
                {item.label}
              </Text>
              {line ? (
                <Text size="xs" c="dimmed" lh={1.35}>
                  {line}
                </Text>
              ) : null}
            </span>
            {ordered ? (
              <span
                aria-label={`Step ${i + 1}`}
                style={{
                  width: 24,
                  height: 24,
                  flex: 'none',
                  borderRadius: '50%',
                  border: '1px solid var(--mantine-color-default-border)',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 12,
                  fontWeight: 500,
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--mantine-color-dimmed)',
                }}
              >
                {i + 1}
              </span>
            ) : null}
          </>
        );
        const style: React.CSSProperties = {
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '12px 14px',
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-md)',
          background: 'var(--mantine-color-body)',
          textAlign: 'left',
          minHeight: 64,
          ['--tile-tint' as string]: `color-mix(in srgb, ${color} 7%, var(--mantine-color-body))`,
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
