/**
 * What Depictio read in the run folder as soon as one is chosen or typed:
 * the pipeline and version that made the run, and the template it would use
 * with how well that template matches. Loading, an unreadable folder and a
 * folder nobody recognised are states of this card, not separate alerts.
 */
import React from 'react';
import { Button, Group, Loader, Paper, SimpleGrid, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { runTemplateMatchText, splitTemplateId } from 'depictio-react-core';
import type { FolderInspection, RunTemplateMatch } from 'depictio-react-core';

import { RunMadeBy, TemplateUsed } from './RunIdentity';

export type DetectionState =
  | { status: 'idle' }
  | { status: 'loading'; location: string }
  | { status: 'error'; location: string; error: string }
  | { status: 'ready'; location: string; result: FolderInspection };

interface DetectionCardProps {
  state: DetectionState;
  /** The template the project would use: the one chosen, else the one
   *  detected. */
  templateId: string | null;
  templateTitle: string | null;
  match: RunTemplateMatch | null;
  /** Offered when a template other than the detected one is chosen. */
  onUseDetected?: () => void;
}

const Line: React.FC<{ icon: string; color: string; children: React.ReactNode }> = ({
  icon,
  color,
  children,
}) => (
  <Group gap="sm" wrap="nowrap" align="flex-start">
    <ThemeIcon variant="light" color={color} size="md" radius="md">
      <Icon icon={icon} width={16} />
    </ThemeIcon>
    <Stack gap={2} style={{ minWidth: 0 }}>
      {children}
    </Stack>
  </Group>
);

export const DetectionCard: React.FC<DetectionCardProps> = ({
  state,
  templateId,
  templateTitle,
  match,
  onUseDetected,
}) => {
  if (state.status === 'idle') return null;

  let body: React.ReactNode;
  if (state.status === 'loading') {
    body = (
      <Group gap="sm" wrap="nowrap">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">
          Reading the folder to recognise the pipeline...
        </Text>
      </Group>
    );
  } else if (state.status === 'error') {
    body = (
      <Line icon="mdi:folder-alert-outline" color="yellow">
        <Text size="sm" fw={600}>
          This folder could not be read
        </Text>
        <Text size="sm" c="dimmed" data-testid="run-detection-error">
          {state.error}
        </Text>
        <Text size="xs" c="dimmed">
          You can still pick the pipeline below and preview the folder.
        </Text>
      </Line>
    );
  } else {
    const { result } = state;
    const detected = result.detected;
    if (!detected?.pipeline) {
      body = (
        <Line icon="mdi:folder-question-outline" color="gray">
          <Text size="sm" fw={600}>
            No pipeline recognised in this folder
          </Text>
          <Text size="sm" c="dimmed">
            {result.looks_like_run
              ? 'The folder holds run records, but none of them names a pipeline Depictio knows. Pick the pipeline below.'
              : 'The folder holds no pipeline_info or multiqc folder, so it does not look like the output of a run. Check the folder, or pick the pipeline below.'}
          </Text>
        </Line>
      );
    } else {
      const detectedId = detected.template_id;
      const usedId = templateId ?? detectedId;
      const usedVersion = usedId ? splitTemplateId(usedId).version : null;
      const text =
        match && match !== 'exact'
          ? runTemplateMatchText(match, { run: detected.version, template: usedVersion })
          : null;
      body = (
        <Stack gap="sm">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" verticalSpacing="sm">
            <RunMadeBy
              run={{ pipeline: detected.pipeline, version: detected.version, engine: detected.engine }}
              testIdPrefix="run-detected"
            />
            <TemplateUsed
              templateId={usedId}
              title={templateTitle}
              match={match}
              runVersion={detected.version}
              testIdPrefix="run-detected"
            />
          </SimpleGrid>
          {text && (
            <Text size="xs" c="dimmed" data-testid="run-detection-match-detail">
              {text.detail}
            </Text>
          )}
          {onUseDetected && detectedId && templateId && templateId !== detectedId && (
            <Group>
              <Button
                size="xs"
                variant="light"
                leftSection={<Icon icon="mdi:auto-fix" width={14} />}
                onClick={onUseDetected}
                data-testid="run-use-detected"
              >
                Use the detected template
              </Button>
            </Group>
          )}
        </Stack>
      );
    }
  }

  return (
    <Paper
      withBorder
      radius="md"
      p="md"
      data-testid="run-detection-card"
      data-state={state.status}
      aria-live="polite"
    >
      {body}
    </Paper>
  );
};
