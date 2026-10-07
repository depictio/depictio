/**
 * The Analysis part's demo: make a group from a selection and compare it, on
 * the dashboard's own components, in three steps.
 *
 * A figure a lasso can be drawn on, a table whose rows can be ticked and a
 * card, each the dashboard's own and drawn by the real renderers. The groups
 * go through the same path as on the canvas: a selection becomes a group
 * (`groupFromSelectionFilter`), the groups become the figure's render request
 * (`resolveGroupRender`, the `groupRender` the grid hands every figure) and
 * the card's per-group comparison (`compare_groups` on the bulk endpoint).
 *
 * What differs is where the state lives: here. Analysis is on in the demo
 * only, its selection is the demo's own filter and its groups the demo's own
 * list — the reader's groups, filters and colouring are left as they were.
 */
import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  CloseButton,
  Grid,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  COLOR_BY_NONE,
  ComponentRenderer,
  defaultGroupName,
  groupFromSelectionFilter,
  groupsRenderPayload,
  nextGroupColor,
  resolveGroupRender,
  selectableSelectionFilters,
  uniqueGroupName,
  useGroupingColor,
} from 'depictio-react-core';
import type {
  BulkComputeOptions,
  GroupingDisplay,
  InteractiveFilter,
  SaveGroupApi,
  SelectionGroup,
  StoredMetadata,
} from 'depictio-react-core';

import { GuideSandbox } from '../GuideSandbox';
import type { AnalysisDemoSource, GuideComponentSource } from '../useGuideSources';
import { useDemoCards, useDemoFilters } from './demoState';

const titleOf = (m: StoredMetadata) => String(m.title || m.column_name || 'it');

/** "a", "a and b", "a, b and c". */
const listed = (items: readonly string[]) =>
  items.length <= 1
    ? (items[0] ?? '')
    : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;

export const AnalysisDemo: React.FC<{ source: AnalysisDemoSource | null | undefined }> = ({
  source,
}) => {
  if (source === undefined) {
    return (
      <Stack gap="sm">
        <Skeleton h={64} radius="md" />
        <Skeleton h={300} radius="md" />
      </Stack>
    );
  }
  if (source === null) {
    return (
      <Group gap={6} wrap="nowrap" data-testid="guide-analysis-none">
        <Icon
          icon="mdi:eye-off-outline"
          width={14}
          style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }}
        />
        <Text size="xs" c="dimmed">
          No figure or table of this dashboard takes a selection, which is what a group is made
          from.
        </Text>
      </Group>
    );
  }
  return <LiveAnalysis source={source} />;
};

// ---------------------------------------------------------------------------

const LiveAnalysis: React.FC<{ source: AnalysisDemoSource }> = ({ source }) => {
  const { figure, table, card } = source;
  const members = useMemo(
    () => [figure, table, card].filter(Boolean).map((s) => (s as GuideComponentSource).metadata),
    [figure, table, card],
  );
  const { filters, settled, onFilterChange, applyNow, reset } = useDemoFilters(members);
  const [groups, setGroups] = useState<SelectionGroup[]>([]);
  const [display, setDisplay] = useState<GroupingDisplay>('color');
  const groupsRef = useRef(groups);
  groupsRef.current = groups;

  // The groups as the canvas sends them: colouring for the figure, a
  // comparison for the card.
  const renderGroups = useMemo(() => groupsRenderPayload(groups), [groups]);
  const groupRender = useMemo(
    () =>
      resolveGroupRender(
        renderGroups.length > 0 ? { kind: 'groups' } : COLOR_BY_NONE,
        renderGroups,
        undefined,
        display,
        true,
      ),
    [renderGroups, display],
  );
  const bulkOptions = useMemo<BulkComputeOptions | undefined>(
    () =>
      renderGroups.length > 0
        ? { groups: renderGroups, compareGroups: true, showOther: true, showOverall: true }
        : undefined,
    [renderGroups],
  );
  const cards = useDemoCards(
    card?.dashboardId,
    card ? [card.metadata.index] : [],
    settled,
    bulkOptions,
  );

  const createGroup = useCallback((filter: InteractiveFilter, name: string, color: string) => {
    const created = groupFromSelectionFilter(
      filter,
      uniqueGroupName(name, groupsRef.current),
      color,
    );
    if (created) setGroups((prev) => [...prev, created]);
    return created;
  }, []);
  // The selection goes as the group comes, in one fetch.
  const saveGroup = useMemo<SaveGroupApi>(
    () => ({ groups, createGroup, clearSelection: applyNow, analysisEngaged: true }),
    [groups, createGroup, applyNow],
  );

  const selection = selectableSelectionFilters(filters)[0];
  const selected = Array.isArray(selection?.value) ? selection.value.length : 0;
  const saveSelection = () => {
    if (!selection) return;
    const created = createGroup(selection, defaultGroupName(groups), nextGroupColor(groups));
    if (created) applyNow({ ...selection, value: [] });
  };
  const startOver = () => {
    setGroups([]);
    setDisplay('color');
    reset();
  };
  // A selection made with groups already saved is the next group on its way:
  // step 2 again, not step 3.
  const step = selected > 0 ? 2 : groups.length > 0 ? 3 : 1;
  // A figure can be split into a panel per group; an ordination only colours,
  // its one shared space being the point of it.
  const canSplit = figure?.metadata.component_type === 'figure';
  const groupingColor = useGroupingColor();

  const kinds = [figure && 'figure', table && 'table', card && 'card'].filter(Boolean) as string[];
  const selectHow = [
    figure && `lasso points on “${titleOf(figure.metadata)}”`,
    table && `tick rows in “${titleOf(table.metadata)}”`,
  ]
    .filter(Boolean)
    .join(', or ');
  const tabs = [...new Set([figure, table, card].filter(Boolean).map((s) => s!.tabLabel))];

  return (
    <GuideSandbox metadata={members} saveGroup={saveGroup}>
      <Stack gap="sm" data-testid="guide-analysis-demo">
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
          <Step
            n={1}
            active={step === 1}
            done={groups.length === 0 && step > 1}
            repeat={groups.length > 0}
            color={groupingColor}
            title={groups.length > 0 ? 'Select again' : 'Select'}
          >
            <Text size="xs" c="dimmed" lh={1.4}>
              {selectHow.charAt(0).toUpperCase() + selectHow.slice(1)}
              {groups.length > 0 ? `: other ones make group ${groups.length + 1}.` : '.'}
            </Text>
            {selected > 0 && (
              <Text size="xs" fw={600} mt={4} data-testid="guide-analysis-selected">
                {selected.toLocaleString()} selected
              </Text>
            )}
          </Step>
          <Step
            n={2}
            active={step === 2}
            done={step > 2}
            color={groupingColor}
            // Numbered only while the next group is on its way: ticked, the
            // step says what was done, and the next number was not saved yet.
            title={
              step === 2 && groups.length > 0
                ? `Save as group ${groups.length + 1}`
                : 'Save as group'
            }
          >
            <Button
              size="compact-xs"
              color={groupingColor}
              variant={selected > 0 ? 'filled' : 'light'}
              disabled={selected === 0}
              leftSection={<Icon icon="mdi:select-group" width={14} />}
              onClick={saveSelection}
              data-testid="guide-analysis-save"
            >
              {groups.length > 0 ? `Save as group ${groups.length + 1}` : 'Save as group'}
            </Button>
            <Text size="xs" c="dimmed" lh={1.4} mt={4}>
              Or the{' '}
              <Icon
                icon="mdi:select-group"
                width={12}
                style={{
                  verticalAlign: '-2px',
                  color: `var(--mantine-color-${groupingColor}-filled)`,
                }}
              />{' '}
              on the tile.
            </Text>
          </Step>
          <Step n={3} active={step === 3} done={false} color={groupingColor} title="Compare">
            <Text size="xs" c="dimmed" lh={1.4}>
              {figure
                ? 'The figure draws each group in its colour, overlaid or split'
                : 'Groups are saved'}
              {card ? '; the card reads each group.' : '.'}
            </Text>
          </Step>
        </SimpleGrid>

        {/* After the first group, say the steps go round again: a comparison
            needs a second group, and nothing on screen said it could be made. */}
        {groups.length === 1 && selected === 0 && (
          <Group gap={6} wrap="nowrap" data-testid="guide-analysis-again">
            <Icon
              icon="mdi:repeat"
              width={14}
              style={{ color: `var(--mantine-color-${groupingColor}-filled)`, flexShrink: 0 }}
            />
            <Text size="xs" c="dimmed">
              Do it again for a second group: select other points, then Save as group 2. Each
              group gets its own colour.
            </Text>
          </Group>
        )}

        {groups.length > 0 && (
          <Group gap="xs" wrap="wrap" data-testid="guide-analysis-groups">
            {groups.map((g) => (
              <Badge
                key={g.id}
                variant="light"
                color="gray"
                size="lg"
                radius="sm"
                leftSection={
                  <Box
                    component="span"
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 5,
                      background: g.color,
                      display: 'inline-block',
                    }}
                  />
                }
                rightSection={
                  <CloseButton
                    size="xs"
                    aria-label={`Delete ${g.name}`}
                    onClick={() => setGroups((prev) => prev.filter((x) => x.id !== g.id))}
                  />
                }
                styles={{ label: { textTransform: 'none' } }}
              >
                {g.name} · {g.values.length}
              </Badge>
            ))}
            <Button variant="subtle" color="gray" size="compact-xs" onClick={startOver}>
              Start over
            </Button>
          </Group>
        )}

        <Grid gutter="xs">
          {figure && (
            <Grid.Col span={{ base: 12, sm: card ? 8 : 12 }}>
              <Group justify="flex-end" mb={6}>
                <Tooltip
                  label={
                    groups.length === 0
                      ? 'Save a group first'
                      : canSplit
                        ? 'Overlay draws the groups in one panel; Split gives each group its own'
                        : 'An ordination stays one panel: its shared space is what it compares'
                  }
                  withArrow
                  openDelay={300}
                >
                  <SegmentedControl
                    size="xs"
                    value={canSplit ? display : 'color'}
                    onChange={(v) => setDisplay(v as GroupingDisplay)}
                    disabled={groups.length === 0 || !canSplit}
                    data={[
                      { value: 'color', label: 'Overlay' },
                      { value: 'facet', label: 'Split' },
                    ]}
                    aria-label="Show the groups overlaid or split"
                    data-testid="guide-analysis-display"
                  />
                </Tooltip>
              </Group>
              <Box className="depictio-guide-demo-tile is-analysis" h={{ base: 300, sm: 340 }}>
                <div className="depictio-guide-demo-cell" data-testid="guide-analysis-figure">
                  <ComponentRenderer
                    metadata={figure.metadata}
                    dashboardId={figure.dashboardId}
                    filters={settled}
                    onFilterChange={onFilterChange}
                    groupRender={groupRender}
                  />
                </div>
              </Box>
            </Grid.Col>
          )}
          {card && (
            <Grid.Col span={{ base: 12, sm: figure ? 4 : 6 }}>
              <Box className="depictio-guide-demo-tile is-analysis" mih={140}>
                <div className="depictio-guide-demo-cell" data-testid="guide-analysis-card">
                  <ComponentRenderer
                    metadata={card.metadata}
                    dashboardId={card.dashboardId}
                    filters={settled}
                    cardValue={cards.values[card.metadata.index]}
                    cardSecondaryValues={cards.secondary[card.metadata.index]}
                    cardLoading={cards.loading}
                  />
                </div>
              </Box>
            </Grid.Col>
          )}
          {table && (
            <Grid.Col span={12}>
              <Box className="depictio-guide-demo-tile is-analysis" h={{ base: 300, sm: 320 }}>
                <div className="depictio-guide-demo-cell" data-testid="guide-analysis-table">
                  <ComponentRenderer
                    metadata={table.metadata}
                    dashboardId={table.dashboardId}
                    filters={settled}
                    onFilterChange={onFilterChange}
                  />
                </div>
              </Box>
            </Grid.Col>
          )}
        </Grid>
        <Text size="xs" c="dimmed">
          The dashboard’s own {listed(kinds)}, from {listed(tabs)}. Groups made here stay here:
          yours are left as they are.
        </Text>
      </Stack>
    </GuideSandbox>
  );
};

/** One of the three steps, lit while it is the one to take. */
const Step: React.FC<{
  n: number;
  title: string;
  active: boolean;
  done: boolean;
  /** A step to take again (selecting, once there is a group): a repeat mark
   *  in place of its number. */
  repeat?: boolean;
  color: string;
  children: React.ReactNode;
}> = ({ n, title, active, done, repeat, color, children }) => (
  <Paper
    withBorder
    radius="md"
    p="xs"
    className={'depictio-guide-step' + (active ? ' is-active' : '')}
    style={
      active
        ? ({
            '--depictio-guide-step-color': `var(--mantine-color-${color}-filled)`,
          } as React.CSSProperties)
        : undefined
    }
    data-testid={`guide-analysis-step-${n}`}
    data-active={active || undefined}
  >
    <Group gap={8} wrap="nowrap" mb={4}>
      <ThemeIcon
        size={20}
        radius="xl"
        color={done ? 'teal' : color}
        variant={active ? 'filled' : 'light'}
      >
        {done ? (
          <Icon icon="mdi:check" width={13} />
        ) : repeat ? (
          <Icon icon="mdi:repeat" width={13} />
        ) : (
          <Text size="xs" fw={700}>
            {n}
          </Text>
        )}
      </ThemeIcon>
      <Text size="sm" fw={600}>
        {title}
      </Text>
    </Group>
    {children}
  </Paper>
);
