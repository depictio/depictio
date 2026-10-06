/**
 * The "Read a tab" demo: real sections, folding and unfolding in the real
 * section chrome, with the real "Collapse all / Expand all" above them.
 *
 * The sections are the dashboard's own — this tab's when it has some that
 * fold, else the family's pinned ones, else the first sibling tab's —
 * and they hold what they hold on the dashboard: their key figures (computed
 * by the endpoint the dashboard uses) and the kind and title of every other
 * tile. Folded, a section reads its key figures in its header, as it does on
 * the page. Only a dashboard with no foldable section anywhere gets the
 * self-contained example.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Accordion, Box, Button, Group, SimpleGrid, Skeleton, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  bulkComputeCards,
  componentTypeVisual,
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
  SectionSummary,
} from 'depictio-react-core';
import type { FilterSectionSpec, GuideDemoSection, StoredMetadata } from 'depictio-react-core';

import type { SectionsDemoSource } from '../useGuideSources';

/** Tiles shown inside an open demo section; the rest are counted. */
const MEMBER_LIMIT = 6;

const fmt = (v: unknown) =>
  typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v ?? '…');

const titleOf = (m: StoredMetadata) =>
  String(m.title || m.column_name || componentTypeVisual(m.component_type).label);

/** One tile of a demo section, as small as it can be and still be recognised. */
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
        {m.component_type === 'text' && !m.title ? 'Notes' : titleOf(m)}
      </Text>
    </Box>
  );
};

/** For a dashboard with no section that folds anywhere: two made-up ones. */
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

/** The section cards' values, unfiltered, from the tab that owns them. */
function useSectionValues(source: SectionsDemoSource | null): Record<string, unknown> {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const ids = useMemo(
    () =>
      source
        ? source.sections.flatMap((s) =>
            s.members.filter((m) => m.component_type === 'card').map((m) => m.index),
          )
        : [],
    [source],
  );
  const key = ids.join('|');
  useEffect(() => {
    if (!source || ids.length === 0) return;
    const ctrl = new AbortController();
    bulkComputeCards(source.dashboardId, [], ids, undefined, ctrl.signal)
      .then((res) => setValues(res.values ?? {}))
      .catch(() => undefined);
    return () => ctrl.abort();
    // `key` is the card ids' identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.dashboardId, key]);
  return values;
}

export const SectionsDemo: React.FC<{ source: SectionsDemoSource | null | undefined }> = ({
  source,
}) => {
  const live = useSectionValues(source ?? null);
  const sections = source ? source.sections : EXAMPLE.sections;
  const values = source ? live : EXAMPLE.values;
  const keys = sections.map((s) => s.spec.name);
  // The first opens, the rest are folded: both states on screen at once. A
  // lone section starts folded, on the state the reader cannot guess: its
  // header still reading its key numbers.
  const [open, setOpen] = useState<string[] | null>(null);
  const shown = open ?? (keys.length > 1 ? keys.slice(0, 1) : []);
  const anyOpen = shown.length > 0;

  if (source === undefined) {
    return (
      <Stack gap={6}>
        <Skeleton h={52} radius="md" />
        <Skeleton h={52} radius="md" />
      </Stack>
    );
  }

  return (
    <Stack gap={4} data-testid="guide-sections-demo">
      <Group justify="flex-end">
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
      <SectionAccordion value={shown} onChange={setOpen}>
        {sections.map(({ spec, members }) => {
          const tiles = members.filter((m) => m.component_type !== 'text' || members.length === 1);
          return (
            <SectionAccordionItem key={spec.name} value={spec.name} color={spec.color}>
              <Accordion.Control>
                <SectionHeader
                  spec={spec}
                  name={spec.name}
                  trailing={
                    shown.includes(spec.name) ? undefined : (
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
                  {tiles.slice(0, MEMBER_LIMIT).map((m) => (
                    <MemberTile key={m.index} m={m} value={values[m.index]} />
                  ))}
                </SimpleGrid>
                {tiles.length > MEMBER_LIMIT && (
                  <Text size="xs" c="dimmed" mt={6}>
                    and {tiles.length - MEMBER_LIMIT} more
                  </Text>
                )}
              </Accordion.Panel>
            </SectionAccordionItem>
          );
        })}
      </SectionAccordion>
    </Stack>
  );
};
