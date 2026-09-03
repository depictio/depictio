import React, { useState } from 'react';
import {
  Button,
  Collapse,
  Group,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Stepper,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { GenerateDashboardRunState } from '../hooks';
import { AI_COLOR } from '../icons';
import type {
  BudgetTick,
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
  { status: 'laying out', label: 'Layout' },
  { status: 'saving', label: 'Saving' },
];

/** Iconify ids per component type, mirroring COMPONENT_TYPE_VISUALS in
 *  depictio-react-core so a card here shows the same icon the builder's
 *  type grid does. Written as literals on purpose: the viewer's
 *  generate-icon-subset.mjs scans package sources for `prefix:name`, so an
 *  id assembled at runtime would ship as a blank box under the CSP. */
const TYPE_ICON: Record<string, string> = {
  figure: 'mdi:graph-box',
  card: 'formkit:number',
  interactive: 'bx:slider-alt',
  table: 'octicon:table-24',
  text: 'mdi:text-box-edit',
  map: 'mdi:map-marker-multiple',
  image: 'mdi:image-area',
  multiqc: 'mdi:chart-line',
  advanced_viz: 'mdi:chart-scatter-plot-hexbin',
};

const UNKNOWN_TYPE_ICON = 'mdi:puzzle';

/** Rationales are the planner explaining itself; past a handful they crowd
 *  out the run, so they fold away. */
const RATIONALES_INLINE_MAX = 3;

type RowStatus = GeneratedComponentEvent['status'] | 'pending';

interface Row {
  tag: string;
  section: string;
  component_type: string;
  status: RowStatus;
  attempts?: number;
  error?: string | null;
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

function sectionNames(sections: PlannedSection[]): string {
  return sections.map((s) => s.name).join(', ');
}

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

export interface GenerationProgressProps {
  /** The whole run as `useGenerateDashboard` accumulates it. */
  state: GenerateDashboardRunState;
  /** True while the stream is open; the rail spins on its current step. */
  pending: boolean;
}

/**
 * Everything a generation run has to say, in one block: how far it has
 * come, what it has spent, what it decided to build and how each piece
 * landed. The panel frames it; this owns the reading of it.
 */
const GenerationProgress: React.FC<GenerationProgressProps> = ({ state, pending }) => {
  const [rationalesOpen, setRationalesOpen] = useState(false);

  const stageIndex = STAGES.findIndex((s) => s.status === state.status);
  // A finished run reads done end to end; anything else sits on the stage
  // the last status named, which is also the step an error marks red.
  const active = state.dashboard ? STAGES.length : Math.max(stageIndex, 0);

  const budgetPct = budgetPercent(state.budget);
  const plan = state.plan;
  const rows = mergeRows(plan?.components ?? [], state.components);
  const rationales = plan
    ? [...plan.filter_sections, ...plan.grid_sections].filter((s) => s.rationale)
    : [];
  const foldRationales = rationales.length > RATIONALES_INLINE_MAX;

  const rationaleRows = (
    <Stack gap={2}>
      {rationales.map((s) => (
        <Group key={s.name} gap={6} wrap="nowrap" align="baseline">
          <Text fw={500} size="xs" style={{ flexShrink: 0 }}>
            {s.name}
          </Text>
          <Text size="xs" c="dimmed">
            {s.rationale}
          </Text>
        </Group>
      ))}
    </Stack>
  );

  return (
    <Stack gap="md">
      <Stepper
        active={active}
        size="xs"
        iconSize={22}
        color={AI_COLOR}
        allowNextStepsSelect={false}
      >
        {STAGES.map((stage, i) => (
          <Stepper.Step
            key={stage.status}
            label={stage.label}
            loading={pending && !state.error && i === active}
            color={state.error && i === active ? 'red' : AI_COLOR}
          />
        ))}
      </Stepper>

      {budgetPct !== null && state.budget && (
        <Group gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            Budget
          </Text>
          <Progress
            value={budgetPct}
            size="sm"
            radius="xl"
            color={AI_COLOR}
            style={{ flex: 1 }}
            aria-label="Budget spent"
          />
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            {state.budget.tokens_used.toLocaleString()} tokens ·{' '}
            {Math.round(state.budget.seconds)}s
          </Text>
        </Group>
      )}

      {plan && (
        <Stack gap={4} data-testid="generate-plan">
          <Text fw={600} size="sm">
            {plan.title || 'Plan'}
          </Text>
          {plan.subtitle && <Text size="sm">{plan.subtitle}</Text>}
          <Text size="xs" c="dimmed">
            {plan.components.length} components
            {plan.filter_sections.length > 0 &&
              ` · filters: ${sectionNames(plan.filter_sections)}`}
            {plan.grid_sections.length > 0 && ` · sections: ${sectionNames(plan.grid_sections)}`}
          </Text>
          {rationales.length > 0 &&
            (foldRationales ? (
              <Stack gap={2} align="flex-start">
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="gray"
                  rightSection={
                    <Icon
                      icon={rationalesOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'}
                      width={14}
                    />
                  }
                  onClick={() => setRationalesOpen((o) => !o)}
                  data-testid="generate-plan-rationales-toggle"
                >
                  Why these sections
                </Button>
                <Collapse in={rationalesOpen}>{rationaleRows}</Collapse>
              </Stack>
            ) : (
              rationaleRows
            ))}
        </Stack>
      )}

      {rows.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
          {rows.map((row) => (
            <Paper
              key={row.tag}
              withBorder
              radius="sm"
              p="xs"
              // A component nobody has reported on yet should not draw the
              // eye: only outcomes get contrast.
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
                    icon={TYPE_ICON[row.component_type] ?? UNKNOWN_TYPE_ICON}
                    width={18}
                    color="var(--mantine-color-gray-6)"
                    style={{ marginTop: 2, flexShrink: 0 }}
                  />
                  <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
                    <Text fw={600} size="sm" truncate>
                      {row.tag}
                    </Text>
                    <Text size="xs" c="dimmed" truncate>
                      {row.section}
                    </Text>
                  </Stack>
                  <Outcome row={row} />
                </Group>
                {row.error && (
                  <Text size="xs" c="red" lineClamp={2} title={row.error} style={{ minWidth: 0 }}>
                    {row.error}
                  </Text>
                )}
              </Stack>
            </Paper>
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
};

export default GenerationProgress;
