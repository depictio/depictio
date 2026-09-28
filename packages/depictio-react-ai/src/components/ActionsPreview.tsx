import React from 'react';
import { Badge, Button, Code, Group, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardActions, ResolvedFilter } from '../types';

/** "4450 – 6300" for a numeric pair, "Adelie, Dream" for lists, plain
 *  string otherwise — JSON.stringify noise belongs in the tooltip era. */
function formatWidgetValue(value: unknown): string {
  if (Array.isArray(value)) {
    if (value.length === 2 && value.every((v) => typeof v === 'number')) {
      return `${value[0]} – ${value[1]}`;
    }
    return value.map(String).join(', ');
  }
  if (value == null) return '(cleared)';
  return String(value);
}

/** What the host receives on "Apply": server-resolved filters (safe to
 *  inject) plus the raw actions for figure mutations. */
export interface ApplyActionsPayload {
  actions: DashboardActions;
  resolved: ResolvedFilter[];
}

interface Props {
  actions: DashboardActions;
  /** Server-validated filters (from AnalysisResult.resolved_filters or a
   *  resolve-filters response). Only these — never raw proposals — get
   *  applied client-side. */
  resolved?: ResolvedFilter[];
  /** Called when the user clicks "Apply". The host wires this into its
   *  filter / figure stores; the AI package never mutates dashboard
   *  state directly. */
  onApply?: (payload: ApplyActionsPayload) => void;
  onDiscard?: () => void;
  applied?: boolean;
  /** Optional tooltip for the Apply button (e.g. "replaces the current plan"). */
  applyTooltip?: string;
}

/**
 * Renders the proposed plan (resolved filters + figure mutations) and
 * lets the user apply or discard it. Always read-only by default —
 * nothing happens unless `onApply` is wired in by the host.
 */
const ActionsPreview: React.FC<Props> = ({
  actions,
  resolved = [],
  onApply,
  onDiscard,
  applied,
  applyTooltip,
}) => {
  const total = resolved.length + actions.figure_mutations.length;
  if (total === 0) return null;

  // Same component, same size in both states — only color and
  // interactivity change. `pointerEvents: none` instead of `disabled`
  // keeps the teal tint (Mantine greys out disabled buttons).
  const applyButton = onApply && (
    <Button
      size="xs"
      variant={applied ? 'light' : 'filled'}
      color={applied ? 'teal' : 'violet'}
      style={applied ? { pointerEvents: 'none' } : undefined}
      leftSection={<Icon icon="material-symbols:check" width={14} />}
      onClick={() => onApply({ actions, resolved })}
    >
      {applied ? 'Applied' : 'Apply'}
    </Button>
  );

  return (
    // The plan and its Apply live in one bordered box — the action sits
    // next to the list it acts on instead of floating elsewhere in the
    // exchange.
    <Paper
      withBorder
      radius="sm"
      p="xs"
      mt={6}
      style={{ borderColor: 'var(--mantine-color-violet-3)' }}
    >
    <Stack gap={6}>
      <Group gap="xs" align="center" wrap="nowrap">
        <Icon icon="material-symbols:bolt" width={16} />
        <Text size="sm" fw={600}>
          Proposed dashboard actions
        </Text>
        <Badge variant="light" color="gray" size="sm">
          {total}
        </Badge>
        {applyButton && (
          <Group gap="xs" ml="auto" wrap="nowrap">
            {onDiscard && !applied && (
              <Button size="xs" variant="subtle" color="gray" onClick={onDiscard}>
                Discard
              </Button>
            )}
            {applyTooltip && !applied ? (
              <Tooltip label={applyTooltip}>{applyButton}</Tooltip>
            ) : (
              applyButton
            )}
          </Group>
        )}
      </Group>

      {resolved.map((f, i) => (
        <Group key={`f${i}`} gap={6} align="flex-start" wrap="nowrap">
          {/* Both kinds narrow the data — "filter" is the user-facing
              category. Whether it lands as a moved control (set_widget) or
              an injected expression is plumbing, not meaning. */}
          <Badge color="violet" variant="light" size="xs">
            filter
          </Badge>
          <Text size="xs" style={{ flex: 1 }}>
            {f.kind === 'set_widget' ? (
              // The row reads "column → value"; the raw component id only
              // matters when debugging, so it lives in the tooltip.
              <Tooltip label={`component ${f.component_id}`} withArrow>
                <span>
                  <Text size="xs" fw={600} component="span">
                    {f.label || f.component_id}
                  </Text>{' '}
                  → <Code style={{ fontSize: 11 }}>{formatWidgetValue(f.value)}</Code>
                </span>
              </Tooltip>
            ) : (
              <Code style={{ fontSize: 11 }}>{f.filter_expr}</Code>
            )}
            {f.description ? (
              <>
                {' '}
                <Text size="xs" c="dimmed" component="span">
                  ({f.description})
                </Text>
              </>
            ) : null}
          </Text>
        </Group>
      ))}

      {actions.figure_mutations.map((m, i) => (
        <Group key={`m${i}`} gap={6} align="flex-start" wrap="nowrap">
          <Badge color="cyan" variant="light" size="xs">
            figure
          </Badge>
          <Text size="xs" style={{ flex: 1 }}>
            <Code style={{ fontSize: 11 }}>{m.component_id}</Code> patch{' '}
            <Code style={{ fontSize: 11 }}>{JSON.stringify(m.dict_kwargs_patch)}</Code>
            {m.reason ? (
              <>
                {' '}
                <Text size="xs" c="dimmed" component="span">
                  ({m.reason})
                </Text>
              </>
            ) : null}
          </Text>
        </Group>
      ))}

    </Stack>
    </Paper>
  );
};

export default ActionsPreview;
