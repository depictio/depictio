/**
 * The Preview and Create steps of the run tab. Both only show what the tab
 * holds: the dry-run plan and the ways it can fail, then the plan's header
 * and what Create will do. The state, and the request behind it, stay in
 * `RunFolderTab`.
 */
import React from 'react';
import { Alert, Box, Button, Center, Group, Loader, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { runCollectionTotals, useBrandAccents } from 'depictio-react-core';
import type { DetectedTemplate, FromRunReport } from 'depictio-react-core';

import { plural } from './plural';
import { RunPreview, RunSummaryCard } from './RunPreview';

/** The preview's answer when no template was picked and the server could not
 *  tell which pipeline produced the folder: say so, and send the reader back
 *  to pick one. `message` is the server's own explanation. */
const TemplateNotDetectedAlert: React.FC<{
  message: string;
  onPickTemplate: () => void;
}> = ({ message, onPickTemplate }) => (
  <Alert
    color="yellow"
    variant="light"
    icon={<Icon icon="mdi:help-circle-outline" width={18} />}
    title="Pipeline not recognised, pick one"
    data-testid="run-template-not-detected"
  >
    <Stack gap="xs">
      <Text size="sm">{message}</Text>
      <Text size="sm">
        Choose the pipeline that produced this folder and its template version, then
        preview again.
      </Text>
      <Group>
        <Button
          size="xs"
          variant="light"
          color="yellow"
          leftSection={<Icon icon="mdi:arrow-left" width={14} />}
          onClick={onPickTemplate}
          data-testid="run-pick-template"
        >
          Pick a pipeline
        </Button>
      </Group>
    </Stack>
  </Alert>
);

interface RunPreviewStepProps {
  loading: boolean;
  /** No template is chosen: the server recognises the pipeline itself. */
  detecting: boolean;
  /** The server's explanation when it recognised no pipeline. */
  notDetected: string | null;
  /** Back to the Source step, to pick a template. */
  onPickTemplate: () => void;
  error: string | null;
  /** Offered beside `error` when the read was refused for want of the
   *  bucket's connection details; null when not. */
  onGiveBucketDetails: (() => void) | null;
  /** Nothing in the plan matched the folder. */
  foundNothing: boolean;
  report: FromRunReport | null;
  templateTitle: string | null;
  detection: DetectedTemplate | null;
}

export const RunPreviewStep: React.FC<RunPreviewStepProps> = ({
  loading,
  detecting,
  notDetected,
  onPickTemplate,
  error,
  onGiveBucketDetails,
  foundNothing,
  report,
  templateTitle,
  detection,
}) => {
  const accent = useBrandAccents();
  return (
    <Stack gap="md" pt="md">
      <Box aria-live="polite" role="status">
        {loading && (
          <Center mih={120}>
            <Group gap="xs">
              <Loader size="sm" color={accent.secondary} />
              <Text size="sm" c="dimmed">
                {detecting
                  ? 'Reading the run folder and recognising its pipeline...'
                  : 'Reading the run folder and resolving the template...'}
              </Text>
            </Group>
          </Center>
        )}
      </Box>
      {notDetected && (
        <TemplateNotDetectedAlert message={notDetected} onPickTemplate={onPickTemplate} />
      )}
      {error && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
          data-testid="run-preview-error"
        >
          <Stack gap="xs" align="flex-start">
            <Text size="sm">{error}</Text>
            {onGiveBucketDetails && (
              <Button
                size="xs"
                variant="light"
                leftSection={<Icon icon="mdi:cloud-lock-outline" width={14} />}
                onClick={onGiveBucketDetails}
                data-testid="run-preview-private-bucket"
              >
                Give the bucket&apos;s connection details
              </Button>
            )}
          </Stack>
        </Alert>
      )}
      {foundNothing && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle" width={16} />}
          title="Nothing to ingest in this folder"
          data-testid="run-no-match-warning"
        >
          <Text size="sm">
            No data collection matched anything here. The paths under &ldquo;Not
            found&rdquo; are what was looked for: a run folder set one level too high, or
            too low, is the usual cause.
          </Text>
        </Alert>
      )}
      {report && (
        <RunPreview report={report} templateTitle={templateTitle} detection={detection} />
      )}
    </Stack>
  );
};

interface RunCreateStepProps {
  /** The plan the Preview step showed; null before one came back. */
  report: FromRunReport | null;
  templateTitle: string | null;
  detection: DetectedTemplate | null;
  /** The name the project will get. */
  projectName: string;
  /** The private bucket's connection details go with the request. */
  savesStorage: boolean;
}

export const RunCreateStep: React.FC<RunCreateStepProps> = ({
  report,
  templateTitle,
  detection,
  projectName,
  savesStorage,
}) => {
  const accent = useBrandAccents();
  const totals = report ? runCollectionTotals(report.data_collections) : null;
  return (
    <Stack gap="md" pt="md">
      {report && (
        <RunSummaryCard report={report} templateTitle={templateTitle} detection={detection} />
      )}
      <Paper withBorder radius="md" p="lg">
        <Stack gap="sm" align="center">
          <Icon
            icon="mdi:rocket-launch-outline"
            width={36}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Text fw={500} ta="center">
            Create &ldquo;{projectName}&rdquo;
          </Text>
          <Text size="xs" c="dimmed" ta="center">
            {totals
              ? `${totals.ready} of ${plural(totals.considered, 'data collection')} will be ` +
                'ingested in the background. You can watch the run and open the dashboard ' +
                'from the next screen.'
              : 'The run folder will be ingested and the template dashboards imported.'}
          </Text>
          {savesStorage && (
            <Group gap={6} wrap="nowrap" justify="center" data-testid="run-create-storage-note">
              <Icon icon="mdi:cloud-lock-outline" width={14} style={{ flexShrink: 0 }} />
              <Text size="xs" c="dimmed" ta="center">
                The private bucket&apos;s connection details are saved as this
                project&apos;s storage settings.
              </Text>
            </Group>
          )}
        </Stack>
      </Paper>
    </Stack>
  );
};
