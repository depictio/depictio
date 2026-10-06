/**
 * The "Read a tab" demo: the tab's own sections, drawn by the grid that draws
 * them on the canvas.
 *
 * Not a picture of a section: `DashboardGrid` itself, handed the sections'
 * members and the tab's stored layout, so the header, the fold, the folded
 * summary, "Collapse all" and every tile are the dashboard's, the cards with
 * their values from the endpoint the dashboard computes them with. The
 * sections are this tab's when it has some that fold, else the family's
 * pinned ones, else the first sibling tab's; the one holding key figures
 * opens, the other is folded, so both states are on screen at once.
 *
 * What it does stays here: the fold is kept in memory rather than with the
 * reader's folds for the tab, and a filter or a selection made inside it is
 * the demo's own (see `GuideSandbox`). Only a dashboard with no section that
 * folds anywhere gets the self-contained example.
 */
import React, { useMemo, useState } from 'react';
import { Accordion, Box, Button, Group, SimpleGrid, Skeleton, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  componentTypeVisual,
  DashboardGrid,
  hasCards,
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
  SectionSummary,
} from 'depictio-react-core';
import type { FilterSectionSpec, GuideDemoSection, StoredMetadata } from 'depictio-react-core';

import { GuideSandbox } from '../GuideSandbox';
import type { SectionsDemoSource } from '../useGuideSources';
import { useCardIds, useDemoCards, useDemoFilters } from './demoState';

export const SectionsDemo: React.FC<{ source: SectionsDemoSource | null | undefined }> = ({
  source,
}) => {
  if (source === undefined) {
    return (
      <Stack gap={6}>
        <Skeleton h={52} radius="md" />
        <Skeleton h={160} radius="md" />
      </Stack>
    );
  }
  return source ? <LiveSections source={source} /> : <ExampleSections />;
};

// ---------------------------------------------------------------------------
// The dashboard's sections
// ---------------------------------------------------------------------------

const LiveSections: React.FC<{ source: SectionsDemoSource }> = ({ source }) => {
  const { sections } = source;
  const members = useMemo(() => sections.flatMap((s) => s.members), [sections]);
  // The section with key figures opens; a lone section opens too, its header
  // folding it at a click.
  const open = sections.find(hasCards) ?? sections[0];
  const specs = useMemo<FilterSectionSpec[]>(
    () =>
      sections.map((s) => ({
        ...s.spec,
        collapsed: sections.length > 1 && s !== open,
      })),
    [sections, open],
  );
  const { filters, settled, onFilterChange } = useDemoFilters(members);
  const cardIds = useCardIds(members);
  const cards = useDemoCards(source.dashboardId, cardIds, settled);
  const keyFigures = open.members.filter((m) => m.component_type === 'card').length;

  return (
    <GuideSandbox metadata={members}>
      <Stack gap={6} data-testid="guide-sections-demo">
        <Box className="depictio-guide-grid">
          <DashboardGrid
            dashboardId={source.dashboardId}
            metadataList={members}
            layoutData={source.layoutData}
            gridSections={specs}
            filters={settled}
            controlFilters={filters}
            onFilterChange={onFilterChange}
            onResetFilters={(indices) =>
              indices.forEach((index) => onFilterChange({ index, value: null }))
            }
            cardValues={cards.values}
            cardSecondaryValues={cards.secondary}
            cardValuesLoading={cards.loading}
            collapseStorageKey={null}
          />
        </Box>
        <Text size="xs" c="dimmed" data-testid="guide-sections-hint">
          {keyFigures > 0
            ? `Click “${open.spec.name}” to fold it: folded, its header still reads its ${
                keyFigures === 1 ? 'key figure' : `${keyFigures} key figures`
              }. Click again to open it.`
            : 'Click a header to fold or unfold its section.'}
        </Text>
      </Stack>
    </GuideSandbox>
  );
};

// ---------------------------------------------------------------------------
// For a dashboard with no section that folds anywhere
// ---------------------------------------------------------------------------

const fmt = (v: unknown) =>
  typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v ?? '…');

const titleOf = (m: StoredMetadata) =>
  String(m.title || m.column_name || componentTypeVisual(m.component_type).label);

/** One tile of an example section, as small as it can be and still be recognised. */
const MemberTile: React.FC<{ m: StoredMetadata; value: unknown }> = ({ m, value }) => {
  if (m.component_type === 'card') {
    const color = (m.icon_color as string | undefined) || undefined;
    return (
      <Box className="depictio-guide-tile" p={8}>
        <Group gap={6} wrap="nowrap">
          {m.icon_name && (
            <Icon
              icon={m.icon_name as string}
              width={16}
              style={{ flexShrink: 0, color: color ?? 'var(--mantine-primary-color-filled)' }}
            />
          )}
          <Text size="xs" c="dimmed" truncate>
            {titleOf(m)}
          </Text>
        </Group>
        <Text fw={700} size="md" lh={1.3} c={color}>
          {fmt(value)}
        </Text>
      </Box>
    );
  }
  const visual = componentTypeVisual(m.component_type);
  return (
    <Box className="depictio-guide-tile" p={8}>
      <Group gap={6} wrap="nowrap">
        <Icon icon={visual.icon} width={16} style={{ flexShrink: 0, color: visual.color }} />
        <Text size="xs" c="dimmed">
          {visual.label}
        </Text>
      </Group>
      <Text size="sm" fw={500} lineClamp={1}>
        {titleOf(m)}
      </Text>
    </Box>
  );
};

const EXAMPLE: { sections: GuideDemoSection[]; values: Record<string, unknown> } = (() => {
  const card = (index: string, title: string, icon: string, color: string): StoredMetadata =>
    ({ index, component_type: 'card', title, icon_name: icon, icon_color: color }) as StoredMetadata;
  const tile = (index: string, component_type: string, title: string): StoredMetadata =>
    ({ index, component_type, title }) as StoredMetadata;
  const keySpec: FilterSectionSpec = {
    name: 'Key numbers',
    icon: 'mdi:gauge',
    color: 'teal',
    description: 'The figures that matter',
  };
  const detailSpec: FilterSectionSpec = {
    name: 'Details',
    icon: 'mdi:table',
    color: 'grape',
    description: 'The rows behind them',
  };
  return {
    sections: [
      {
        spec: keySpec,
        members: [
          card('ex-samples', 'Samples', 'mdi:test-tube', 'teal'),
          card('ex-sites', 'Sites', 'mdi:map-marker', 'blue'),
          card('ex-median', 'Median depth', 'mdi:waves', 'grape'),
        ],
      },
      {
        spec: detailSpec,
        members: [tile('ex-fig', 'figure', 'Samples by site'), tile('ex-table', 'table', 'Sample sheet')],
      },
    ],
    values: { 'ex-samples': 85, 'ex-sites': 3, 'ex-median': 12.5 },
  };
})();

/** Two made-up sections in the real section chrome, for a dashboard that has
 *  no section to show. */
const ExampleSections: React.FC = () => {
  const { sections, values } = EXAMPLE;
  const keys = sections.map((s) => s.spec.name);
  const [open, setOpen] = useState<string[]>(keys.slice(0, 1));
  const anyOpen = open.length > 0;
  return (
    <Stack gap={4} data-testid="guide-sections-demo">
      <Group justify="space-between" wrap="nowrap">
        <Group gap={6} wrap="nowrap">
          <Icon
            icon="mdi:eye-off-outline"
            width={14}
            style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }}
          />
          <Text size="xs" c="dimmed">
            No section of this dashboard folds: an example
          </Text>
        </Group>
        <Button
          variant="subtle"
          color="gray"
          size="compact-xs"
          leftSection={
            <Icon
              icon={anyOpen ? 'mdi:unfold-less-horizontal' : 'mdi:unfold-more-horizontal'}
              width={14}
            />
          }
          onClick={() => setOpen(anyOpen ? [] : keys)}
        >
          {anyOpen ? 'Collapse all' : 'Expand all'}
        </Button>
      </Group>
      <SectionAccordion value={open} onChange={setOpen}>
        {sections.map(({ spec, members }) => (
          <SectionAccordionItem key={spec.name} value={spec.name} color={spec.color}>
            <Accordion.Control>
              <SectionHeader
                spec={spec}
                name={spec.name}
                trailing={
                  open.includes(spec.name) ? undefined : (
                    <SectionSummary
                      section={{ key: spec.name, sectionName: spec.name, spec, members }}
                      cardValues={values}
                    />
                  )
                }
              />
            </Accordion.Control>
            <Accordion.Panel>
              <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs">
                {members.map((m) => (
                  <MemberTile key={m.index} m={m} value={values[m.index]} />
                ))}
              </SimpleGrid>
            </Accordion.Panel>
          </SectionAccordionItem>
        ))}
      </SectionAccordion>
    </Stack>
  );
};
