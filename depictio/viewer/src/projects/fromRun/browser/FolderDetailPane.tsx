/**
 * The right-hand side of the folder browser: what the selected folder holds
 * and what Depictio recognises in it, read with `inspectFolder` on selection
 * (a newer selection cancels the request still in flight).
 *
 * Top down: the folder and its path; the checks of the run against the
 * template Depictio would read it with (one line each, what the template
 * finds one click away); the run records that make it a run folder (its
 * `pipeline_info`, previewable, and its MultiQC report); the search for run
 * folders below it; and its contents, one list, folders first, each folder
 * one click from opening. Once a search ran, its hits (`RunSearchResults`)
 * come before the contents, which fold under a toggle. A folder in a private
 * bucket is read, and searched, with its connection details.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  NavLink,
  Paper,
  ScrollArea,
  Skeleton,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  UnstyledButton,
} from '@mantine/core';
import { useId } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import {
  findRunFolders,
  folderName,
  inspectFolder,
  normalizeFolder,
  relativeToFolder,
  runTemplateMatch,
} from 'depictio-react-core';
import type { FolderInspection, RunStorageIn, TemplateInfo } from 'depictio-react-core';

import { FlowBadge } from '../FlowBadge';
import { FolderPath } from '../FolderPath';
import { plural } from '../plural';
import { RunChecks } from '../RunChecks';
import { MARKER_META, MarkerIcon } from '../RunMarkers';
import { useRunPlan } from '../runPlan';
import { PipelineInfoPreview } from './PipelineInfoPreview';
import { RunSearchResults } from './RunSearchResults';
import type { FindState } from './RunSearchResults';

/** More entries than this get a filter above the contents. */
const FILTER_FROM = 12;

type InspectState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; result: FolderInspection };

interface FolderDetailPaneProps {
  /** The selected folder; null shows a hint. */
  location: string | null;
  /** The catalog's templates by id, for the template recognised in the folder. */
  templatesById: Record<string, TemplateInfo>;
  /** Open the tree on a folder below the selected one. */
  onReveal: (location: string) => void;
  /** Called with each finished inspection (to badge the tree, and to word
   *  the footer). */
  onInspected: (location: string, result: FolderInspection | null) => void;
  /** The connection details to read `location` with, when it is in a
   *  private bucket. */
  storageFor?: (location: string) => RunStorageIn | null;
}

const Section: React.FC<{ title: string; description?: string; children: React.ReactNode }> = ({
  title,
  description,
  children,
}) => (
  <Stack gap={6}>
    <Stack gap={0}>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase">
        {title}
      </Text>
      {description && (
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      )}
    </Stack>
    {children}
  </Stack>
);

/** A folder's child, spelled the way the tree spells folders. */
function childLocation(location: string, name: string): string {
  return normalizeFolder(`${location}/${name}`);
}

const FILE_ICON: Array<[RegExp, string]> = [
  [/\.html?$/i, 'mdi:language-html5'],
  [/\.(tsv|csv|txt|tab)(\.gz)?$/i, 'mdi:file-delimited-outline'],
  [/\.(json|ya?ml|toml)$/i, 'mdi:code-json'],
  [/\.(png|jpe?g|svg|gif|tiff?)$/i, 'mdi:file-image-outline'],
  [/\.pdf$/i, 'mdi:file-pdf-box'],
  [/\.(gz|zip|tar|bz2|xz)$/i, 'mdi:folder-zip-outline'],
  [/\.(log|out|err)$/i, 'mdi:text-box-outline'],
  [/\.(bam|cram|sam|bai|vcf|bcf|fa|fasta|fq|fastq|bed|gtf|gff3?)(\.gz)?$/i, 'mdi:dna'],
];

function fileIcon(name: string): string {
  for (const [pattern, icon] of FILE_ICON) if (pattern.test(name)) return icon;
  return 'mdi:file-outline';
}

/** The run records of the folder, each said in words; `pipeline_info` opens
 *  onto what the engine wrote about the run. */
const RunRecords: React.FC<{
  result: FolderInspection;
  onOpen: (name: string) => void;
}> = ({ result, onOpen }) => {
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewId = useId();
  if (result.markers.length === 0) {
    return (
      <Text size="sm" c="dimmed" data-testid="browse-detail-markers">
        No pipeline_info folder and no MultiQC report here, so this does not look like the
        output of a pipeline run.
      </Text>
    );
  }
  const runInfo = result.run_info ?? null;
  return (
    <Stack gap="xs" data-testid="browse-detail-markers">
      {result.markers.map((marker) => {
        const meta = MARKER_META[marker];
        const isInfo = marker === 'pipeline_info';
        return (
          <Paper key={marker} withBorder radius="md" p="sm" data-marker={marker}>
            <Stack gap="xs">
              <Group gap="sm" wrap="nowrap" align="flex-start">
                <ThemeIcon variant="default" size="lg" radius="md">
                  <MarkerIcon marker={marker} size={18} />
                </ThemeIcon>
                <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                  <Text size="sm" fw={600} ff={isInfo ? 'monospace' : undefined}>
                    {meta?.label ?? marker}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {meta?.description ?? 'A record of the run.'}
                  </Text>
                </Stack>
                <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
                  {isInfo && runInfo && (
                    <Button
                      size="compact-xs"
                      variant="light"
                      leftSection={<Icon icon={previewOpen ? 'mdi:eye-off-outline' : 'mdi:eye-outline'} width={14} />}
                      onClick={() => setPreviewOpen((o) => !o)}
                      aria-expanded={previewOpen}
                      aria-controls={previewId}
                      data-testid="browse-detail-pipeline-info-toggle"
                    >
                      {previewOpen ? 'Hide' : 'Preview'}
                    </Button>
                  )}
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="gray"
                    rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                    onClick={() => onOpen(marker)}
                    data-testid={`browse-detail-open-${marker}`}
                  >
                    Open
                  </Button>
                </Group>
              </Group>
              {isInfo && !runInfo && (
                <Text size="xs" c="dimmed">
                  Depictio could not read the run from it.
                </Text>
              )}
              {isInfo && runInfo && (
                <Collapse in={previewOpen} id={previewId}>
                  <PipelineInfoPreview info={runInfo} folder={result.location} />
                </Collapse>
              )}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
};

/** "2 folders, 3 files", "at least" when the listing was cut short. */
function contentCounts(result: FolderInspection): string {
  const { folders, files } = result;
  return (
    `${plural(folders.count, 'folder')}, ${plural(files.count, 'file')}` +
    (result.truncated ? ' (at least)' : '')
  );
}

const RECORD_FOLDERS = new Set(['pipeline_info', 'multiqc']);

/** The folder's sub-folders, then its files, in one list: a folder opens on
 *  a click, a filter appears past a dozen entries. */
const ContentsList: React.FC<{ result: FolderInspection; onOpen: (name: string) => void }> = ({
  result,
  onOpen,
}) => {
  const [query, setQuery] = useState('');
  const { folders, files } = result;
  const total = folders.names.length + files.names.length;
  const q = query.trim().toLowerCase();
  const keep = (name: string) => !q || name.toLowerCase().includes(q);
  const shownFolders = folders.names.filter(keep);
  const shownFiles = files.names.filter(keep);
  const listed = folders.count + files.count;

  if (total === 0) {
    return (
      <Text size="sm" c="dimmed">
        This folder is empty.
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      {total > FILTER_FROM && (
        <TextInput
          size="xs"
          placeholder="Filter by name"
          leftSection={<Icon icon="mdi:magnify" width={14} />}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          data-testid="browse-detail-contents-filter"
        />
      )}
      <Paper withBorder radius="md">
        <ScrollArea.Autosize mah={300} type="auto" offsetScrollbars>
          <Stack gap={0} py={4}>
            {shownFolders.length > 0 && (
              <Stack gap={0} data-testid="browse-detail-folders">
                {shownFolders.map((name) => (
                  <NavLink
                    key={name}
                    component="button"
                    type="button"
                    onClick={() => onOpen(name)}
                    py={4}
                    label={
                      <Text size="sm" ff="monospace" truncate>
                        {name}
                      </Text>
                    }
                    leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                    rightSection={
                      <Group gap={6} wrap="nowrap">
                        {RECORD_FOLDERS.has(name) && (
                          <Badge
                            size="xs"
                            variant="light"
                            color="green"
                            radius="sm"
                            tt="none"
                            leftSection={<MarkerIcon marker={name} size={10} />}
                          >
                            run record
                          </Badge>
                        )}
                        <Icon icon="mdi:chevron-right" width={14} />
                      </Group>
                    }
                    aria-label={`Open ${name}`}
                    data-testid="browse-detail-folder"
                    data-name={name}
                  />
                ))}
              </Stack>
            )}
            {shownFolders.length > 0 && shownFiles.length > 0 && <Divider my={4} />}
            {shownFiles.length > 0 && (
              <Stack gap={0} data-testid="browse-detail-files">
                {shownFiles.map((name) => (
                  <Group key={name} gap="xs" wrap="nowrap" px="sm" py={4}>
                    <Icon icon={fileIcon(name)} width={16} style={{ flexShrink: 0 }} />
                    <Text size="sm" ff="monospace" truncate>
                      {name}
                    </Text>
                  </Group>
                ))}
              </Stack>
            )}
            {shownFolders.length + shownFiles.length === 0 && (
              <Text size="sm" c="dimmed" px="sm" py={4}>
                Nothing here matches &ldquo;{query.trim()}&rdquo;.
              </Text>
            )}
          </Stack>
        </ScrollArea.Autosize>
      </Paper>
      {listed > total && (
        <Text size="xs" c="dimmed">
          The first {total} of {plural(listed, 'entry', 'entries')}.
        </Text>
      )}
    </Stack>
  );
};

/** The folder's contents. Folded under a toggle while a search's hits are
 *  listed above it. */
const ContentsSection: React.FC<{
  result: FolderInspection;
  foldable: boolean;
  open: boolean;
  onToggle: () => void;
  onOpen: (name: string) => void;
}> = ({ result, foldable, open, onToggle, onOpen }) => {
  const contentsId = useId();
  const list = <ContentsList result={result} onOpen={onOpen} />;

  if (!foldable) {
    return (
      <Stack gap={6}>
        <Group gap={6} wrap="nowrap">
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            Contents
          </Text>
          <Text size="xs" c="dimmed" data-testid="browse-detail-counts">
            {contentCounts(result)}
          </Text>
        </Group>
        {list}
      </Stack>
    );
  }
  return (
    <Stack gap={6}>
      <UnstyledButton
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={contentsId}
        data-testid="browse-detail-contents-toggle"
      >
        <Group gap={4} wrap="nowrap">
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
          <Text span size="xs" fw={700} c="dimmed" tt="uppercase">
            Contents
          </Text>
          <Text span size="xs" c="dimmed" data-testid="browse-detail-counts">
            ({contentCounts(result)})
          </Text>
        </Group>
      </UnstyledButton>
      <Collapse in={open} id={contentsId} data-testid="browse-detail-contents">
        {list}
      </Collapse>
    </Stack>
  );
};

/** The checks of a recognised folder, against the template detected in it. */
const BrowseChecks: React.FC<{
  result: FolderInspection;
  templateName: string | null;
  templateEngine: string | null;
  storage: RunStorageIn | null;
}> = ({ result, templateName, templateEngine, storage }) => {
  const detected = result.detected;
  const templateId = detected?.template_id ?? null;
  const plan = useRunPlan(result.location, templateId, storage);
  return (
    <RunChecks
      location={result.location}
      run={detected}
      templateId={templateId}
      templateName={templateName}
      templateEngine={templateEngine}
      match={runTemplateMatch({
        runPipeline: detected?.pipeline,
        runVersion: detected?.version,
        templateId,
        detectedTemplateId: templateId,
        detectedMatch: detected?.match ?? null,
      })}
      plan={plan}
      runInfo={result.run_info ?? null}
      listingCut={result.truncated}
      storage={storage}
      testIdPrefix="browse-detail"
    />
  );
};

export const FolderDetailPane: React.FC<FolderDetailPaneProps> = ({
  location,
  templatesById,
  onReveal,
  onInspected,
  storageFor,
}) => {
  const [inspect, setInspect] = useState<InspectState>({ status: 'loading' });
  const [find, setFind] = useState<FindState | null>(null);
  /** The contents, folded while a search's hits are listed. */
  const [contentsOpen, setContentsOpen] = useState(false);

  useEffect(() => {
    if (!location) return undefined;
    const controller = new AbortController();
    setInspect({ status: 'loading' });
    setContentsOpen(false);
    inspectFolder(location, { signal: controller.signal, storage: storageFor?.(location) ?? null })
      .then((result) => {
        if (controller.signal.aborted) return;
        setInspect({ status: 'ready', result });
        onInspected(location, result);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setInspect({ status: 'error', error: err.message || 'This folder could not be read.' });
        onInspected(location, null);
      });
    return () => controller.abort();
    // `onInspected` and `storageFor` are callback props; only the location
    // starts a request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location]);

  const runFind = () => {
    if (!location) return;
    const root = location;
    setFind({ status: 'loading', root });
    setContentsOpen(false);
    findRunFolders(root, { storage: storageFor?.(root) ?? null })
      .then((result) => setFind((cur) => (cur?.root === root ? { status: 'ready', root, result } : cur)))
      .catch((err: Error) =>
        setFind((cur) =>
          cur?.root === root
            ? { status: 'error', root, error: err.message || 'The search failed.' }
            : cur,
        ),
      );
  };

  // The hits stay listed while the reader walks through them: they belong to
  // the folder searched, and to every folder below it.
  const activeFind = useMemo(() => {
    if (!find || !location) return null;
    return relativeToFolder(normalizeFolder(find.root), normalizeFolder(location)) !== null
      ? find
      : null;
  }, [find, location]);

  if (!location) {
    return (
      <Stack align="center" justify="center" gap="xs" mih={240} data-testid="browse-detail-empty">
        <ThemeIcon variant="light" color="gray" size="xl" radius="xl">
          <Icon icon="mdi:folder-search-outline" width={24} />
        </ThemeIcon>
        <Text size="sm" c="dimmed" ta="center" maw={320}>
          Select a folder in the tree, or type its path above, to see what it holds and which
          pipeline made it.
        </Text>
      </Stack>
    );
  }

  const result = inspect.status === 'ready' ? inspect.result : null;
  const detected = result?.detected ?? null;
  const template = detected?.template_id ? templatesById[detected.template_id] ?? null : null;
  const openChild = (name: string) => onReveal(childLocation(result?.location ?? location, name));

  return (
    <Stack gap="md" data-testid="browse-detail" data-path={location}>
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon variant="light" color="gray" size="lg" radius="md">
              <Icon icon={result?.looks_like_run ? 'mdi:folder-check-outline' : 'mdi:folder-outline'} width={20} />
            </ThemeIcon>
            <Text fw={700} size="lg" style={{ wordBreak: 'break-word' }} data-testid="browse-detail-name">
              {result?.name || folderName(location)}
            </Text>
          </Group>
          {result?.looks_like_run && <FlowBadge status="run-folder" testId="browse-detail-run-badge" />}
        </Group>
        <FolderPath location={result?.location ?? location} maxLength={96} testId="browse-selected" />
      </Stack>

      {inspect.status === 'loading' && (
        <Stack gap="xs" data-testid="browse-detail-loading">
          <Skeleton h={14} w="60%" />
          <Skeleton h={14} w="40%" />
          <Skeleton h={14} w="70%" />
        </Stack>
      )}

      {inspect.status === 'error' && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
          title="This folder could not be read"
          data-testid="browse-detail-error"
        >
          {inspect.error}
        </Alert>
      )}

      {result && (
        <>
          {detected?.pipeline ? (
            <BrowseChecks
              result={result}
              templateName={template?.name ?? null}
              templateEngine={template?.engine ?? null}
              storage={storageFor?.(result.location) ?? null}
            />
          ) : (
            <Text size="sm" c="dimmed" data-testid="browse-detail-not-recognised">
              {result.looks_like_run
                ? 'This folder has a pipeline_info folder or a MultiQC report, but neither names a pipeline Depictio has a template for.'
                : 'Depictio recognises no pipeline run here.'}
            </Text>
          )}

          <Section
            title="Why this is a run folder"
            description="A pipeline run leaves records beside its results; Depictio looks for these two."
          >
            <RunRecords result={result} onOpen={openChild} />
          </Section>
        </>
      )}

      <Divider />

      <Section title="Run folders below this one">
        {activeFind ? (
          <RunSearchResults
            find={activeFind}
            location={location}
            onReveal={onReveal}
            onClear={() => setFind(null)}
          />
        ) : (
          <Group>
            <Button
              size="xs"
              variant="light"
              leftSection={<Icon icon="mdi:folder-search-outline" width={14} />}
              onClick={runFind}
              data-testid="browse-find-runs"
            >
              Find run folders here
            </Button>
          </Group>
        )}
      </Section>

      {result && (
        <ContentsSection
          result={result}
          foldable={activeFind !== null}
          open={contentsOpen}
          onToggle={() => setContentsOpen((open) => !open)}
          onOpen={openChild}
        />
      )}
    </Stack>
  );
};
