import React from 'react';
import { Badge, Button, Code, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardActions } from '../types';

interface Props {
  actions: DashboardActions;
  /** Called when the user clicks "Apply". The host wires this into its
   *  filter / figure stores; the AI package never mutates dashboard
   *  state directly. */
  onApply?: (actions: DashboardActions) => void;
  onDiscard?: () => void;
  applied?: boolean;
}

/**
 * Renders a `DashboardActions` plan (filter sets + figure mutations) and
 * lets the user apply or discard it. Always read-only by default —
 * nothing happens unless `onApply` is wired in by the host.
 */
const ActionsPreview: React.FC<Props> = ({ actions, onApply, onDiscard, applied }) => {
  const total = actions.filters.length + actions.figure_mutations.length;
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

      {actions.filters.map((f, i) => (
        <Group key={`f${i}`} gap={6} align="flex-start" wrap="nowrap">
          <Badge color="violet" variant="light" size="xs">
            filter
          </Badge>
          <Text size="xs" style={{ flex: 1 }}>
            <Code style={{ fontSize: 11 }}>{f.component_id}</Code> →{' '}
            <Code style={{ fontSize: 11 }}>{JSON.stringify(f.value)}</Code>
            {f.reason ? (
              <>
                {' '}
                <Text size="xs" c="dimmed" component="span">
                  ({f.reason})
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
            onClick={() => onApply(actions)}
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
