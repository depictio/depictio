/**
 * The run-folder plan: a summary header (the template used, how many
 * collections are ready, the checks of the run against the template, the run
 * folder written once), then the data collections grouped by what needs a
 * look first: "Empty for now" and "Found" open, "Optional, not found" folded (it
 * informs, it is not a problem), then the template settings the server
 * resolved, folded too. Every path is written relative to the run folder,
 * which is what tells a folder set one level off.
 *
 * Renders the dry-run plan on the Preview step and, unchanged, the real report
 * after creation (where dashboards that failed to import are listed too).
 *
 * A project defined in the Project Builder (`custom`) is no pipeline's run:
 * its header names the project and the folder, without the pipeline, version
 * and engine checks, which have nothing to compare against.
 */
import React, { useState } from 'react';
import {
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Paper,
  RingProgress,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  isS3Location,
  runTemplateMatch,
  splitTemplateId,
} from 'depictio-react-core';
import type {
  DetectedTemplate,
  FromRunReport,
  RunStorageIn,
  RunTemplateMatch,
} from 'depictio-react-core';

import { TemplateSourceLogo } from '../template';
import { FoundCard, SourceValue } from '../detail/FoundCard';
import type { FoundRow } from '../detail/FoundCard';
import { CollectionPlan } from './CollectionPlan';
import { collectionCounts, readySummary } from './collectionCounts';
import type { CollectionCounts } from './collectionCounts';
import { FolderPath } from './FolderPath';
import { pipelineLabel } from './pipelineLabel';
import { plural } from './plural';
import { RunChecks } from './RunChecks';
import type { RunInfo } from './RunChecks';
import { ResolvedSettings } from './TemplateSettings';

/** Red when nothing is ready, yellow when some is, green when all is. */
function readyColor(ready: number, considered: number): string {
  if (ready === 0) return 'red';
  if (ready < considered) return 'yellow';
  return 'green';
}

/** "21 collections ready · 2 optional ones not in this run", as a ring and
 *  in words. The ring is complete when everything required is there. */
const ReadyRing: React.FC<{ counts: CollectionCounts }> = ({ counts }) => {
  const { ready, required } = counts;
  if (required === 0) {
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
        sections={[{ value: (ready / required) * 100, color: readyColor(ready, required) }]}
        label={
          <Text size="xs" fw={700} ta="center">
            {ready}/{required}
          </Text>
        }
      />
      <Text size="sm" fw={500} data-testid="run-match-summary" data-ready={ready} data-considered={required}>
        {readySummary(counts)}
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
  /** The catalog's long title: secondary text next to the pipeline id and
   *  version, which name the pipeline. */
  templateTitle: string | null;
  /** The engine the template was written for, when the catalog says. */
  templateEngine?: string | null;
  /** What was read in the folder before the preview, used when the report
   *  carries no detection of its own (a template was chosen). */
  detection: DetectedTemplate | null;
  /** The private bucket's connection details, to preview its files. */
  storage?: RunStorageIn | null;
  /** Defined in the Project Builder: custom workflows, no pipeline. */
  custom?: boolean;
}

/** The header of a Project Builder project's plan: its name, what is ready,
 *  and the folder. */
const CustomSummaryCard: React.FC<{ report: FromRunReport }> = ({ report }) => {
  const counts = collectionCounts(report.data_collections);
  return (
    <Paper withBorder radius="md" p="md" data-testid="run-summary-card" data-kind="custom">
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <ThemeIcon variant="light" size={40} radius="md" color="gray">
            <Icon icon="mdi:folder-cog-outline" width={24} />
          </ThemeIcon>
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text fw={700} size="lg" style={{ wordBreak: 'break-word' }} data-testid="run-summary-title">
              {report.project_name}
            </Text>
            <Text size="sm" c="dimmed">
              Custom workflows, defined in the Project Builder
            </Text>
          </Stack>
        </Group>
        <ReadyRing counts={counts} />
      </Group>
      <Group gap="xs" mt="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ flexShrink: 0 }}>
          Folder
        </Text>
        <FolderPath location={report.data_root} testId="run-preview-data-root" />
      </Group>
    </Paper>
  );
};

/** A folder of runs: several run folders named in the request, read together. */
export function readsSeveralRuns(report: FromRunReport): boolean {
  return (report.runs?.length ?? 0) > 1;
}

/** "run_a, run_b", "+N more" past the first eight. */
function runsLine(names: string[]): string {
  const shown = names.slice(0, 8);
  const rest = names.length - shown.length;
  return shown.join(', ') + (rest > 0 ? `, +${rest} more` : '');
}

/** The folder read: the run, or for several runs the folder holding them (the
 *  report's data root names the first run, read first). */
export function runsParent(report: FromRunReport): string {
  const first = readsSeveralRuns(report) ? report.runs?.[0] ?? '' : '';
  const root = report.data_root.replace(/\/+$/, '');
  return first && root.endsWith(`/${first}`) ? root.slice(0, -(first.length + 1)) : report.data_root;
}

/** The header of the plan: the template used, the ready count, the checks
 *  and the run folder once. */
export const RunSummaryCard: React.FC<RunSummaryCardProps> = ({
  report,
  templateTitle,
  templateEngine = null,
  detection,
  storage = null,
}) => {
  const run = reportRunInfo(report, detection);
  const match = reportMatch(report, detection);
  const counts = collectionCounts(report.data_collections);
  const source = splitTemplateId(report.template_id).source;
  const label = pipelineLabel(report.template_id) ?? report.template_id;
  // A folder of runs: the folder holding them, and their names.
  const severalRuns = readsSeveralRuns(report);
  const shownFolder = runsParent(report);
  return (
    <Paper withBorder radius="md" p="md" data-testid="run-summary-card">
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <TemplateSourceLogo source={source} size={40} />
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text fw={700} size="lg" style={{ wordBreak: 'break-word' }} data-testid="run-summary-title">
              {label}
            </Text>
            {templateTitle && templateTitle !== label && (
              <Text size="sm" c="dimmed" data-testid="run-summary-long-title">
                {templateTitle}
              </Text>
            )}
            <Text size="sm" c="dimmed">
              Project &ldquo;{report.project_name}&rdquo;
            </Text>
          </Stack>
        </Group>
        <ReadyRing counts={counts} />
      </Group>
      <Divider my="sm" />
      <RunChecks
        location={report.data_root}
        run={run}
        templateId={report.template_id}
        templateName={label}
        templateEngine={templateEngine}
        match={match}
        plan={{ status: 'ready', report }}
        storage={storage}
        withPlan={false}
        testIdPrefix="run-summary"
      />
      <Group gap="xs" mt="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ flexShrink: 0 }}>
          {severalRuns ? 'Runs folder' : 'Run folder'}
        </Text>
        <FolderPath location={shownFolder} testId="run-preview-data-root" />
        {severalRuns && (
          <Text size="xs" c="dimmed" truncate data-testid="run-preview-runs">
            {report.runs?.join(', ')}
          </Text>
        )}
      </Group>
    </Paper>
  );
};

/** What the pipeline row says about how the pipeline relates to the run. */
function pipelineHint(
  match: RunTemplateMatch | null,
): { status: 'ok' | 'differs' | 'warn' | 'info'; text: string } | null {
  switch (match) {
    case 'exact':
      return { status: 'ok', text: "matches the run's records" };
    case 'closest':
    case 'other-version':
      return { status: 'differs', text: 'versions differ, the closest one is used' };
    case 'other-pipeline':
      return { status: 'warn', text: 'the run was made by another pipeline' };
    case 'none':
      return { status: 'info', text: 'no matching pipeline version for this run' };
    default:
      return null;
  }
}

export interface RunFoundInfo {
  /** Where the pipeline came from: read from the folder, or picked. */
  chosenFrom: 'detected' | 'user' | null;
}

/** "What Depictio found" for a run folder: pipeline, runs, source, contents,
 *  and the checks folded away. */
export const RunFoundCard: React.FC<RunSummaryCardProps & { found: RunFoundInfo }> = ({
  report,
  templateTitle,
  templateEngine = null,
  detection,
  storage = null,
  found,
}) => {
  const [checksOpen, setChecksOpen] = useState(false);
  const run = reportRunInfo(report, detection);
  const match = reportMatch(report, detection);
  const counts = collectionCounts(report.data_collections);
  const { ready, required: considered } = counts;
  const parts = splitTemplateId(report.template_id);
  const hint = pipelineHint(match);
  // Several run folders named in the request: they are the runs, read from the first.
  const severalRuns = readsSeveralRuns(report);
  const runs = severalRuns ? (report.runs ?? []) : (report.detected_runs ?? []);
  const sourceKind = isS3Location(report.data_root) ? 's3' : 'folder';
  const label = pipelineLabel(report.template_id) ?? report.template_id;
  const rows: FoundRow[] = [
    {
      key: 'pipeline',
      label: 'Pipeline',
      status: hint?.status ?? null,
      hint: hint?.text,
      value: (
        <Stack gap={2}>
          <Group gap="xs" wrap="wrap">
            <Text size="sm" data-testid="run-found-pipeline">
              {label}
            </Text>
            {templateTitle && templateTitle !== label && (
              <Text size="sm" c="dimmed">
                {templateTitle}
              </Text>
            )}
            {found.chosenFrom && (
              <Badge variant="light" color={found.chosenFrom === 'detected' ? 'blue' : 'gray'} size="sm">
                {found.chosenFrom === 'detected'
                  ? 'Detected'
                  : `You chose ${parts.version ?? label}`}
              </Badge>
            )}
          </Group>
          {run?.version && found.chosenFrom === 'user' && (
            <Text size="xs" c="dimmed">
              The run says {run.version}
            </Text>
          )}
        </Stack>
      ),
    },
    ...(runs.length > 0
      ? [
          {
            key: 'runs',
            label: 'Runs',
            // The names, on one line like every other row; how they are read under them.
            value: (
              <Text size="sm" style={{ wordBreak: 'break-word' }} data-testid="run-found-runs">
                {runsLine(runs)}
              </Text>
            ),
            hint: severalRuns
              ? `${plural(runs.length, 'run')}, read together: the counts below add them up`
              : undefined,
          } satisfies FoundRow,
        ]
      : []),
    {
      key: 'source',
      label: 'Source',
      value: <SourceValue kind={sourceKind} location={severalRuns ? runsParent(report) : report.data_root} />,
    },
    {
      key: 'contents',
      label: 'Contents',
      value:
        considered === 0 ? (
          <Text size="sm" c="dimmed" data-testid="run-match-summary">
            No collection to look for
          </Text>
        ) : (
          <Text size="sm" data-testid="run-match-summary" data-ready={ready} data-considered={considered}>
            {readySummary(counts)}
          </Text>
        ),
    },
    {
      key: 'checks',
      label: 'Checks',
      value: (
        <Stack gap="xs">
          <Button
            variant="subtle"
            size="compact-sm"
            color="gray"
            px={0}
            style={{ alignSelf: 'flex-start' }}
            leftSection={<Icon icon={checksOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />}
            onClick={() => setChecksOpen((o) => !o)}
            aria-expanded={checksOpen}
            data-testid="run-found-checks-toggle"
          >
            {checksOpen ? 'Hide checks' : 'Show checks'}
          </Button>
          <Collapse in={checksOpen}>
            <RunChecks
              location={report.data_root}
              run={run}
              templateId={report.template_id}
              templateName={label}
              templateEngine={templateEngine}
              match={match}
              plan={{ status: 'ready', report }}
              storage={storage}
              withPlan={false}
              testIdPrefix="run-summary"
            />
          </Collapse>
        </Stack>
      ),
    },
  ];
  return <FoundCard embedded rows={rows} testId="run-found-card" />;
};

export const RunPreview: React.FC<RunSummaryCardProps & { found?: RunFoundInfo | null }> = ({
  report,
  templateTitle,
  templateEngine = null,
  detection,
  storage = null,
  found = null,
  custom = false,
}) => {
  const failedDashboards = report.dashboards.filter((d) => !d.success);
  const settings = Object.entries(report.resolved_variables ?? {}).filter(
    ([key]) => key !== 'DATA_ROOT',
  );

  return (
    <Stack gap="md" data-testid="run-preview-report">
      {custom ? (
        <CustomSummaryCard report={report} />
      ) : found ? (
        <RunFoundCard
          report={report}
          templateTitle={templateTitle}
          templateEngine={templateEngine}
          detection={detection}
          storage={storage}
          found={found}
        />
      ) : (
        <RunSummaryCard
          report={report}
          templateTitle={templateTitle}
          templateEngine={templateEngine}
          detection={detection}
          storage={storage}
        />
      )}

      {report.data_collections.length === 0 ? (
        <Group gap="xs" wrap="nowrap" data-testid="run-preview-empty">
          <ThemeIcon variant="light" color="gray" size="md" radius="md">
            <Icon icon="mdi:table-off" width={16} />
          </ThemeIcon>
          <Text size="sm" c="dimmed">
            No data collection is defined to look for in this folder.
          </Text>
        </Group>
      ) : (
        <CollectionPlan
          rows={report.data_collections}
          dataRoot={report.data_root}
          storage={storage}
          folderWord={custom ? 'folder' : 'run folder'}
        />
      )}

      {settings.length > 0 && <ResolvedSettings settings={settings} dataRoot={report.data_root} />}

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
