import React from 'react';
import {
  ActionIcon,
  Group,
  Stack,
  Text,
  ThemeIcon,
  Timeline,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  changeTone,
  formatMetric,
  metricChange,
  stepIcon,
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

/** One metric of a step: its value, an arrow for its change since the step
 *  before, coloured by whether that is better; the change in a tooltip. */
const Metric: React.FC<{
  name: string;
  step: ProcessingStep;
  previous: ProcessingStep | null;
  better?: MetricDirection;
}> = ({ name, step, previous, better }) => {
  const value = step.metrics[name];
  const change = previous ? metricChange(value, previous.metrics[name]) : null;
  const tone = changeTone(change, better);
  const arrow = change == null || change === 0 ? '' : change > 0 ? '▲' : '▼';
  const tip =
    change == null
      ? `${name}: ${formatMetric(value)}`
      : `${name}: ${formatMetric(value)}, ${change > 0 ? '+' : '−'}${formatMetric(Math.abs(change))} since ${previous?.label}${tone === 'neutral' ? '' : ` (${tone})`}`;
  return (
    <Tooltip label={tip} withArrow openDelay={250}>
      <Text span fz={11} c={TONE_COLOURS[tone]} style={{ whiteSpace: 'nowrap' }}>
        {name} {formatMetric(value)}
        {arrow ? ` ${arrow}` : ''}
      </Text>
    </Tooltip>
  );
};

/**
 * What was done to an image, step by step, read-only. One line per step: an
 * icon for its kind, its name and its first metric. The chosen step unfolds:
 * the tool that ran it, all its metrics and the parameters it ran with.
 * Picking a step shows its output; nothing here runs or tunes anything, that
 * is the tool's job.
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
  const lead = metrics[0];
  return (
    // `data-dock-keep`: only buttons here, which the dock would otherwise fold.
    <Stack gap={6} data-testid="bioimage-step-history" data-dock-keep="">
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed">
          Step {active + 1} of {steps.length}
        </Text>
        <Group gap={2} wrap="nowrap">
          <Tooltip label="Previous step" withArrow openDelay={300}>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
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
              variant={playing ? 'light' : 'subtle'}
              color={playing ? undefined : 'gray'}
              aria-label={playing ? 'Pause' : 'Play'}
              aria-pressed={playing}
              onClick={onTogglePlay}
            >
              <Icon icon={playing ? 'tabler:player-pause' : 'tabler:player-play'} width={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Next step" withArrow openDelay={300}>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              aria-label="Next step"
              disabled={active >= steps.length - 1}
              onClick={() => onPick(active + 1)}
            >
              <Icon icon="tabler:chevron-right" width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
      <Timeline
        active={active}
        bulletSize={20}
        lineWidth={2}
        // The bullet is the step's own light icon, not Mantine's filled dot.
        styles={{
          item: { marginTop: 6 },
          itemTitle: { marginBottom: 0 },
          itemBullet: { backgroundColor: 'transparent', border: 'none' },
        }}
      >
        {steps.map((step, i) => {
          const previous = i > 0 ? steps[i - 1] : null;
          const chosen = i === active;
          const info = infoLine(step);
          return (
            <Timeline.Item
              key={`${step.label}-${i}`}
              bullet={
                <ThemeIcon
                  size={20}
                  radius="xl"
                  variant={chosen ? 'filled' : 'light'}
                  color={i <= active ? undefined : 'gray'}
                >
                  <Icon icon={stepIcon(step.label)} width={12} height={12} />
                </ThemeIcon>
              }
              title={
                <UnstyledButton
                  w="100%"
                  onClick={() => onPick(i)}
                  aria-current={chosen ? 'step' : undefined}
                  data-testid="bioimage-step-item"
                >
                  <Group gap={6} wrap="nowrap" justify="space-between">
                    <Text size="xs" fw={chosen ? 700 : 500} c={chosen ? undefined : 'dimmed'} truncate>
                      {step.label}
                    </Text>
                    {lead && !chosen ? (
                      <Metric name={lead} step={step} previous={previous} better={better?.[lead]} />
                    ) : null}
                  </Group>
                </UnstyledButton>
              }
            >
              {chosen ? (
                <Stack gap={4} mt={2}>
                  {info ? (
                    <Text fz={11} c="dimmed" lh={1.3}>
                      {info}
                    </Text>
                  ) : null}
                  {metrics.length ? (
                    <Group gap={8} wrap="wrap">
                      {metrics.map((m) => (
                        <Metric key={m} name={m} step={step} previous={previous} better={better?.[m]} />
                      ))}
                    </Group>
                  ) : null}
                  {step.params.length ? (
                    <Stack gap={2} data-testid="bioimage-step-params">
                      <Text fz={11} fw={600}>
                        Parameters{' '}
                        <Text span fz={11} c="dimmed" fw={400}>
                          (as run)
                        </Text>
                      </Text>
                      {/* Name over value: the dock is too narrow for two columns. */}
                      {step.params.map(([key, value]) => (
                        <div key={key}>
                          <Text fz={10} c="dimmed" lh={1.2}>
                            {key}
                          </Text>
                          <Text fz={11} ff="monospace" lh={1.3} style={{ overflowWrap: 'anywhere' }}>
                            {value}
                          </Text>
                        </div>
                      ))}
                    </Stack>
                  ) : null}
                </Stack>
              ) : null}
            </Timeline.Item>
          );
        })}
      </Timeline>
    </Stack>
  );
};

export default StepHistory;
