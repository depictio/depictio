/**
 * The key to a genome view's overlays, in the header next to the link tag: a swatch drawn like
 * each overlay (a solid frame for the selected region, a dashed band for the
 * genome browser's window, in the link's colour) with what it is in words.
 * The tag of the browser itself sits in the header. The canvas cannot be read
 * by a screen reader; this line says the same thing as text, politely
 * announced when it changes.
 */
import { Group, Text } from '@mantine/core';

function Swatch({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <svg width={22} height={12} aria-hidden style={{ flex: 'none' }}>
      <rect x={2} y={1} width={18} height={10} fill={color} fillOpacity={dashed ? 0.12 : 0} />
      {[2, 20].map((x) => (
        <line
          key={x}
          x1={x}
          x2={x}
          y1={0}
          y2={12}
          stroke={color}
          strokeWidth={dashed ? 1.5 : 2}
          strokeDasharray={dashed ? '3 2' : undefined}
        />
      ))}
    </svg>
  );
}

export interface OverlayLegendProps {
  /** The selected region, formatted; null when none is in force. */
  selection: string | null;
  selectionColor: string;
  /** The genome browser's window, formatted; null when not drawn. */
  window: string | null;
  windowColor: string;
}

export default function OverlayLegend({
  selection,
  selectionColor,
  window: windowText,
  windowColor,
}: OverlayLegendProps) {
  if (!selection && !windowText) return null;
  return (
    <Group
      gap="md"
      wrap="wrap"
      role="status"
      aria-live="polite"
      data-testid="genome-view-overlay-legend"
      style={{ rowGap: 2 }}
    >
      {selection ? (
        <Group gap={6} wrap="nowrap">
          <Swatch color={selectionColor} />
          <Text size="xs">
            <Text span fw={600} size="xs">
              Filter
            </Text>{' '}
            {selection}
          </Text>
        </Group>
      ) : null}
      {windowText ? (
        <Group gap={6} wrap="nowrap">
          <Swatch color={windowColor} dashed />
          <Text size="xs">
            <Text span fw={600} size="xs">
              Browser view
            </Text>{' '}
            {windowText}
          </Text>
        </Group>
      ) : null}
    </Group>
  );
}
