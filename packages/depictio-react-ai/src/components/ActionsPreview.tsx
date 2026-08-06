import React from 'react';
import { Badge, Button, Code, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardActions, ResolvedFilter } from '../types';

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
}) => {
  const total = resolved.length + actions.figure_mutations.length;
  if (total === 0) return null;

  return (
    <Stack gap={6} mt={6}>
      <Group gap="xs" align="center">
        <Icon icon="material-symbols:bolt" width={16} />
        <Text size="sm" fw={600}>
          Proposed dashboard actions
        </Text>
        <Badge variant="light" color="gray" size="sm">
          {total}
        </Badge>
      </Group>

      {resolved.map((f, i) => (
        <Group key={`f${i}`} gap={6} align="flex-start" wrap="nowrap">
          <Badge color="violet" variant="light" size="xs">
            {f.kind === 'set_widget' ? 'widget' : 'filter'}
          </Badge>
          <Text size="xs" style={{ flex: 1 }}>
            {f.kind === 'set_widget' ? (
              <>
                <Code style={{ fontSize: 11 }}>{f.component_id}</Code> →{' '}
                <Code style={{ fontSize: 11 }}>{JSON.stringify(f.value)}</Code>
              </>
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

      {onApply && (
        <Group gap="xs" mt={4}>
          <Button
            size="xs"
            variant={applied ? 'light' : 'filled'}
            color={applied ? 'gray' : 'blue'}
            disabled={applied}
            leftSection={<Icon icon="material-symbols:check" width={14} />}
            onClick={() => onApply({ actions, resolved })}
          >
            {applied ? 'Applied' : 'Apply'}
          </Button>
          {onDiscard && !applied && (
            <Button size="xs" variant="subtle" color="gray" onClick={onDiscard}>
              Discard
            </Button>
          )}
        </Group>
      )}
    </Stack>
  );
};

export default ActionsPreview;
