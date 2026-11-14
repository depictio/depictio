import React from 'react';
import {
  ActionIcon,
  Badge,
  Group,
  Stack,
  Text,
  Timeline,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  changeTone,
  formatMetric,
  metricChange,
  type MetricDirection,
  type ProcessingStep,
} from './steps';

const TONE_COLOURS = { better: 'teal', worse: 'red', neutral: 'dimmed' } as const;

export interface StepHistoryProps {
  steps: readonly ProcessingStep[];
  active: number;
  onPick: (index: number) => void;
  metrics: readonly string[];
  /** Which way each metric improves, to colour its change; others stay grey. */
  better?: Readonly<Record<string, MetricDirection>>;
  playing: boolean;
  onTogglePlay: () => void;
}

function infoLine(step: ProcessingStep): string {
  return Object.values(step.info)
    .filter((v) => v != null && v !== '')
    .map((v) => (typeof v === 'number' ? formatMetric(v) : String(v)))
    .join(' · ');
}

/**
 * What was done to an image, step by step, read-only: each step the tool ran
 * (as the steps table records it), its metrics and their change since the
 * step before, and the parameters of the chosen one. Picking a step shows its
 * output; nothing here runs or tunes anything, that is the tool's job.
 */
const StepHistory: React.FC<StepHistoryProps> = ({
  steps,
  active,
  onPick,
  metrics,
  better,
  playing,
  onTogglePlay,
}) => {
  const current = steps[active];
  return (
    <Stack gap={6} data-testid="bioimage-step-history" data-dock-keep="">
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" fw={600}>
          History · step {active + 1} of {steps.length}
        </Text>
        <Group gap={2} wrap="nowrap">
          <Tooltip label="Previous step" withArrow openDelay={300}>
            <ActionIcon
              size="sm"
              variant="default"
              aria-label="Previous step"
              disabled={active <= 0}
              onClick={() => onPick(active - 1)}
            >
              <Icon icon="tabler:chevron-left" width={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={playing ? 'Pause' : 'Play through the steps'} withArrow openDelay={300}>
            <ActionIcon
              size="sm"
              variant={playing ? 'filled' : 'default'}
              aria-label={playing ? 'Pause' : 'Play'}
              aria-pressed={playing}
              onClick={onTogglePlay}
            >
              <Icon icon={playing ? 'tabler:player-pause' : 'tabler:player-play'} width={12} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Next step" withArrow openDelay={300}>
            <ActionIcon
              size="sm"
              variant="default"
              aria-label="Next step"
              disabled={active >= steps.length - 1}
              onClick={() => onPick(active + 1)}
            >
              <Icon icon="tabler:chevron-right" width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
      <Timeline active={active} bulletSize={14} lineWidth={2}>
        {steps.map((step, i) => {
          const previous = i > 0 ? steps[i - 1] : null;
          const chosen = i === active;
          return (
            <Timeline.Item
              key={`${step.label}-${i}`}
              title={
                <UnstyledButton
                  onClick={() => onPick(i)}
                  aria-current={chosen ? 'step' : undefined}
                  data-testid="bioimage-step-item"
                >
                  <Text size="xs" fw={chosen ? 700 : 500} c={chosen ? undefined : 'dimmed'}>
                    {i + 1}. {step.label}
                  </Text>
                </UnstyledButton>
              }
            >
              {infoLine(step) ? (
                <Text size="xs" c="dimmed" lh={1.3}>
                  {infoLine(step)}
                </Text>
              ) : null}
              {metrics.length ? (
                <Group gap={4} mt={2}>
                  {metrics.map((m) => {
                    const value = step.metrics[m];
                    const change = previous ? metricChange(value, previous.metrics[m]) : null;
                    const tone = changeTone(change, better?.[m]);
                    const arrow = change == null || change === 0 ? '' : change > 0 ? ' ▲' : ' ▼';
                    const tip =
                      change == null
                        ? `${m}: ${formatMetric(value)}`
                        : `${m}: ${formatMetric(value)}, ${change > 0 ? '+' : '−'}${formatMetric(Math.abs(change))} since ${previous?.label}${tone === 'neutral' ? '' : ` (${tone})`}`;
                    return (
                      <Tooltip key={m} label={tip} withArrow openDelay={250}>
                        <Badge
                          size="xs"
                          radius="sm"
                          tt="none"
                          variant="light"
                          color={tone === 'neutral' ? 'gray' : TONE_COLOURS[tone]}
                        >
                          {m} {formatMetric(value)}
                          {arrow}
                        </Badge>
                      </Tooltip>
                    );
                  })}
                </Group>
              ) : null}
            </Timeline.Item>
          );
        })}
      </Timeline>
      {current && current.params.length ? (
        <Stack gap={2} data-testid="bioimage-step-params">
          <Text size="xs" fw={600}>
            Parameters of {current.label}{' '}
            <Text span size="xs" c="dimmed" fw={400}>
              (as run, read-only)
            </Text>
          </Text>
          {/* Name over value: the dock is too narrow for two columns. */}
          {current.params.map(([key, value]) => (
            <div key={key}>
              <Text size="xs" c="dimmed" lh={1.2}>
                {key}
              </Text>
              <Text size="xs" ff="monospace" lh={1.3} style={{ overflowWrap: 'anywhere' }}>
                {value}
              </Text>
            </div>
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
};

export default StepHistory;
