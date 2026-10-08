/**
 * Vertical timeline of an ingestion run's steps.
 *
 * Replaces the flat table that used to render them. The table was adequate when
 * steps only appeared after a run finished; now that the CLI reports each step
 * as it starts, the view has to answer "where is it right now" at a glance,
 * which is what a timeline with an active marker does and a table does not.
 */

import React from 'react';
import { Alert, Badge, Group, Loader, Progress, Stack, Text, Timeline, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { MonitoringIngestionStep } from 'depictio-react-core';

import { compactCount, formatDuration } from './format';
import { statusColor } from './tokens';

/** Human labels for the counter keys the CLI emits. Unknown keys fall back to
 *  their raw name with underscores stripped, so a new counter shows up
 *  immediately instead of being silently dropped. */
const COUNTER_LABELS: Record<string, string> = {
  files_scanned: 'scanned',
  files_new: 'new',
  files_updated: 'updated',
  files_unchanged: 'unchanged',
  files_skipped: 'skipped',
  files_failed: 'failed',
  files_deleted: 'deleted',
  rows_written: 'rows',
  bytes_written: 'bytes',
  runs_scanned: 'runs',
};

/** Counters worth colouring: a non-zero failure count should read as a problem
 *  even before anyone expands the step. */
const COUNTER_COLORS: Record<string, string> = {
  files_failed: 'red',
  files_new: 'green',
  files_updated: 'blue',
  files_deleted: 'orange',
};

function stepIcon(status: string): string {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'mdi:check-circle';
    case 'failed':
    case 'failure':
      return 'mdi:alert-circle';
    case 'skipped':
      return 'mdi:minus-circle';
    case 'partial':
      return 'mdi:alert';
    default:
      return 'mdi:circle-outline';
  }
}

const CounterChips: React.FC<{ counters?: Record<string, number> | null }> = ({ counters }) => {
  if (!counters) return null;
  const entries = Object.entries(counters).filter(([, v]) => v != null);
  if (entries.length === 0) return null;
  return (
    <Group gap={4}>
      {entries.map(([key, value]) => (
        <Badge
          key={key}
          size="xs"
          variant="light"
          color={COUNTER_COLORS[key] ?? 'gray'}
        >
          {compactCount(value)} {COUNTER_LABELS[key] ?? key.replace(/_/g, ' ')}
        </Badge>
      ))}
    </Group>
  );
};

export const IngestionStepTimeline: React.FC<{
  steps?: MonitoringIngestionStep[];
  currentStep?: string | null;
}> = ({ steps, currentStep }) => {
  if (!steps || steps.length === 0) {
    return (
      <Text size="xs" c="dimmed">
        No steps recorded.
      </Text>
    );
  }

  // Steps arrive keyed by name and may be upserted out of order; sort by the
  // explicit index when the CLI supplies one, else keep arrival order.
  const ordered = [...steps].sort((a, b) => {
    if (a.index != null && b.index != null) return a.index - b.index;
    return 0;
  });

  const activeIndex = currentStep
    ? ordered.findIndex((s) => s.name === currentStep)
    : ordered.reduce(
        (last, s, i) => (['success', 'failed', 'skipped', 'partial'].includes(s.status) ? i : last),
        -1,
      );

  return (
    <Timeline active={activeIndex} bulletSize={18} lineWidth={2}>
      {ordered.map((step) => {
        const isCurrent = currentStep != null && step.name === currentStep;
        const color = isCurrent ? 'yellow' : statusColor(step.status);
        return (
          <Timeline.Item
            key={step.name}
            color={color}
            bullet={
              isCurrent ? (
                <Loader size={10} color="yellow" />
              ) : (
                <Icon icon={stepIcon(step.status)} width={12} />
              )
            }
            title={
              <Group gap={6} wrap="nowrap">
                <Text size="xs" fw={isCurrent ? 700 : 500}>
                  {step.name}
                </Text>
                {step.data_collection_tag && (
                  <Badge size="xs" variant="outline" color="gray">
                    {step.data_collection_tag}
                  </Badge>
                )}
                {step.duration_ms != null && (
                  <Text size="10px" c="dimmed">
                    {formatDuration(step.duration_ms)}
                  </Text>
                )}
                {step.job_id && (
                  <Tooltip label={`Offloaded as job ${step.job_id}`} withArrow>
                    <Badge size="xs" variant="light" color="cyan">
                      offloaded
                    </Badge>
                  </Tooltip>
                )}
              </Group>
            }
          >
            <Stack gap={4}>
              {step.detail && (
                <Text size="xs" c="dimmed">
                  {step.detail}
                </Text>
              )}
              {/* Only a real fraction gets a bar. Anything else would be a
                  progress indicator that lies about how far along it is. */}
              {step.progress?.percent != null && (
                <Progress
                  value={step.progress.percent}
                  size="xs"
                  color={color}
                  aria-label={`${step.name} progress`}
                />
              )}
              {step.progress?.percent == null && step.progress?.total != null && (
                <Text size="10px" c="dimmed">
                  {step.progress.current ?? 0} / {step.progress.total}
                  {step.progress.unit ? ` ${step.progress.unit}` : ''}
                </Text>
              )}
              <CounterChips counters={step.counters} />
              {step.error && (
                <Alert color="red" variant="light" p="xs">
                  <Text size="xs">{step.error}</Text>
                </Alert>
              )}
            </Stack>
          </Timeline.Item>
        );
      })}
    </Timeline>
  );
};
