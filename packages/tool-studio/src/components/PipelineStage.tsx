/**
 * One stage of the recipe pipeline on the Fixture step:
 * raw sample(s) → recipe → fixture.
 *
 * Each stage carries its own state, drawn like the wizard's stepper so the two
 * read as one system: a grey outlined number and a dashed card while there is
 * something to do, the Studio's tone (violet) with a check once done, red on
 * error. Only the number and the status badge carry the colour; the card keeps
 * the page's hairline, so a finished pipeline does not turn into a stack of
 * coloured frames. The footer line says what happens to the stage's content on export
 * (stays in the browser, or which file it becomes), which is the distinction
 * the three stages exist to make.
 */
import type { ReactNode } from 'react';
import { Badge, Box, Group, Paper, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import { STUDIO_TONE } from '../theme';

export type StageStatus = 'empty' | 'ready' | 'running' | 'error';

const STATUS: Record<StageStatus, { color: string; label: string; icon: string }> = {
  empty: { color: 'gray', label: 'to do', icon: 'mdi:circle-outline' },
  ready: { color: STUDIO_TONE, label: 'done', icon: 'mdi:check-circle' },
  running: { color: STUDIO_TONE, label: 'running', icon: 'mdi:progress-clock' },
  error: { color: 'red', label: 'error', icon: 'mdi:alert-circle' },
};

export function PipelineArrow() {
  return (
    <Group justify="center" my={-6} aria-hidden>
      <Icon icon="mdi:arrow-down" width={20} color="var(--mantine-color-dimmed)" />
    </Group>
  );
}

export default function PipelineStage({
  index,
  title,
  status,
  statusText,
  exportNote,
  aside,
  children,
  testId,
}: {
  index: number;
  title: string;
  status: StageStatus;
  /** Overrides the default status label ("done", "to do"…), e.g. "103 rows · 11 cols". */
  statusText?: string;
  /** What this stage becomes on export, e.g. "stays in your browser". */
  exportNote?: ReactNode;
  /** Right-aligned content on the title row. */
  aside?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  const s = STATUS[status];
  return (
    <Paper
      withBorder
      radius="md"
      p="md"
      data-testid={testId}
      data-status={status}
      style={{
        borderStyle: status === 'empty' ? 'dashed' : 'solid',
        borderColor: status === 'error' ? 'var(--mantine-color-red-6)' : undefined,
      }}
    >
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="center">
          <Group gap="sm" wrap="nowrap">
            {/* The stepper's step circle: outlined number to do, filled check done. */}
            <ThemeIcon
              radius="xl"
              size={28}
              color={s.color}
              variant={status === 'empty' ? 'outline' : 'filled'}
              aria-label={`Stage ${index}`}
            >
              {status === 'ready' ? (
                <Icon icon="mdi:check" width={16} />
              ) : (
                <Text size="xs" fw={700} c="inherit">
                  {index}
                </Text>
              )}
            </ThemeIcon>
            <Title order={2} size="h5">
              {title}
            </Title>
            <Badge
              size="sm"
              variant="light"
              color={s.color}
              leftSection={<Icon icon={s.icon} width={12} />}
            >
              {statusText ?? s.label}
            </Badge>
          </Group>
          {aside && <Box style={{ flexShrink: 0 }}>{aside}</Box>}
        </Group>
        {children}
        {exportNote && (
          <Group gap={6} wrap="nowrap">
            <Icon icon="mdi:export-variant" width={14} color="var(--mantine-color-dimmed)" />
            <Text size="xs" c="dimmed">
              {exportNote}
            </Text>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
