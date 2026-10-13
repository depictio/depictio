/**
 * What Depictio read in the run folder as soon as one is chosen or typed:
 * the checks of the run against the template it would use (the run's
 * records, the files the template is pointed at, what it finds), each one
 * line, the collections one click away. Loading, an unreadable folder and a
 * folder nobody recognised are states of this card, not separate alerts.
 */
import React from 'react';
import { Button, Group, Loader, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { FolderInspection, RunStorageIn, RunTemplateMatch } from 'depictio-react-core';

import { RunChecks } from './RunChecks';
import { useRunPlan } from './runPlan';

export type DetectionState =
  | { status: 'idle' }
  | { status: 'loading'; location: string }
  /** `code` is the server's reason (`s3_access_denied`, ...), when it sent one. */
  | { status: 'error'; location: string; error: string; code?: string | null }
  | { status: 'ready'; location: string; result: FolderInspection };

interface DetectionCardProps {
  state: DetectionState;
  /** The template the project would use: the one chosen, else the one
   *  detected. */
  templateId: string | null;
  templateTitle: string | null;
  /** The engine the template was written for, when the catalog says. */
  templateEngine?: string | null;
  match: RunTemplateMatch | null;
  /** The private bucket's connection details, for a folder in one. */
  storage?: RunStorageIn | null;
  /** Offered when a template other than the detected one is chosen. */
  onUseDetected?: () => void;
  /** What to do about an unreadable folder, when the tab knows better than
   *  "pick the pipeline" (a private bucket). */
  errorHint?: string | null;
  /** Said instead of the server's reason, when that reason speaks of
   *  settings the reader cannot see yet (a project not created). */
  errorMessage?: string | null;
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

/** The checks of a recognised folder, its dry run asked for as soon as a
 *  template is known. */
const DetectedChecks: React.FC<{
  result: FolderInspection;
  templateId: string | null;
  templateTitle: string | null;
  templateEngine: string | null;
  match: RunTemplateMatch | null;
  storage: RunStorageIn | null;
}> = ({ result, templateId, templateTitle, templateEngine, match, storage }) => {
  const plan = useRunPlan(result.location, templateId, storage);
  return (
    <RunChecks
      location={result.location}
      run={result.detected}
      templateId={templateId}
      templateName={templateTitle}
      templateEngine={templateEngine}
      match={match}
      plan={plan}
      runInfo={result.run_info ?? null}
      listingCut={result.truncated}
      storage={storage}
      testIdPrefix="run-detected"
    />
  );
};

export const DetectionCard: React.FC<DetectionCardProps> = ({
  state,
  templateId,
  templateTitle,
  templateEngine = null,
  match,
  storage = null,
  onUseDetected,
  errorHint,
  errorMessage,
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
          {errorMessage || state.error}
        </Text>
        <Text size="xs" c="dimmed" data-testid="run-detection-error-hint">
          {errorHint || 'You can still pick the pipeline below and preview the folder.'}
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
              ? 'The folder has a pipeline_info folder or a MultiQC report, but neither names a pipeline Depictio has a template for. Pick the pipeline below.'
              : 'The folder holds no pipeline_info folder or MultiQC report, so it does not look like the output of a run. Check the folder, or pick the pipeline below.'}
          </Text>
        </Line>
      );
    } else {
      const detectedId = detected.template_id;
      body = (
        <Stack gap="sm">
          <DetectedChecks
            result={result}
            templateId={templateId ?? detectedId}
            templateTitle={templateTitle}
            templateEngine={templateEngine}
            match={match}
            storage={storage}
          />
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
