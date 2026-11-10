import React, { useEffect, useMemo, useState } from 'react';
import {
  Anchor,
  Badge,
  Box,
  Group,
  Popover,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { AlertTriangle, ExternalLink } from 'lucide-react';
import { fetchIngestionReport } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';
import { useListingAccents } from '../../lib/useListingAccents';
import { DcTypeIcon, dcTypeMeta } from '../dcTypeIcon';
import { SOURCE_ICON, SOURCE_TEXT } from './FoundCard';
import type { ProjectSourceKind } from '../layout';
import { projectLayout, projectPipelines, projectSource, projectTypeCounts } from '../layout';
import { parseTemplate, templateDocsUrl } from '../template';

/** Run names per project, kept so a reload of the page does not flash the
 *  "several runs" fallback while the report is fetched again. */
const runNamesCache = new Map<string, string[]>();

interface ProjectSummaryProps {
  project: ProjectListEntry;
  projectId: string | null;
  dashboardsCount?: number | null;
  /** Changes when the project was reloaded, to read its runs again. */
  refreshKey?: number;
  /** Show the page's ingestion report (the failed-collections line links to it). */
  onShowIngestion?: () => void;
  /** Show the page's Runs tab, on one run when given. */
  onShowRuns?: (run?: string) => void;
}

/** A label's worth of `SOURCE_TEXT`, which reads as the end of a sentence. */
const SHORT_SOURCE: Partial<Record<ProjectSourceKind, string>> = {
  url: 'URL',
  folder: 'Folder',
  s3: 'S3 bucket',
  run: 'Run folder',
  manifest: 'Manifest',
};

/** One labelled block of the summary; a count appears once there are several. */
const Fact: React.FC<{
  label: string;
  count?: number;
  testId: string;
  children: React.ReactNode;
}> = ({ label, count = 0, testId, children }) => (
  <Stack gap={6} style={{ minWidth: 0 }} data-testid={testId}>
    <Group gap={6} wrap="nowrap">
      <Text size="xs" fw={600} c="dimmed" tt="uppercase">
        {label}
      </Text>
      {count > 1 && (
        <Text size="xs" fw={700}>
          {count}
        </Text>
      )}
    </Group>
    {children}
  </Stack>
);

const CHIP_MAX_WIDTH = 190;
/** Below this a list is read at a glance; a search box would be noise. */
const SEARCH_FROM = 9;
/** Above this a run name takes the line for itself. */
const LONG_RUN_NAME = 12;
const RUN_CHIP_CHARS = 20;

/** Run names of one series share their start and differ at the end, so an
 *  ordinary ellipsis would make every chip read the same. */
const middleEllipsis = (text: string, max: number) =>
  text.length <= max
    ? text
    : `${text.slice(0, Math.ceil((max - 1) / 2))}…${text.slice(-Math.floor((max - 1) / 2))}`;

/** The first items of a list on one line; the rest, however many, behind a
 *  "+N" that opens the whole list, so a long list never grows the header. */
function CappedList<T>({
  items,
  shown,
  keyOf,
  chip,
  row,
  textOf,
  title,
  testId,
  footer,
}: {
  items: T[];
  shown: number;
  keyOf: (item: T) => string;
  chip: (item: T) => React.ReactNode;
  row: (item: T) => React.ReactNode;
  textOf: (item: T) => string;
  title: string;
  testId: string;
  /** Below the list, e.g. a link to where the whole thing lives. */
  footer?: React.ReactNode;
}) {
  const [query, setQuery] = useState('');
  const rest = items.length - shown;
  const needle = query.trim().toLowerCase();
  const matching = needle ? items.filter((i) => textOf(i).toLowerCase().includes(needle)) : items;
  return (
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
      {items.slice(0, shown).map((item) => (
        <React.Fragment key={keyOf(item)}>{chip(item)}</React.Fragment>
      ))}
      {rest > 0 && (
        <Popover width={420} position="bottom-start" shadow="md" withArrow onClose={() => setQuery('')}>
          <Popover.Target>
            <UnstyledButton aria-label={`Show all ${title}`} data-testid={`${testId}-more`}>
              <Text size="xs" fw={600} c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                +{rest}
              </Text>
            </UnstyledButton>
          </Popover.Target>
          <Popover.Dropdown data-testid={`${testId}-list`}>
            <Stack gap="xs">
              <Text size="xs" fw={600} c="dimmed" tt="uppercase">
                {items.length} {title}
              </Text>
              {items.length >= SEARCH_FROM && (
                <TextInput
                  size="xs"
                  placeholder="Search"
                  aria-label={`Search ${title}`}
                  value={query}
                  onChange={(e) => setQuery(e.currentTarget.value)}
                />
              )}
              <ScrollArea.Autosize mah={260} type="auto">
                <Stack gap={4}>
                  {matching.map((item) => (
                    <Box key={keyOf(item)}>{row(item)}</Box>
                  ))}
                  {matching.length === 0 && (
                    <Text size="xs" c="dimmed">
                      Nothing matches.
                    </Text>
                  )}
                </Stack>
              </ScrollArea.Autosize>
              {footer}
            </Stack>
          </Popover.Dropdown>
        </Popover>
      )}
    </Group>
  );
}

const pipelineText = (p: { name: string; version: string | null }) =>
  `${p.name}${p.version ? ` ${p.version}` : ''}`;

/** What the project holds, as blocks that say what each fact is: its pipelines
 *  and runs when it has any, its collections by type, where they came from. */
export const ProjectSummary: React.FC<ProjectSummaryProps> = ({
  project,
  projectId,
  dashboardsCount,
  refreshKey = 0,
  onShowIngestion,
  onShowRuns,
}) => {
  const accent = useListingAccents('projects');
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
  const pipelines = useMemo(() => projectPipelines(project), [project]);
  const typeCounts = useMemo(() => projectTypeCounts(project), [project]);
  const runs = useMemo(
    () =>
      [...layout.runNames].sort((a, b) =>
        a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
      ),
    [layout.runNames],
  );
  const tmpl = parseTemplate(project);
  const SourceGlyph = SOURCE_ICON[source.kind];
  const places = source.locations ?? (source.location ? [source.location] : []);
  const sourceLabel =
    source.locations && source.locations.length > 1 && source.kind !== 'mixed'
      ? `${source.locations.length} folders`
      : (SHORT_SOURCE[source.kind] ?? SOURCE_TEXT[source.kind]);
  const sourceBadge = (
    <Badge
      variant="default"
      radius="sm"
      tt="none"
      size="lg"
      fw={500}
      leftSection={<SourceGlyph size={14} aria-hidden />}
    >
      {sourceLabel}
    </Badge>
  );

  return (
    // The header is a flex row: without this the grid would shrink to its content
    // and stack its blocks in one column.
    <Stack gap="sm" style={{ flex: '1 1 0', minWidth: 0 }} data-testid="project-summary">
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
          gap: 'var(--mantine-spacing-md) var(--mantine-spacing-xl)',
          width: '100%',
        }}
      >
        {pipelines.length > 0 && (
          <Fact
            label={pipelines.length > 1 ? 'Pipelines' : 'Pipeline'}
            count={pipelines.length}
            testId="project-fact-pipelines"
          >
            <CappedList
              items={pipelines}
              shown={pipelines.length > 2 ? 1 : 2}
              keyOf={pipelineText}
              textOf={pipelineText}
              title="pipelines"
              testId="project-fact-pipelines"
              chip={(pipeline) => {
                const docs = pipelines.length === 1 && tmpl ? templateDocsUrl(tmpl) : null;
                return (
                  <Tooltip label={pipelineText(pipeline)} withArrow>
                    <Badge
                      variant="light"
                      color={accent.secondary}
                      radius="sm"
                      tt="none"
                      size="lg"
                      fw={500}
                      maw={CHIP_MAX_WIDTH}
                      {...(docs
                        ? { component: 'a' as const, href: docs, target: '_blank', rel: 'noreferrer' }
                        : {})}
                      style={docs ? { cursor: 'pointer' } : undefined}
                      rightSection={docs ? <ExternalLink size={12} aria-hidden /> : undefined}
                    >
                      {pipelineText(pipeline)}
                    </Badge>
                  </Tooltip>
                );
              }}
              row={(pipeline) => <Text size="sm">{pipelineText(pipeline)}</Text>}
            />
          </Fact>
        )}
        {(layout.runCount > 0 || layout.realWorkflows.length > 0) && (
          <Fact
            label={layout.runCount > 1 ? 'Runs' : 'Run'}
            count={layout.runCount}
            testId="project-fact-runs"
          >
            {layout.runCount > 0 ? (
              <CappedList
                items={runs}
                shown={runs.some((run) => run.length > LONG_RUN_NAME) ? 1 : 2}
                keyOf={(run) => run}
                textOf={(run) => run}
                title="runs"
                testId="project-fact-runs"
                footer={
                  onShowRuns && (
                    <Anchor component="button" type="button" size="xs" onClick={() => onShowRuns()}>
                      Open the Runs tab
                    </Anchor>
                  )
                }
                chip={(run) => (
                  <Tooltip label={onShowRuns ? `${run}: see this run` : run} withArrow>
                    <Badge
                      {...(onShowRuns
                        ? { component: 'button' as const, type: 'button' as const, onClick: () => onShowRuns(run) }
                        : {})}
                      style={onShowRuns ? { cursor: 'pointer' } : undefined}
                      variant="light"
                      color="gray"
                      radius="sm"
                      tt="none"
                      size="lg"
                      fw={500}
                      ff="monospace"
                      maw={CHIP_MAX_WIDTH}
                    >
                      {middleEllipsis(run, RUN_CHIP_CHARS)}
                    </Badge>
                  </Tooltip>
                )}
                row={(run) => {
                  const text = (
                    <Text size="sm" ff="monospace" style={{ overflowWrap: 'anywhere' }}>
                      {run}
                    </Text>
                  );
                  return onShowRuns ? (
                    <UnstyledButton onClick={() => onShowRuns(run)} title="See this run">
                      {text}
                    </UnstyledButton>
                  ) : (
                    text
                  );
                }}
              />
            ) : (
              <Text size="sm" c="dimmed">
                Not recorded yet
              </Text>
            )}
          </Fact>
        )}
        <Fact
          label="Data collections"
          count={typeCounts.reduce((sum, { count }) => sum + count, 0)}
          testId="project-fact-data"
        >
          {typeCounts.length > 0 ? (
            // There are only a handful of types: all of them, whole, wrapping.
            <Group gap={6} wrap="wrap">
              {typeCounts.map(({ type, count }) => (
                <Badge
                  key={type}
                  variant="default"
                  radius="sm"
                  tt="none"
                  size="lg"
                  fw={500}
                  styles={{ root: { flexShrink: 0, maxWidth: 'none' }, label: { overflow: 'visible' } }}
                  leftSection={<DcTypeIcon type={type} size={14} withTooltip={false} />}
                  data-testid={`project-fact-type-${type}`}
                >
                  {dcTypeMeta(type).label}
                  <Text span inherit fw={700} ml={6}>
                    {count}
                  </Text>
                </Badge>
              ))}
            </Group>
          ) : (
            <Text size="sm" c="dimmed">
              No data yet
            </Text>
          )}
        </Fact>
        {typeCounts.length > 0 && source.kind !== 'unknown' && (
          <Fact label="Source" testId="project-fact-source">
            {places.length > 0 ? (
              <Tooltip
                label={
                  <Stack gap={2}>
                    {places.map((place) => (
                      <Text key={place} size="xs" inherit style={{ wordBreak: 'break-all' }}>
                        {place}
                      </Text>
                    ))}
                  </Stack>
                }
                multiline
                maw={480}
                withArrow
              >
                <span style={{ display: 'inline-flex', width: 'fit-content' }}>{sourceBadge}</span>
              </Tooltip>
            ) : (
              sourceBadge
            )}
          </Fact>
        )}
      </Box>
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
    </Stack>
  );
};

export default ProjectSummary;
