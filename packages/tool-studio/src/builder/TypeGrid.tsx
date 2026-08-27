/**
 * Component-type picker — the depictio builder grid, filtered to the types
 * Tool Studio can author from a single fixture without a backend
 * (multiqc / image / map / text / jbrowse are dropped). Uses the shared
 * `COMPONENT_TYPES` registry so labels, icons and accent colours match depictio
 * exactly; the card markup mirrors depictio's StepType TypeCard.
 */
import { Card, Center, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { COMPONENT_TYPES } from 'depictio-builder/componentTypes';
import type { ComponentType } from 'depictio-builder/store/useBuilderStore';

const ALLOWED: ComponentType[] = ['figure', 'card', 'table', 'interactive', 'advanced_viz'];

export default function TypeGrid({ onPick }: { onPick: (t: ComponentType) => void }) {
  const cards = COMPONENT_TYPES.filter((t) => ALLOWED.includes(t.type));
  // Match depictio's StepType grid sizing (3 columns, 1.5rem gap, ≤900px, cards
  // fill 1fr). A 6-col track lets each card span 2 so a trailing row of 2 sits
  // centered (cards 4 & 5 offset to columns 2 and 4).
  const remainder = cards.length % 3;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(6, 1fr)',
        gap: '1.5rem',
        maxWidth: 900,
        width: '100%',
        margin: '1.5rem auto',
        padding: '0 1rem',
      }}
    >
      {cards.map((t, i) => {
        // Center the last row when it isn't full: 2 leftover → cols 2 & 4; 1 → col 3.
        const inLastRow = i >= cards.length - remainder && remainder !== 0;
        const posInRow = i - (cards.length - remainder);
        const startCol = remainder === 2 ? 2 + posInRow * 2 : 3;
        return (
          <Card
            key={t.type}
            withBorder
            radius="md"
            p="lg"
            shadow="sm"
            // The primary "Add visualization" entry point: it was a div with an
            // onClick, so the whole builder was unreachable by keyboard.
            component="button"
            type="button"
            aria-label={t.label}
            onClick={() => onPick(t.type)}
            style={{
              cursor: 'pointer',
              textAlign: 'center',
              transition: 'transform 0.2s ease, box-shadow 0.2s ease',
              height: '100%',
              width: '100%',
              font: 'inherit',
              color: 'inherit',
              gridColumn: inLastRow ? `${startCol} / span 2` : 'span 2',
            }}
            className="cs-type-card"
          >
            <Stack gap="sm" align="center">
              <Center style={{ width: 48, height: 48, borderRadius: 12, background: t.iconBg, margin: '0 auto 1rem auto' }}>
                <Icon icon={t.icon} width={24} color="white" />
              </Center>
              <Text fw={700} size="lg" ta="center">
                {t.label}
              </Text>
              <Text size="sm" c="dimmed" ta="center" mt="xs">
                {t.description}
              </Text>
            </Stack>
          </Card>
        );
      })}
    </div>
  );
}
