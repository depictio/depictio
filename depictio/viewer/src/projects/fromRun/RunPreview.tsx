/**
 * The run-folder plan: a summary header (what made the run, the template
 * used, the run folder written once, how many collections are ready), then
 * the data collections grouped by what needs a look first: "Not found" and
 * "Ready to ingest" open, "Optional, not found" folded (it informs, it is not
 * a problem), then the template settings the server resolved, folded too.
 * Every path is written relative to the run folder, which is what tells a
 * folder set one level off.
 *
 * Renders the dry-run plan on the Preview step and, unchanged, the real report
 * after creation (where dashboards that failed to import are listed too).
 */
import React from 'react';
import {
  Alert,
  Code,
  Divider,
  Group,
  Paper,
  RingProgress,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { runCollectionTotals, runTemplateMatch, splitTemplateId } from 'depictio-react-core';
import type { DetectedTemplate, FromRunReport, RunTemplateMatch } from 'depictio-react-core';

import { TemplateSourceLogo } from '../template';
import { CollectionPlan } from './CollectionPlan';
import { FolderPath } from './FolderPath';
import { plural } from './plural';
import { RunTemplateTable } from './RunIdentity';
import type { RunInfo } from './RunIdentity';
import { ResolvedSettings } from './TemplateSettings';

/** Red when nothing is ready, yellow when some is, green when all is. */
function readyColor(ready: number, considered: number): string {
  if (ready === 0) return 'red';
  if (ready < considered) return 'yellow';
  return 'green';
}

/** "21 of 23 collections ready", as a ring and in words. */
const ReadyRing: React.FC<{ ready: number; considered: number }> = ({ ready, considered }) => {
  if (considered === 0) {
    return (
      <Text size="sm" c="dimmed" data-testid="run-match-summary">
        No collection to look for
      </Text>
    );
  }
  return (
    <Group gap="xs" wrap="nowrap">
      <RingProgress
        size={64}
        thickness={6}
        roundCaps
        sections={[{ value: (ready / considered) * 100, color: readyColor(ready, considered) }]}
        label={
          <Text size="xs" fw={700} ta="center">
            {ready}/{considered}
          </Text>
        }
      />
      <Text size="sm" fw={500} data-testid="run-match-summary" data-ready={ready} data-considered={considered}>
        {ready} of {plural(considered, 'collection')} ready
      </Text>
    </Group>
  );
};

/** What made the run: the report's own detection, else the one read from
 *  the folder before the preview. Null when neither recognised it. */
function reportRunInfo(
  report: FromRunReport,
  detection: DetectedTemplate | null,
): RunInfo | null {
  const d = report.detected_template ?? detection;
  return d?.pipeline ? d : null;
}

/** How the template the report used matches the run. */
function reportMatch(
  report: FromRunReport,
  detection: DetectedTemplate | null,
): RunTemplateMatch | null {
  const d = report.detected_template ?? detection;
  return runTemplateMatch({
    runPipeline: d?.pipeline,
    runVersion: d?.version,
    templateId: report.template_id,
    detectedTemplateId: d?.template_id,
    detectedMatch: d?.match ?? null,
  });
}

interface RunSummaryCardProps {
  report: FromRunReport;
  /** The template's name; the id is shown when it is not known. */
  templateTitle: string | null;
  /** The engine the template was written for, when the catalog says. */
  templateEngine?: string | null;
  /** What was read in the folder before the preview, used when the report
   *  carries no detection of its own (a template was chosen). */
  detection: DetectedTemplate | null;
}

/** The header of the plan: who made the run, the template used, the run
 *  folder once, and the ready count. */
export const RunSummaryCard: React.FC<RunSummaryCardProps> = ({
  report,
  templateTitle,
  templateEngine = null,
  detection,
}) => {
  const run = reportRunInfo(report, detection);
  const match = reportMatch(report, detection);
  const { ready, considered } = runCollectionTotals(report.data_collections);
  const source = splitTemplateId(report.template_id).source;
  return (
    <Paper withBorder radius="md" p="md" data-testid="run-summary-card">
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <TemplateSourceLogo source={source} size={40} />
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text fw={700} size="lg" style={{ wordBreak: 'break-word' }} data-testid="run-summary-title">
              {templateTitle || report.template_id}
            </Text>
            <Text size="sm" c="dimmed">
              Project &ldquo;{report.project_name}&rdquo;
            </Text>
          </Stack>
        </Group>
        <ReadyRing ready={ready} considered={considered} />
      </Group>
      <Divider my="sm" />
      <RunTemplateTable
        run={run}
        templateId={report.template_id}
        templateName={templateTitle}
        templateEngine={templateEngine}
        match={match}
        testIdPrefix="run-summary"
        templateHeading="Template used"
      />
      <Group gap="xs" mt="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ flexShrink: 0 }}>
          Run folder
        </Text>
        <FolderPath location={report.data_root} testId="run-preview-data-root" />
      </Group>
    </Paper>
  );
};

export const RunPreview: React.FC<RunSummaryCardProps> = ({
  report,
  templateTitle,
  templateEngine = null,
  detection,
}) => {
  const failedDashboards = report.dashboards.filter((d) => !d.success);
  const settings = Object.entries(report.resolved_variables ?? {}).filter(
    ([key]) => key !== 'DATA_ROOT',
  );

  return (
    <Stack gap="md" data-testid="run-preview-report">
      <RunSummaryCard
        report={report}
        templateTitle={templateTitle}
        templateEngine={templateEngine}
        detection={detection}
      />

      {report.truncated && (
        <Alert
          color="yellow"
          variant="light"
          icon={<Icon icon="mdi:information-outline" width={16} />}
          data-testid="run-truncated-warning"
        >
          <Text size="sm">
            The folder listing was cut short, so every count below is a lower bound. More
            files are picked up at ingestion.
          </Text>
        </Alert>
      )}

      {report.data_collections.length === 0 ? (
        <Group gap="xs" wrap="nowrap" data-testid="run-preview-empty">
          <ThemeIcon variant="light" color="gray" size="md" radius="md">
            <Icon icon="mdi:table-off" width={16} />
          </ThemeIcon>
          <Text size="sm" c="dimmed">
            The template defines no data collection to look for in this folder.
          </Text>
        </Group>
      ) : (
        <CollectionPlan rows={report.data_collections} dataRoot={report.data_root} />
      )}

      {settings.length > 0 && <ResolvedSettings settings={settings} dataRoot={report.data_root} />}

      {report.detected_runs.length > 0 && (
        <Group gap={6} wrap="wrap" data-testid="run-detected-runs">
          <Text size="xs" c="dimmed">
            Runs found in this folder:
          </Text>
          {report.detected_runs.map((name) => (
            <Code key={name}>{name}</Code>
          ))}
        </Group>
      )}

      {failedDashboards.length > 0 && (
        <Stack gap={4} data-testid="run-failed-dashboards">
          <Text size="xs" c="dimmed">
            Dashboards that failed to import:
          </Text>
          {failedDashboards.map((d) => (
            <Group key={d.path} gap="xs" wrap="nowrap" align="flex-start">
              <ThemeIcon variant="light" color="red" size="xs" radius="xl">
                <Icon icon="mdi:alert-circle" width={12} />
              </ThemeIcon>
              <Text size="xs" fw={600}>
                {d.title || d.path}
              </Text>
              {d.error && (
                <Text size="xs" c="red">
                  {d.error}
                </Text>
              )}
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
};
