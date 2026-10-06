/**
 * The section form's layout choice: cards with a thumbnail of what each
 * layout looks like, rather than two words in a segmented control. "Tiles" and
 * "Filter bar" read the same until you see one of each.
 *
 * The thumbnails are drawn with plain boxes in the theme's own greys, so they
 * follow light and dark mode and need no image.
 */
import React from 'react';
import { Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

const INK = 'light-dark(var(--mantine-color-gray-4), var(--mantine-color-dark-3))';
const FAINT = 'light-dark(var(--mantine-color-gray-2), var(--mantine-color-dark-5))';
const ACCENT = 'var(--mantine-color-grape-5)';

const bar = (width: number | string, height = 4, color = INK): React.CSSProperties => ({
  width,
  height,
  borderRadius: 2,
  background: color,
  flexShrink: 0,
});

/** A section heading over a 3×2 grid of tiles. */
export const TilesPreview: React.FC = () => (
  <Stack gap={5} w="100%">
    <div style={bar(46, 5)} />
    {[0, 1].map((row) => (
      <Group key={row} gap={4} wrap="nowrap">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{ flex: 1, height: 18, borderRadius: 3, border: `1px solid ${INK}` }}
          />
        ))}
      </Group>
    ))}
  </Stack>
);

/** One filter: badge, label, a chip track. */
const FilterGlyph: React.FC<{ chips?: number; slider?: boolean }> = ({ chips = 3, slider }) => (
  <Group gap={3} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
    <div style={{ ...bar(7, 7, ACCENT), borderRadius: 2 }} />
    <div style={bar(14, 3)} />
    {slider ? (
      <div style={{ ...bar('100%', 2), flex: 1, position: 'relative' }} />
    ) : (
      <Group gap={2} wrap="nowrap" style={{ flex: 1, padding: 2, borderRadius: 3, background: FAINT }}>
        {Array.from({ length: chips }, (_, i) => (
          <div key={i} style={{ ...bar('100%', 4, INK), flex: 1 }} />
        ))}
      </Group>
    )}
  </Group>
);

/** One compact row of filters with rules between them. */
export const BarPreview: React.FC = () => (
  <Stack gap={5} w="100%" justify="center" style={{ minHeight: 49 }}>
    <Group
      gap={6}
      wrap="nowrap"
      style={{ padding: '6px 6px', borderRadius: 4, border: `1px solid ${INK}` }}
    >
      <FilterGlyph />
      <div style={{ width: 1, alignSelf: 'stretch', background: INK }} />
      <FilterGlyph slider />
    </Group>
  </Stack>
);

/** A section heading, its own row of filters, then its tiles. */
export const SectionBarPreview: React.FC = () => (
  <Stack gap={5} w="100%">
    <div style={bar(46, 5)} />
    <Group
      gap={6}
      wrap="nowrap"
      style={{ padding: '3px 5px', borderRadius: 3, border: `1px dashed ${ACCENT}` }}
    >
      <FilterGlyph chips={2} />
      <div style={{ width: 1, alignSelf: 'stretch', background: INK }} />
      <FilterGlyph chips={3} />
    </Group>
    <Group gap={4} wrap="nowrap">
      {[0, 1, 2].map((i) => (
        <div key={i} style={{ flex: 1, height: 16, borderRadius: 3, border: `1px solid ${INK}` }} />
      ))}
    </Group>
  </Stack>
);

export interface LayoutOption<T extends string> {
  value: T;
  title: string;
  description: string;
  icon: string;
  preview: React.ReactNode;
}

/** Radio cards: thumbnail, title, one line on what it does. */
export function LayoutChoice<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: LayoutOption<T>[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      style={{ display: 'grid', gridTemplateColumns: `repeat(${options.length}, 1fr)`, gap: 10 }}
    >
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <UnstyledButton
            key={o.value}
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(o.value)}
            data-testid={`section-layout-${o.value}`}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              padding: 10,
              borderRadius: 'var(--mantine-radius-md)',
              border: selected
                ? `2px solid var(--mantine-color-grape-6)`
                : '2px solid var(--mantine-color-default-border)',
              background: selected
                ? 'light-dark(var(--mantine-color-grape-0), rgba(190, 75, 219, 0.08))'
                : 'var(--mantine-color-body)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: 8,
                borderRadius: 'var(--mantine-radius-sm)',
                background: 'light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))',
              }}
              aria-hidden
            >
              {o.preview}
            </div>
            <Group gap={6} wrap="nowrap">
              <Icon
                icon={selected ? 'mdi:radiobox-marked' : 'mdi:radiobox-blank'}
                width={16}
                color={selected ? 'var(--mantine-color-grape-6)' : 'var(--mantine-color-dimmed)'}
              />
              <Icon icon={o.icon} width={15} />
              <Text size="sm" fw={600}>
                {o.title}
              </Text>
            </Group>
            <Text size="xs" c="dimmed" lh={1.35}>
              {o.description}
            </Text>
          </UnstyledButton>
        );
      })}
    </div>
  );
}
