import React, { useEffect, useMemo, useState } from 'react';
import { Anchor, Box, Group, SegmentedControl, Stack, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { AlertTriangle, ChevronDown, ChevronUp, Flag, GitBranch, Table2 } from 'lucide-react';
import { fetchIngestionReport } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';
import { FoundCard, RunChips, SourceValue, type FoundRow } from './FoundCard';
import { saveProjectLayout } from './projectLayoutApi';
import {
  dataCollectionCount,
  projectLayout,
  projectPipeline,
  projectSentence,
  projectSource,
  type ProjectLayoutKind,
} from '../layout';
import { parseTemplate, templateDocsUrl } from '../template';

const KIND_NAME: Record<ProjectLayoutKind, string> = {
  runs: 'several runs',
  pipeline: 'one run',
  tables: 'plain tables',
};

const KIND_ICON: Record<ProjectLayoutKind, typeof Flag> = {
  runs: GitBranch,
  pipeline: Flag,
  tables: Table2,
};

/** Run names per project, kept so a reload of the page does not flash the
 *  "several runs" fallback while the report is fetched again. */
const runNamesCache = new Map<string, string[]>();

interface ProjectSummaryProps {
  project: ProjectListEntry;
  projectId: string | null;
  dashboardsCount?: number | null;
  /** The viewer may change how the project is read. */
  canEdit: boolean;
  /** Shown as the reason when `canEdit` is false. */
  disabledReason?: string;
  /** The project is read-only because it was published. */
  locked?: boolean;
  /** Called after the layout was saved, to reload the project. */
  onChanged: () => void;
  /** The "What Depictio found" disclosure. Held by the parent when it
   *  remounts this component while it reloads the project. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Changes when the project was reloaded, to read its runs again. */
  refreshKey?: number;
  /** Show the page's ingestion report (the failed-collections line links to it). */
  onShowIngestion?: () => void;
}

/** One generated sentence about the project, with the facts behind it and a
 *  way to correct a wrong guess. */
export const ProjectSummary: React.FC<ProjectSummaryProps> = ({
  project,
  projectId,
  dashboardsCount,
  canEdit,
  disabledReason = 'Owner permission required',
  locked = false,
  onChanged,
  open: openProp,
  onOpenChange,
  refreshKey = 0,
  onShowIngestion,
}) => {
  const [openLocal, setOpenLocal] = useState(false);
  const open = openProp ?? openLocal;
  const setOpen = (next: boolean) => {
    setOpenLocal(next);
    onOpenChange?.(next);
  };
  const [saving, setSaving] = useState(false);
  const [runNames, setRunNames] = useState<string[] | null>(
    projectId ? (runNamesCache.get(projectId) ?? null) : null,
  );
  const [failedCollections, setFailedCollections] = useState(0);
  // The runs live in the server's `runs` collection; `workflows[].runs` is empty.
  useEffect(() => {
    if (!projectId) return undefined;
    let cancelled = false;
    fetchIngestionReport(projectId)
      .then((report) => {
        if (cancelled) return;
        const names = (report.runs ?? []).map((r) => r.run_tag).filter(Boolean);
        runNamesCache.set(projectId, names);
        setRunNames(names);
        setFailedCollections(
          (report.data_collections ?? []).filter((dc) => (dc.files_failed ?? 0) > 0).length,
        );
      })
      .catch(() => {
        // Keep the fallback built from the project payload.
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);
  const layout = useMemo(() => projectLayout(project, { runNames }), [project, runNames]);
  const source = useMemo(() => projectSource(project), [project]);
  const pipeline = useMemo(() => projectPipeline(project), [project]);
  const sentence = projectSentence(project, { dashboards: dashboardsCount, runNames });
  const Glyph = KIND_ICON[layout.kind];
  const tmpl = parseTemplate(project);
  const collections = dataCollectionCount(project);

  const rows: FoundRow[] = [];
  if (pipeline) {
    rows.push({
      key: 'pipeline',
      label: 'Pipeline',
      value: (
        <Group gap="xs" wrap="wrap">
          <Text size="sm">
            {pipeline.name}
            {pipeline.version ? ` ${pipeline.version}` : ''}
          </Text>
          {tmpl && (
            <Anchor href={templateDocsUrl(tmpl)} target="_blank" rel="noreferrer" size="xs">
              Documentation
            </Anchor>
          )}
        </Group>
      ),
    });
  }
  if (layout.kind !== 'tables') {
    // The run records come from the ingestion report; until they are read
    // (or when none were recorded) no count is claimed, as in the sentence.
    rows.push({
      key: 'runs',
      label: 'Runs',
      value:
        layout.runCount > 0 ? (
          <Stack gap={6}>
            <Text size="sm">{layout.runCount === 1 ? '1 run' : `${layout.runCount} runs`}</Text>
            <RunChips names={layout.runNames} />
          </Stack>
        ) : (
          <Text size="sm" c="dimmed">
            Not recorded yet
          </Text>
        ),
    });
  }
  rows.push({
    key: 'source',
    label: 'Source',
    value: <SourceValue kind={source.kind} location={source.location} locations={source.locations} />,
  });
  rows.push({
    key: 'contents',
    label: 'Contents',
    value: (
      <Text size="sm">
        {layout.kind === 'tables'
          ? collections === 1
            ? '1 table'
            : `${collections} tables`
          : collections === 1
            ? '1 collection'
            : `${collections} collections`}
        {typeof dashboardsCount === 'number'
          ? ` and ${dashboardsCount === 1 ? '1 dashboard' : `${dashboardsCount} dashboards`}`
          : ''}
      </Text>
    ),
  });

  const disabled = !canEdit || locked || saving;
  const reason = locked
    ? 'This project is published and read-only'
    : !canEdit
      ? disabledReason
      : undefined;

  const change = async (value: string) => {
    if (!projectId) return;
    const next = value === 'detected' ? null : (value as ProjectLayoutKind);
    setSaving(true);
    try {
      await saveProjectLayout(projectId, next);
      onChanged();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not change how this project is read',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setSaving(false);
    }
  };

  const control = (
    <SegmentedControl
      size="xs"
      data-testid="project-layout-control"
      disabled={disabled}
      value={layout.overridden ? layout.kind : 'detected'}
      onChange={change}
      data={[
        { value: 'detected', label: `Detected (${KIND_NAME[layout.detectedKind]})` },
        { value: 'pipeline', label: 'One run' },
        { value: 'runs', label: 'Several runs' },
        { value: 'tables', label: 'Plain tables' },
      ]}
    />
  );

  return (
    <Stack gap={6} data-testid="project-summary">
      <Group gap="xs" wrap="nowrap" align="center">
        <Glyph size={16} aria-hidden style={{ flexShrink: 0 }} />
        <Text size="sm" fw={500} data-testid="project-sentence">
          {sentence}
        </Text>
      </Group>
      {failedCollections > 0 && (
        <Group gap={6} wrap="nowrap" align="center" data-testid="project-ingestion-warning">
          <AlertTriangle size={14} aria-hidden style={{ flexShrink: 0 }} color="var(--mantine-color-orange-6)" />
          <Text size="xs" c="dimmed">
            {failedCollections === 1
              ? '1 collection failed in the last ingestion'
              : `${failedCollections} collections failed in the last ingestion`}
            {onShowIngestion && (
              <>
                {' · '}
                <Anchor
                  component="button"
                  type="button"
                  size="xs"
                  onClick={onShowIngestion}
                  data-testid="project-ingestion-warning-link"
                >
                  See the ingestion report
                </Anchor>
              </>
            )}
          </Text>
        </Group>
      )}
      <UnstyledButton
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        data-testid="project-found-toggle"
        style={{ alignSelf: 'flex-start' }}
      >
        <Group gap={4} wrap="nowrap" c="dimmed">
          <Text size="xs" c="dimmed">
            What Depictio found
          </Text>
          {open ? <ChevronUp size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
        </Group>
      </UnstyledButton>
      {open && (
        <Stack gap="sm" mt={4}>
          <FoundCard testId="project-found-card" rows={rows} />
          <Stack gap={6}>
            <Text size="xs" c="dimmed">
              Not right? Treat this project as:
            </Text>
            <Box>
              {reason ? (
                <Tooltip label={reason} withArrow>
                  <Box style={{ display: 'inline-block' }}>{control}</Box>
                </Tooltip>
              ) : (
                control
              )}
            </Box>
          </Stack>
        </Stack>
      )}
    </Stack>
  );
};

export default ProjectSummary;
