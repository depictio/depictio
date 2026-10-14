import React, { useEffect, useRef, useState } from 'react';
import { Button, Group, Paper, Progress, SimpleGrid, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { componentTypeVisual } from 'depictio-react-core';

import CheckStrip from './CheckStrip';
import { sectionIconId } from '../componentVisuals';
import type { GenerateDashboardRunState } from '../hooks';
import { AI_COLOR } from '../icons';
import type {
  BudgetTick,
  ComponentCheck,
  DashboardPlan,
  GeneratedComponentEvent,
  PlannedComponent,
  PlannedSection,
} from '../types';

/** The `status` strings the generation route emits, in the order it emits
 *  them (see `gen.status(...)` in dashboard_gen.py), each with the short
 *  label the rail has room for. A status outside this list — 'starting',
 *  or a stage added server-side before this list catches up — leaves the
 *  rail on its first step rather than blanking it. */
const STAGES: { status: string; label: string }[] = [
  { status: 'reading project', label: 'Reading project' },
  { status: 'inventorying', label: 'Inventory' },
  { status: 'planning', label: 'Planning' },
  { status: 'filling', label: 'Filling' },
  { status: 'checking', label: 'Checking' },
  { status: 'laying out', label: 'Layout' },
  { status: 'saving', label: 'Saving' },
];

/** Singular and plural of each type, for the plan's "4 cards · 3 figures"
 *  tally. Types that read the same either way repeat themselves. */
const TYPE_LABEL: Record<string, [string, string]> = {
  figure: ['figure', 'figures'],
  card: ['card', 'cards'],
  interactive: ['interactive', 'interactive'],
  table: ['table', 'tables'],
  text: ['text', 'texts'],
  map: ['map', 'maps'],
  image: ['image', 'images'],
  multiqc: ['MultiQC', 'MultiQC'],
  advanced_viz: ['advanced viz', 'advanced viz'],
};

/** Components a section lists before the rest fold away: enough to judge the
 *  shape of the section without burying the sections after it. */
const SECTION_INLINE_MAX = 4;

type RowStatus = GeneratedComponentEvent['status'] | 'pending';

interface Row {
  tag: string;
  section: string;
  component_type: string;
  status: RowStatus;
  attempts?: number;
  error?: string | null;
  /** Undefined while the component is still pending, and on a run whose
   *  server did not report the gates. */
  checks?: ComponentCheck[];
}

/** Plan rows first, in plan order, each carrying its latest outcome; then
 *  any reported tag the plan did not name, so a row never goes missing. */
export function mergeRows(planned: PlannedComponent[], events: GeneratedComponentEvent[]): Row[] {
  const byTag = new Map(events.map((e) => [e.tag, e]));
  const rows: Row[] = planned.map((p) => {
    const e = byTag.get(p.tag);
    return {
      tag: p.tag,
      section: p.section,
      component_type: p.component_type,
      status: e?.status ?? 'pending',
      attempts: e?.attempts,
      error: e?.error,
      checks: e?.checks,
    };
  });
  const known = new Set(planned.map((p) => p.tag));
  for (const e of events) {
    if (!known.has(e.tag)) rows.push({ ...e });
  }
  return rows;
}

/** Tokens and wall clock both cap a run; the bar tracks whichever is closer
 *  to its limit. Null when no budget tick has arrived yet. */
export function budgetPercent(budget: BudgetTick | null): number | null {
  if (!budget) return null;
  const tokenPct = budget.max_tokens > 0 ? (budget.tokens_used / budget.max_tokens) * 100 : 0;
  const secondsPct = budget.max_seconds > 0 ? (budget.seconds / budget.max_seconds) * 100 : 0;
  return Math.min(100, Math.max(tokenPct, secondsPct));
}

function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0s';
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`;
}

/** Estimated dollars. A run costing a fraction of a cent still cost
 *  something, so it reads as a floor rather than as `~$0.00`. */
export function formatCost(cost: number): string {
  if (cost > 0 && cost < 0.01) return '<$0.01';
  return `~$${cost.toFixed(2)}`;
}

function typeLabel(type: string, count = 1): string {
  const pair = TYPE_LABEL[type];
  if (!pair) return type;
  return count === 1 ? pair[0] : pair[1];
}

/** "4 cards · 3 figures · 2 interactive", commonest type first. */
function typeTally(components: PlannedComponent[]): string {
  const counts = new Map<string, number>();
  for (const c of components) counts.set(c.component_type, (counts.get(c.component_type) ?? 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type, n]) => `${n} ${typeLabel(type, n)}`)
    .join(' · ');
}

/** The collections the plan reads from, deduplicated, in plan order. */
function planCollections(components: PlannedComponent[]): string[] {
  const tags: string[] = [];
  for (const c of components) {
    const tag = (c.data_collection_tag ?? '').trim();
    if (tag && !tags.includes(tag)) tags.push(tag);
  }
  return tags;
}

interface SectionGroup {
  name: string;
  kind: 'filter' | 'grid' | 'unplaced';
  section: PlannedSection | null;
}

/** The plan's sections in funnel order (filter panels first, then the grid),
 *  with a trailing catch-all for components whose section the plan never
 *  names, so nothing is dropped from either the plan or the card grid. */
function sectionGroups(plan: DashboardPlan | null, sections: string[]): SectionGroup[] {
  const groups: SectionGroup[] = [];
  const named = new Set<string>();
  for (const s of plan?.filter_sections ?? []) {
    groups.push({ name: s.name, kind: 'filter', section: s });
    named.add(s.name);
  }
  for (const s of plan?.grid_sections ?? []) {
    groups.push({ name: s.name, kind: 'grid', section: s });
    named.add(s.name);
  }
  if (sections.some((name) => !named.has(name))) {
    groups.push({ name: 'Unplaced', kind: 'unplaced', section: null });
  }
  return groups;
}

/** Members of one group: whatever names that section, and everything the plan
 *  left unplaced for the catch-all group. Serves both the plan's components
 *  and the live rows, which carry the same `section` handle. */
function membersOfGroup<T extends { section: string }>(
  group: SectionGroup,
  members: T[],
  placed: Set<string>,
): T[] {
  if (group.kind === 'unplaced') return members.filter((m) => !placed.has(m.section));
  return members.filter((m) => m.section === group.name);
}

/** A section keeps the icon and the colour the planner gave it, so the plan
 *  reads like the dashboard it is about to become. */
function sectionVisual(section: PlannedSection | null, kind: string): {
  icon: string;
  color: string;
} {
  return {
    icon: sectionIconId(section?.icon, kind),
    color: section?.color
      ? `var(--mantine-color-${section.color}-6)`
      : 'var(--mantine-color-gray-6)',
  };
}

/** Wall clock per stage, read from the `status` events alone: a status change
 *  closes the stage before it and opens the next. Planning is the longest
 *  call of a run and, untimed, is indistinguishable from a hang. */
function useStageTimings(status: string, running: boolean) {
  const [durations, setDurations] = useState<Record<string, number>>({});
  const [elapsed, setElapsed] = useState(0);
  const openedAt = useRef(Date.now());
  const openStatus = useRef('');

  useEffect(() => {
    const previous = openStatus.current;
    if (previous === status) return;
    const since = openedAt.current;
    openStatus.current = status;
    openedAt.current = Date.now();
    setElapsed(0);
    // Every run opens on 'starting' (useGenerateDashboard sets it before the
    // stream does), which is where a second run drops the first one's times.
    if (status === 'starting') {
      setDurations({});
      return;
    }
    if (previous && previous !== 'starting') {
      setDurations((d) => ({ ...d, [previous]: (Date.now() - since) / 1000 }));
    }
  }, [status]);

  useEffect(() => {
    if (!running) {
      // The stream ended on this stage: freeze what it took, rather than
      // leaving the last stage of a finished run without a time.
      const open = openStatus.current;
      const since = openedAt.current;
      if (open && open !== 'starting') {
        setDurations((d) => (open in d ? d : { ...d, [open]: (Date.now() - since) / 1000 }));
      }
      return;
    }
    const timer = window.setInterval(() => {
      setElapsed((Date.now() - openedAt.current) / 1000);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [running, status]);

  return { durations, elapsed };
}

/** Six equal segments under one line naming the current stage. Fixed width
 *  whatever the column: a segment shrinks, a step label would not. */
const StageRail: React.FC<{
  index: number;
  complete: boolean;
  running: boolean;
  failed: boolean;
  durations: Record<string, number>;
  elapsed: number;
}> = ({ index, complete, running, failed, durations, elapsed }) => {
  const current = STAGES[Math.min(Math.max(index, 0), STAGES.length - 1)];
  const spentHere = running ? elapsed : durations[current.status];
  const timed = STAGES.filter((s) => durations[s.status] !== undefined);

  return (
    <Stack gap={6}>
      <Group gap={8} wrap="nowrap" justify="space-between">
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <Text size="sm" fw={600} truncate>
            {complete ? 'Complete' : current.label}
          </Text>
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            step {complete ? STAGES.length : index + 1} of {STAGES.length}
          </Text>
        </Group>
        {!complete && spentHere !== undefined && (
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            {formatSeconds(spentHere)}
          </Text>
        )}
      </Group>
      <Group gap={4} wrap="nowrap">
        {STAGES.map((stage, i) => {
          const done = complete || i < index;
          const isCurrent = !complete && i === index;
          const spent = durations[stage.status];
          return (
            <Tooltip
              key={stage.status}
              label={spent === undefined ? stage.label : `${stage.label} · ${formatSeconds(spent)}`}
              withArrow
              openDelay={200}
            >
              <Progress
                value={done || isCurrent ? 100 : 0}
                size="sm"
                radius="xl"
                color={isCurrent && failed ? 'red' : AI_COLOR}
                striped={isCurrent && running}
                animated={isCurrent && running}
                // Stages still ahead read as a track, not as work done.
                style={{ flex: 1, minWidth: 0, opacity: done || isCurrent ? 1 : 0.45 }}
                aria-label={stage.label}
              />
            </Tooltip>
          );
        })}
      </Group>
      {/* Once the stream is over the hover targets are gone from the reader's
          mind: spell the run out so it can be read back. */}
      {!running && timed.length > 0 && (
        <Text size="xs" c="dimmed">
          {timed.map((s) => `${s.label} ${formatSeconds(durations[s.status])}`).join(' · ')}
        </Text>
      )}
    </Stack>
  );
};

/** One planned section as the reviewer reads it: what it is for, and what it
 *  will hold. Long sections fold past the first few components. */
const PlanSectionBlock: React.FC<{ group: SectionGroup; components: PlannedComponent[] }> = ({
  group,
  components,
}) => {
  const [open, setOpen] = useState(false);
  const hidden = Math.max(components.length - SECTION_INLINE_MAX, 0);
  const shown = open ? components : components.slice(0, SECTION_INLINE_MAX);
  const kind = group.kind === 'filter' ? 'filter panel' : group.kind === 'grid' ? 'section' : '';
  const visual = sectionVisual(group.section, group.kind);

  return (
    <Paper withBorder radius="sm" p="xs" data-testid="generate-plan-section">
      <Stack gap={4}>
        <Group gap={6} wrap="nowrap" align="center">
          <Icon
            icon={visual.icon}
            width={16}
            color={visual.color}
            style={{ flexShrink: 0 }}
          />
          <Text size="xs" fw={600} truncate>
            {group.name}
          </Text>
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            {kind && `${kind} · `}
            {components.length} {components.length === 1 ? 'component' : 'components'}
          </Text>
        </Group>
        {group.section?.rationale && (
          <Text size="xs" c="dimmed">
            {group.section.rationale}
          </Text>
        )}
        {shown.map((c) => (
          <Group key={c.tag} gap={6} wrap="nowrap" align="flex-start">
            <Icon
              icon={componentTypeVisual(c.component_type).icon}
              width={14}
              color={componentTypeVisual(c.component_type).color}
              style={{ marginTop: 3, flexShrink: 0 }}
            />
            <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
              <Group gap={6} wrap="nowrap">
                <Text size="xs" fw={500} truncate>
                  {c.tag}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  {typeLabel(c.component_type)}
                  {c.data_collection_tag ? ` · ${c.data_collection_tag}` : ''}
                </Text>
              </Group>
              {c.intent && (
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {c.intent}
                </Text>
              )}
            </Stack>
          </Group>
        ))}
        {hidden > 0 && (
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            onClick={() => setOpen((o) => !o)}
            rightSection={<Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />}
            style={{ alignSelf: 'flex-start' }}
          >
            {open ? 'Show fewer' : `${hidden} more`}
          </Button>
        )}
      </Stack>
    </Paper>
  );
};

/** The right-hand end of a component card: what became of the component.
 *  Anything not yet reported stays colourless, so colour on this grid only
 *  ever means an outcome. */
const Outcome: React.FC<{ row: Row }> = ({ row }) => {
  if (row.status === 'pending') {
    return (
      <Text size="xs" c="dimmed">
        planned
      </Text>
    );
  }
  if (row.status === 'ok') {
    return <Icon icon="mdi:check-circle" width={18} color="var(--mantine-color-teal-6)" />;
  }
  if (row.status === 'repaired') {
    return (
      <Group gap={4} wrap="nowrap">
        <Icon icon="mdi:wrench-outline" width={18} color="var(--mantine-color-yellow-6)" />
        {row.attempts !== undefined && row.attempts > 1 && (
          <Text size="xs" c="dimmed">
            {row.attempts} attempts
          </Text>
        )}
      </Group>
    );
  }
  return <Icon icon="mdi:minus-circle" width={18} color="var(--mantine-color-red-6)" />;
};

/** What a whole dialog session has spent, summed over its calls. Reviewing a
 *  plan before building it costs two calls, and the second one resets the run
 *  state, so the first one's spend only survives here. */
export interface SessionSpend {
  /** Calls counted, the one in flight included. */
  runs: number;
  tokens: number;
  seconds: number;
  /** Null when no call could be priced. */
  cost: number | null;
}

export interface GenerationProgressProps {
  /** The whole run as `useGenerateDashboard` accumulates it. */
  state: GenerateDashboardRunState;
  /** True while the stream is open; the current segment pulses. */
  pending: boolean;
  /** Totals across every call of the dialog session, when there has been
   *  more than one. Omitted, only the current run's budget shows. */
  sessionSpend?: SessionSpend | null;
}

/**
 * Everything a generation run has to say, in one block: how far it has
 * come, what it has spent, what it decided to build and how each piece
 * landed. The panel frames it; this owns the reading of it.
 */
const GenerationProgress: React.FC<GenerationProgressProps> = ({
  state,
  pending,
  sessionSpend = null,
}) => {
  const stageIndex = STAGES.findIndex((s) => s.status === state.status);
  // A finished run reads done end to end; anything else sits on the stage
  // the last status named, which is also the stage an error marks red.
  const complete = Boolean(state.dashboard);
  const index = Math.max(stageIndex, 0);
  const running = pending && !state.error;
  const { durations, elapsed } = useStageTimings(state.status, running);

  const budgetPct = budgetPercent(state.budget);
  const cost = typeof state.budget?.cost_usd === 'number' ? state.budget.cost_usd : null;
  const plan = state.plan;
  const rows = mergeRows(plan?.components ?? [], state.components);
  const groups = sectionGroups(
    plan,
    rows.map((r) => r.section),
  );
  const placed = new Set(
    groups.filter((g) => g.kind !== 'unplaced').map((g) => g.name),
  );
  const collections = plan ? planCollections(plan.components) : [];
  const sectionCount = plan ? plan.filter_sections.length + plan.grid_sections.length : 0;

  return (
    <Stack gap="md">
      <StageRail
        index={index}
        complete={complete}
        running={running}
        failed={Boolean(state.error)}
        durations={durations}
        elapsed={elapsed}
      />

      {/* The bar is the current call's; the line under it is the session's,
          which is the only place the planning call's spend survives. */}
      <Stack gap={2}>
        {budgetPct !== null && state.budget && (
          <Group gap="xs" wrap="nowrap">
            <Tooltip
              multiline
              w={280}
              withArrow
              label={
                `One run stops at ${state.budget.max_tokens.toLocaleString()} tokens ` +
                `or ${Math.round(state.budget.max_seconds)}s, whichever it reaches first. ` +
                'The bar tracks whichever is closer to its limit.'
              }
            >
              <Text size="xs" c="dimmed" style={{ flexShrink: 0, cursor: 'help' }}>
                Run limit
              </Text>
            </Tooltip>
            <Progress
              value={budgetPct}
              size="sm"
              radius="xl"
              color={AI_COLOR}
              style={{ flex: 1 }}
              aria-label="Share of the run limit spent"
            />
            <Group gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
              <Text size="xs" c="dimmed">
                {state.budget.tokens_used.toLocaleString()} tokens ·{' '}
                {Math.round(state.budget.seconds)}s
              </Text>
              {cost !== null && (
                <Tooltip label="Estimated from the model's public pricing." withArrow>
                  <Text size="xs" c="dimmed" style={{ cursor: 'help' }}>
                    {formatCost(cost)}
                  </Text>
                </Tooltip>
              )}
            </Group>
          </Group>
        )}
        {sessionSpend && sessionSpend.runs > 1 && (
          <Text size="xs" c="dimmed">
            Session total over {sessionSpend.runs} calls:{' '}
            {sessionSpend.tokens.toLocaleString()} tokens · {formatSeconds(sessionSpend.seconds)}
            {sessionSpend.cost !== null ? ` · ${formatCost(sessionSpend.cost)}` : ''}
          </Text>
        )}
      </Stack>

      {plan && (
        <Stack gap="xs" data-testid="generate-plan">
          <Stack gap={2}>
            <Text fw={600} size="sm">
              {plan.title || 'Plan'}
            </Text>
            {plan.subtitle && <Text size="sm">{plan.subtitle}</Text>}
            <Text size="xs" c="dimmed">
              {plan.components.length}{' '}
              {plan.components.length === 1 ? 'component' : 'components'} · {sectionCount}{' '}
              {sectionCount === 1 ? 'section' : 'sections'}
              {collections.length > 0 && ` · ${collections.join(', ')}`}
            </Text>
            {plan.components.length > 0 && (
              <Text size="xs" c="dimmed">
                {typeTally(plan.components)}
              </Text>
            )}
          </Stack>
          {groups.map((group) => {
            const components = membersOfGroup(group, plan.components, placed);
            // An empty planned section still says something about the shape;
            // an empty catch-all says nothing.
            if (components.length === 0 && group.kind === 'unplaced') return null;
            return <PlanSectionBlock key={group.name} group={group} components={components} />;
          })}
        </Stack>
      )}

      {rows.length > 0 && (
        <Stack gap="sm">
          {groups.map((group) => {
            const groupRows = membersOfGroup(group, rows, placed);
            if (groupRows.length === 0) return null;
            return (
              <Stack gap={4} key={group.name}>
                <Group gap={6} wrap="nowrap">
                  <Text size="xs" fw={600} tt="uppercase" c="dimmed" truncate>
                    {group.name}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                    {groupRows.length}
                  </Text>
                </Group>
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
                  {groupRows.map((row) => (
                    <Paper
                      key={row.tag}
                      withBorder
                      radius="sm"
                      p="xs"
                      // A component nobody has reported on yet should not draw
                      // the eye: only outcomes get contrast.
                      style={
                        row.status === 'pending'
                          ? { borderColor: 'var(--mantine-color-gray-3)' }
                          : undefined
                      }
                      data-testid="generate-progress-component"
                      data-tag={row.tag}
                      data-status={row.status}
                    >
                      <Stack gap={2}>
                        <Group gap="xs" wrap="nowrap" align="flex-start">
                          <Icon
                            icon={componentTypeVisual(row.component_type).icon}
                            width={18}
                            color={componentTypeVisual(row.component_type).color}
                            style={{ marginTop: 2, flexShrink: 0 }}
                          />
                          <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
                            <Text fw={600} size="sm" truncate>
                              {row.tag}
                            </Text>
                            <Text size="xs" c="dimmed" truncate>
                              {typeLabel(row.component_type)}
                            </Text>
                          </Stack>
                          <Outcome row={row} />
                        </Group>
                        {/* The gates, once the tile has been through any: a row
                            of marks says how it got here, which the single
                            outcome icon on its own cannot. A pending row, and a
                            run whose server reported no gates, stay silent
                            rather than saying they were not recorded. */}
                        {row.checks && row.checks.length > 0 && (
                          <CheckStrip checks={row.checks} testId="generate-progress-checks" />
                        )}
                        {row.error && (
                          <Text
                            size="xs"
                            c="red"
                            lineClamp={2}
                            title={row.error}
                            style={{ minWidth: 0 }}
                          >
                            {row.error}
                          </Text>
                        )}
                      </Stack>
                    </Paper>
                  ))}
                </SimpleGrid>
              </Stack>
            );
          })}
        </Stack>
      )}
    </Stack>
  );
};

export default GenerationProgress;
