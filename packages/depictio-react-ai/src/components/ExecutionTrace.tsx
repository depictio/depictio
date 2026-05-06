import React, { useMemo, useState } from 'react';
import {
  Accordion,
  Badge,
  Code,
  Group,
  Stack,
  Text,
  SegmentedControl,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ExecutionStep } from '../types';

interface Props {
  steps: ExecutionStep[];
  /** Default open state for newly added steps (defaults to false). */
  defaultOpen?: boolean;
}

const STATUS_COLOR: Record<string, string> = {
  success: 'teal',
  warning: 'yellow',
  error: 'red',
  running: 'blue',
};

const STATUS_ICON: Record<string, string> = {
  success: 'material-symbols:check-circle-outline',
  warning: 'material-symbols:warning-outline',
  error: 'material-symbols:error-outline',
  running: 'svg-spinners:90-ring',
};

type Filter = 'all' | 'code' | 'errors';

/**
 * Collapsible per-step trace borrowed from the LiteLLM prototype's
 * `render_execution_trace`. Each step surfaces the LLM's thought, the
 * Polars expression that ran (if any), and the truncated output.
 */
const ExecutionTrace: React.FC<Props> = ({ steps, defaultOpen = false }) => {
  const [filter, setFilter] = useState<Filter>('all');

  const counts = useMemo(() => {
    const c = { success: 0, warning: 0, error: 0, running: 0 };
    for (const s of steps) c[s.status as keyof typeof c] = (c[s.status as keyof typeof c] ?? 0) + 1;
    return c;
  }, [steps]);

  const visible = useMemo(() => {
    if (filter === 'errors') return steps.filter((s) => s.status === 'error');
    if (filter === 'code') return steps.filter((s) => s.code.trim().length > 0);
    return steps;
  }, [steps, filter]);

  if (steps.length === 0) return null;

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap" align="center">
        <Badge variant="light" color="gray">
          {steps.length} {steps.length === 1 ? 'step' : 'steps'}
        </Badge>
        {counts.success > 0 && (
          <Badge variant="light" color="teal">
            {counts.success} ok
          </Badge>
        )}
        {counts.warning > 0 && (
          <Badge variant="light" color="yellow">
            {counts.warning} warn
          </Badge>
        )}
        {counts.error > 0 && (
          <Badge variant="light" color="red">
            {counts.error} err
          </Badge>
        )}
        <SegmentedControl
          ml="auto"
          size="xs"
          data={[
            { value: 'all', label: 'All' },
            { value: 'code', label: 'Code' },
            { value: 'errors', label: 'Errors' },
          ]}
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
        />
      </Group>

      <Accordion
        multiple
        defaultValue={defaultOpen ? steps.map((_, i) => `s${i}`) : []}
        variant="separated"
        styles={{ control: { paddingTop: 6, paddingBottom: 6 } }}
      >
        {visible.map((step, i) => {
          const color = STATUS_COLOR[step.status] ?? 'gray';
          const icon = STATUS_ICON[step.status] ?? 'material-symbols:help-outline';
          return (
            <Accordion.Item key={`s${i}`} value={`s${i}`}>
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  <Icon icon={icon} width={16} color={`var(--mantine-color-${color}-6)`} />
                  <Text size="sm" lineClamp={1} flex={1}>
                    {step.thought || (step.code ? 'Compute' : 'Step')}
                  </Text>
                  <Badge size="xs" variant="light" color={color}>
                    {step.status}
                  </Badge>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="xs">
                  {step.thought && (
                    <Text size="xs" c="dimmed" fs="italic">
                      {step.thought}
                    </Text>
                  )}
                  {step.code && (
                    <Code block style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
                      {step.code}
                    </Code>
                  )}
                  {step.output && (
                    <Code
                      block
                      color={step.status === 'error' ? 'red' : undefined}
                      style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}
                    >
                      {step.output}
                    </Code>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
    </Stack>
  );
};

export default ExecutionTrace;
