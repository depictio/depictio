import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Badge,
  Code,
  Collapse,
  Group,
  Stack,
  Text,
  SegmentedControl,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { AI_COLOR, aiColorVar } from '../icons';

import { formatPolarsCode } from '../formatPolars';
import type { ExecutionStep } from '../types';

/** A labeled code block that folds — long Polars chains and row dumps
 *  shouldn't monopolize the panel once the reader has seen them. */
const FoldableCode: React.FC<{
  label: string;
  color: string;
  content: string;
  defaultOpen?: boolean;
}> = ({ label, color, content, defaultOpen = true }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Stack gap={4}>
      <UnstyledButton onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <Group gap={4} wrap="nowrap">
          <Badge size="xs" variant="light" color={color}>
            {label}
          </Badge>
          <Icon
            icon={open ? 'material-symbols:keyboard-arrow-up' : 'material-symbols:keyboard-arrow-down'}
            width={14}
            style={{ color: 'var(--mantine-color-dimmed)' }}
          />
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Code
          block
          color={color === 'red' ? 'red' : undefined}
          style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}
        >
          {content}
        </Code>
      </Collapse>
    </Stack>
  );
};

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
  running: 'mdi:loading',
};

type Filter = 'all' | 'code' | 'errors';

/** "1,203 → 47" — the cardinality trail. A filter that silently kept
 *  everything and one that silently kept nothing read identically in the
 *  narrative; they cannot hide in this column. */
function cardinality(step: ExecutionStep): string | null {
  if (step.rows_in == null) return null;
  const rin = step.rows_in.toLocaleString();
  return step.rows_out != null ? `${rin} → ${step.rows_out.toLocaleString()}` : rin;
}

/**
 * Collapsible per-step trace borrowed from the LiteLLM prototype's
 * `render_execution_trace`. Each step surfaces the LLM's thought, the
 * Polars expression that ran (if any), and the truncated output.
 */
const ExecutionTrace: React.FC<Props> = ({ steps, defaultOpen = false }) => {
  const [filter, setFilter] = useState<Filter>('all');
  // Controlled so failed steps pop open as they stream in — an error the
  // user has to hunt for behind a collapsed accordion is an invisible
  // error. Keys index into `steps`, not the filtered view, so they stay
  // stable when the filter changes.
  const [opened, setOpened] = useState<string[]>(
    defaultOpen ? steps.map((_, i) => `s${i}`) : [],
  );
  useEffect(() => {
    const errKeys = steps
      .map((s, i) => (s.status === 'error' ? `s${i}` : null))
      .filter((k): k is string => k !== null);
    if (errKeys.length === 0) return;
    setOpened((prev) => {
      const missing = errKeys.filter((k) => !prev.includes(k));
      return missing.length ? [...prev, ...missing] : prev;
    });
  }, [steps]);

  const counts = useMemo(() => {
    const c = { success: 0, warning: 0, error: 0, running: 0 };
    for (const s of steps) c[s.status as keyof typeof c] = (c[s.status as keyof typeof c] ?? 0) + 1;
    return c;
  }, [steps]);

  const visible = useMemo(() => {
    const indexed = steps.map((step, index) => ({ step, index }));
    if (filter === 'errors') return indexed.filter(({ step }) => step.status === 'error');
    if (filter === 'code') return indexed.filter(({ step }) => step.code.trim().length > 0);
    return indexed;
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
        value={opened}
        onChange={setOpened}
        variant="separated"
        styles={{ control: { paddingTop: 6, paddingBottom: 6 } }}
      >
        {visible.map(({ step, index }) => {
          const color = STATUS_COLOR[step.status] ?? 'gray';
          const icon = STATUS_ICON[step.status] ?? 'material-symbols:help-outline';
          return (
            <Accordion.Item key={`s${index}`} value={`s${index}`}>
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  <Icon icon={icon} width={16} color={`var(--mantine-color-${color}-6)`} />
                  <Text size="sm" lineClamp={1} flex={1}>
                    {step.thought || (step.code ? 'Compute' : 'Step')}
                  </Text>
                  {step.dc_tag && (
                    <Badge size="xs" variant="outline" color="gray">
                      {step.dc_tag}
                    </Badge>
                  )}
                  {cardinality(step) && (
                    <Badge size="xs" variant="light" color="gray">
                      {cardinality(step)}
                    </Badge>
                  )}
                  {step.seconds != null && step.seconds > 0 && (
                    <Text size="xs" c="dimmed">
                      {step.seconds.toFixed(1)}s
                    </Text>
                  )}
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
                    <FoldableCode
                      label="Polars"
                      color={AI_COLOR}
                      content={formatPolarsCode(step.code)}
                    />
                  )}
                  {step.output && (
                    <FoldableCode
                      label={step.status === 'error' ? 'Error' : 'Output'}
                      color={step.status === 'error' ? 'red' : 'gray'}
                      content={step.output}
                    />
                  )}
                  {!step.output && step.status === 'error' && (
                    <Text size="xs" c="red">
                      Step failed but returned no error output.
                    </Text>
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
