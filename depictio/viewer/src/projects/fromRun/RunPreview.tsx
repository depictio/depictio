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
  Accordion,
  Alert,
  Button,
  Code,
  Divider,
  Group,
  Paper,
  RingProgress,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  groupRunCollections,
  relativeToRunFolder,
  runCollectionTotals,
  runTemplateMatch,
  splitTemplateId,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  DetectedTemplate,
  FromRunDCPreview,
  FromRunReport,
  RunCollectionSection,
  RunTemplateMatch,
} from 'depictio-react-core';

import { TemplateSourceLogo } from '../template';
import { CollectionKindIcon, collectionKindMeta } from './CollectionKindIcon';
import { FlowBadge } from './FlowBadge';
import type { FlowStatus } from './FlowBadge';
import { FolderPath } from './FolderPath';
import { RunMadeBy, TemplateUsed } from './RunIdentity';
import type { RunInfo } from './RunIdentity';
import { ResolvedSettings } from './TemplateSettings';

const SECTIONS: Record<
  RunCollectionSection,
  { title: string; icon: string; color: string; description: string }
> = {
  missing: {
    title: 'Not found',
    icon: 'mdi:alert-circle-outline',
    color: 'red',
    description:
      'These collections found nothing in this folder. You can still create the project: they stay empty until their files exist.',
  },
  ready: {
    title: 'Ready to ingest',
    icon: 'mdi:check-circle-outline',
    color: 'green',
    description: 'Found in the run folder and ingested when the project is created.',
  },
  optional: {
    title: 'Optional, not found',
    icon: 'mdi:minus-circle-outline',
    color: 'gray',
    description: 'The template can do without these. They are skipped when their files are absent.',
  },
};

const SECTION_ORDER: RunCollectionSection[] = ['missing', 'ready', 'optional'];

function rowStatus(dc: FromRunDCPreview, section: RunCollectionSection): FlowStatus {
  if (section === 'ready') return 'ready';
  if (section === 'optional') return dc.status === 'pruned' ? 'skipped' : 'optional';
  return dc.status === 'empty' ? 'no-files' : 'not-found';
}

function countText(dc: FromRunDCPreview, unit: 'file' | 'input'): string {
  if (dc.status === 'pruned') return '';
  if (dc.matched > 0) return `${dc.matched} ${unit}${dc.matched === 1 ? '' : 's'}`;
  if (dc.status === 'ok') return 'Counted at ingestion';
  return `No ${unit}s`;
}

/** Where a collection looks, relative to the run folder. */
const LocationLine: React.FC<{ dc: FromRunDCPreview; dataRoot: string }> = ({ dc, dataRoot }) => {
  if (dc.status === 'pruned') {
    return (
      <Text size="xs" c="dimmed">
        Left out by the template for this run.
      </Text>
    );
  }
  if (!dc.location) return null;
  const relative = relativeToRunFolder(dataRoot, dc.location);
  if (relative === '') {
    return (
      <Text size="xs" c="dimmed">
        {dc.kind === 'recipe'
          ? 'Built from files across the run folder'
          : 'Looks through the whole run folder'}
      </Text>
    );
  }
  if (relative === null) {
    return <FolderPath location={dc.location} withCopy={false} maxLength={64} />;
  }
  return (
    <Tooltip label={dc.location} withArrow multiline maw={480} zIndex={Z_LAYERS.tooltip}>
      <Code
        data-testid={`run-preview-path-${dc.data_collection_tag}`}
        style={{ alignSelf: 'flex-start', wordBreak: 'break-all' }}
      >
        {relative}
      </Code>
    </Tooltip>
  );
};

const CollectionRow: React.FC<{
  dc: FromRunDCPreview;
  dataRoot: string;
  section: RunCollectionSection;
}> = ({ dc, dataRoot, section }) => {
  const meta = collectionKindMeta(dc);
  const status = rowStatus(dc, section);
  const count = countText(dc, meta.unit);
  return (
    <Group
      wrap="nowrap"
      align="flex-start"
      gap="sm"
      py="xs"
      data-testid={`run-preview-row-${dc.data_collection_tag}`}
      data-status={dc.status}
      data-section={section}
    >
      <CollectionKindIcon dc={dc} />
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <Group gap={8} wrap="wrap">
          <Text size="sm" fw={600} style={{ wordBreak: 'break-word' }}>
            {dc.data_collection_tag}
          </Text>
          {dc.optional && (
            <Text span size="xs" c="dimmed" fs="italic">
              optional
            </Text>
          )}
        </Group>
        <LocationLine dc={dc} dataRoot={dataRoot} />
        {dc.missing_sources.length > 0 && (
          <Stack gap={2} data-testid={`run-missing-sources-${dc.data_collection_tag}`}>
            <Text size="xs" c="dimmed">
              Looked for, not found:
            </Text>
            {dc.missing_sources.map((source) => {
              const relative = relativeToRunFolder(dataRoot, source);
              return (
                <Text
                  key={source}
                  size="xs"
                  ff="monospace"
                  c="red"
                  title={source}
                  style={{ wordBreak: 'break-all' }}
                >
                  {relative === '' ? '(the run folder itself)' : relative ?? source}
                </Text>
              );
            })}
          </Stack>
        )}
      </Stack>
      <Stack gap={4} align="flex-end" style={{ flexShrink: 0 }}>
        <FlowBadge
          status={status}
          tooltip={
            status === 'skipped'
              ? 'One of the template settings turns this collection off for this run.'
              : undefined
          }
        />
        {count && (
          <Text size="xs" c="dimmed" data-testid={`run-preview-count-${dc.data_collection_tag}`}>
            {count}
          </Text>
        )}
      </Stack>
    </Group>
  );
};

/** "21 of 23 collections ready", as a ring and in words. */
const ReadyRing: React.FC<{ ready: number; considered: number }> = ({ ready, considered }) => {
  if (considered === 0) {
    return (
      <Text size="sm" c="dimmed" data-testid="run-match-summary">
        No collection to look for
      </Text>
    );
  }
  const color = ready === 0 ? 'red' : ready < considered ? 'yellow' : 'green';
  return (
    <Group gap="xs" wrap="nowrap">
      <RingProgress
        size={64}
        thickness={6}
        roundCaps
        sections={[{ value: (ready / considered) * 100, color }]}
        label={
          <Text size="xs" fw={700} ta="center">
            {ready}/{considered}
          </Text>
        }
      />
      <Text size="sm" fw={500} data-testid="run-match-summary" data-ready={ready} data-considered={considered}>
        {ready} of {considered} collection{considered === 1 ? '' : 's'} ready
      </Text>
    </Group>
  );
};

/** What made the run: the report's own detection, else the one read from
 *  the folder before the preview. Null when neither recognised it. */
export function reportRunInfo(
  report: FromRunReport,
  detection: DetectedTemplate | null,
): RunInfo | null {
  const d = report.detected_template ?? detection;
  return d?.pipeline ? { pipeline: d.pipeline, version: d.version, engine: d.engine } : null;
}

/** How the template the report used matches the run. */
export function reportMatch(
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
  /** What was read in the folder before the preview, used when the report
   *  carries no detection of its own (a template was chosen). */
  detection: DetectedTemplate | null;
}

/** The header of the plan: who made the run, the template used, the run
 *  folder once, and the ready count. */
export const RunSummaryCard: React.FC<RunSummaryCardProps> = ({
  report,
  templateTitle,
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
      <SimpleGrid cols={{ base: 1, sm: run ? 2 : 1 }} spacing="md" verticalSpacing="sm">
        {run && <RunMadeBy run={run} testIdPrefix="run-summary" />}
        <TemplateUsed
          templateId={report.template_id}
          title={templateTitle}
          match={match}
          runVersion={run?.version ?? null}
          testIdPrefix="run-summary"
          heading="Template used"
        />
      </SimpleGrid>
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
  detection,
}) => {
  const groups = groupRunCollections(report.data_collections);
  const present = SECTION_ORDER.filter((s) => groups[s].length > 0);
  const failedDashboards = report.dashboards.filter((d) => !d.success);
  const settings = Object.entries(report.resolved_variables ?? {}).filter(
    ([key]) => key !== 'DATA_ROOT',
  );

  return (
    <Stack gap="md" data-testid="run-preview-report">
      <RunSummaryCard report={report} templateTitle={templateTitle} detection={detection} />

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
        <Accordion
          multiple
          variant="separated"
          radius="md"
          // What needs a look, and what is ready, start open; the optional
          // collections that found nothing start folded.
          defaultValue={present.filter((s) => s !== 'optional')}
          chevronPosition="right"
        >
          {present.map((section) => {
            const meta = SECTIONS[section];
            const rows = groups[section];
            return (
              <Accordion.Item key={section} value={section} data-testid={`run-section-${section}`}>
                <Accordion.Control>
                  <Group gap="sm" wrap="nowrap">
                    <ThemeIcon variant="light" color={meta.color} size="md" radius="md">
                      <Icon icon={meta.icon} width={16} />
                    </ThemeIcon>
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text size="sm" fw={600}>
                        {meta.title}{' '}
                        <Text span size="sm" c="dimmed" fw={400}>
                          ({rows.length})
                        </Text>
                      </Text>
                      <Text size="xs" c="dimmed">
                        {meta.description}
                      </Text>
                    </Stack>
                  </Group>
                </Accordion.Control>
                <Accordion.Panel>
                  <Stack gap={0}>
                    {rows.map((dc, index) => (
                      <React.Fragment key={dc.data_collection_tag}>
                        {index > 0 && <Divider />}
                        <CollectionRow dc={dc} dataRoot={report.data_root} section={section} />
                      </React.Fragment>
                    ))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            );
          })}
        </Accordion>
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

/** The preview's answer when no template was picked and the server could not
 *  tell which pipeline produced the folder: say so, and send the reader back
 *  to pick one. `message` is the server's own explanation. */
export const TemplateNotDetectedAlert: React.FC<{
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
