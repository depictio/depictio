/**
 * The right-hand side of the folder browser: what the selected folder holds
 * and what Depictio recognises in it, read with `inspectFolder` on selection
 * (a newer selection cancels the request still in flight). From here the
 * reader can also look for run folders below the selected one: once a search
 * ran, its hits (`RunSearchResults`) come first and the folder's contents
 * fold under a toggle. A folder in a private bucket is read, and searched,
 * with its connection details.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Collapse,
  Divider,
  Group,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
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
import type { FolderInspection, RunStorageIn } from 'depictio-react-core';

import { FlowBadge } from '../FlowBadge';
import { FolderPath } from '../FolderPath';
import { plural } from '../plural';
import { RunMadeBy, TemplateUsed } from '../RunIdentity';
import { RunMarkers } from '../RunMarkers';
import { RunSearchResults } from './RunSearchResults';
import type { FindState } from './RunSearchResults';

const NAMES_SHOWN = 12;

type InspectState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; result: FolderInspection };

interface FolderDetailPaneProps {
  /** The selected folder; null shows a hint. */
  location: string | null;
  /** Template names by id, for the template recognised in the folder. */
  templateTitles: Record<string, string>;
  /** Open the tree on a run folder found below the selected one. */
  onReveal: (location: string) => void;
  /** Called with each finished inspection (to badge the tree, and to word
   *  the footer). */
  onInspected: (location: string, result: FolderInspection | null) => void;
  /** The connection details to read `location` with, when it is in a
   *  private bucket. */
  storageFor?: (location: string) => RunStorageIn | null;
}

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <Stack gap={6}>
    <Text size="xs" fw={700} c="dimmed" tt="uppercase">
      {title}
    </Text>
    {children}
  </Stack>
);

const NameList: React.FC<{ names: string[]; count: number; icon: string; testId: string }> = ({
  names,
  count,
  icon,
  testId,
}) => {
  const shown = names.slice(0, NAMES_SHOWN);
  const more = count - shown.length;
  return (
    <Stack gap={2} data-testid={testId}>
      {shown.map((name) => (
        <Group key={name} gap={6} wrap="nowrap">
          <Icon icon={icon} width={14} style={{ flexShrink: 0 }} />
          <Text size="xs" ff="monospace" truncate>
            {name}
          </Text>
        </Group>
      ))}
      {more > 0 && (
        <Text size="xs" c="dimmed">
          and {more} more
        </Text>
      )}
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

/** The folder's sub-folders and files: their counts, then the first names.
 *  Folded under a toggle while a search's hits are listed above it. */
const ContentsSection: React.FC<{
  result: FolderInspection;
  foldable: boolean;
  open: boolean;
  onToggle: () => void;
}> = ({ result, foldable, open, onToggle }) => {
  const contentsId = useId();
  const { folders, files } = result;
  const lists =
    folders.names.length > 0 || files.names.length > 0 ? (
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        {folders.names.length > 0 && (
          <NameList
            names={folders.names}
            count={folders.count}
            icon="mdi:folder-outline"
            testId="browse-detail-folders"
          />
        )}
        {files.names.length > 0 && (
          <NameList
            names={files.names}
            count={files.count}
            icon="mdi:file-outline"
            testId="browse-detail-files"
          />
        )}
      </SimpleGrid>
    ) : null;

  if (!foldable) {
    return (
      <Section title="Contents">
        <Text size="sm" data-testid="browse-detail-counts">
          {contentCounts(result)}
        </Text>
        {lists}
      </Section>
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
        {lists}
      </Collapse>
    </Stack>
  );
};

export const FolderDetailPane: React.FC<FolderDetailPaneProps> = ({
  location,
  templateTitles,
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
        <FolderPath location={result?.location ?? location} maxLength={72} testId="browse-detail-path" />
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
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" data-testid="browse-detail-detected">
              <RunMadeBy run={detected} testIdPrefix="browse-detail" />
              <TemplateUsed
                templateId={detected.template_id}
                title={detected.template_id ? templateTitles[detected.template_id] ?? null : null}
                match={runTemplateMatch({
                  runPipeline: detected.pipeline,
                  runVersion: detected.version,
                  templateId: detected.template_id,
                  detectedTemplateId: detected.template_id,
                  detectedMatch: detected.match ?? null,
                })}
                runVersion={detected.version}
                testIdPrefix="browse-detail"
              />
            </SimpleGrid>
          ) : (
            <Text size="sm" c="dimmed" data-testid="browse-detail-not-recognised">
              {result.looks_like_run
                ? 'This folder holds run records, but none of them names a pipeline Depictio knows.'
                : 'No run records here: a run folder holds a pipeline_info folder or a MultiQC report.'}
            </Text>
          )}

          <Section title="Run records">
            {result.markers.length > 0 ? (
              <RunMarkers markers={result.markers} testId="browse-detail-markers" />
            ) : (
              <Text size="xs" c="dimmed">
                None found.
              </Text>
            )}
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
        />
      )}
    </Stack>
  );
};
