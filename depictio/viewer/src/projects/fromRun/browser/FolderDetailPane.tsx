/**
 * The right-hand side of the folder browser: what the selected folder holds
 * and what Depictio recognises in it, read with `inspectFolder` on selection
 * (a newer selection cancels the request still in flight). From here the
 * reader can also look for run folders below the selected one.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Code,
  Divider,
  Group,
  Loader,
  NavLink,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  findRunFolders,
  folderName,
  formatVersion,
  inspectFolder,
  isS3Location,
  normalizeFolder,
  relativeToFolder,
  runTemplateMatch,
} from 'depictio-react-core';
import type { FindRunsResult, FolderInspection } from 'depictio-react-core';

import { FlowBadge } from '../FlowBadge';
import { FolderPath } from '../FolderPath';
import { RunMadeBy, TemplateUsed } from '../RunIdentity';

const NAMES_SHOWN = 12;

/** `find_runs` lists the searched folder itself as `relative: "."` when it
 *  is a run folder. */
const isSearchedFolder = (relative: string | null | undefined): boolean =>
  relative === '.' || relative === './';

type InspectState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; result: FolderInspection };

type FindState =
  | { status: 'loading'; root: string }
  | { status: 'error'; root: string; error: string }
  | { status: 'ready'; root: string; result: FindRunsResult };

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

export const FolderDetailPane: React.FC<FolderDetailPaneProps> = ({
  location,
  templateTitles,
  onReveal,
  onInspected,
}) => {
  const [inspect, setInspect] = useState<InspectState>({ status: 'loading' });
  const [find, setFind] = useState<FindState | null>(null);

  useEffect(() => {
    if (!location) return undefined;
    const controller = new AbortController();
    setInspect({ status: 'loading' });
    inspectFolder(location, { signal: controller.signal })
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
    // `onInspected` is a callback prop; only the location starts a request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location]);

  const runFind = () => {
    if (!location) return;
    const root = location;
    setFind({ status: 'loading', root });
    findRunFolders(root)
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
  const findApplies = useMemo(() => {
    if (!find || !location) return false;
    return relativeToFolder(normalizeFolder(find.root), normalizeFolder(location)) !== null;
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
  const unit = isS3Location(location) ? 'object' : 'folder';

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
              <RunMadeBy
                run={{ pipeline: detected.pipeline, version: detected.version, engine: detected.engine }}
                testIdPrefix="browse-detail"
              />
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
                : 'No run records here: a run folder holds a pipeline_info or multiqc folder.'}
            </Text>
          )}

          <Section title="Run records">
            {result.markers.length > 0 ? (
              <Group gap={6} wrap="wrap" data-testid="browse-detail-markers">
                {result.markers.map((marker) => (
                  <Code key={marker}>{marker}</Code>
                ))}
              </Group>
            ) : (
              <Text size="xs" c="dimmed">
                None found.
              </Text>
            )}
          </Section>

          <Section title="Contents">
            <Text size="sm" data-testid="browse-detail-counts">
              {result.folders.count} folder{result.folders.count === 1 ? '' : 's'},{' '}
              {result.files.count} file{result.files.count === 1 ? '' : 's'}
              {result.truncated ? ' (at least)' : ''}
            </Text>
            {(result.folders.names.length > 0 || result.files.names.length > 0) && (
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                {result.folders.names.length > 0 && (
                  <NameList
                    names={result.folders.names}
                    count={result.folders.count}
                    icon="mdi:folder-outline"
                    testId="browse-detail-folders"
                  />
                )}
                {result.files.names.length > 0 && (
                  <NameList
                    names={result.files.names}
                    count={result.files.count}
                    icon="mdi:file-outline"
                    testId="browse-detail-files"
                  />
                )}
              </SimpleGrid>
            )}
          </Section>
        </>
      )}

      <Divider />

      <Section title="Run folders below this one">
        {findApplies && find ? (
          <Stack gap="xs" data-testid="browse-find-results" data-state={find.status}>
            {find.status === 'loading' && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm" c="dimmed">
                  Looking for run folders under {folderName(find.root)}...
                </Text>
              </Group>
            )}
            {find.status === 'error' && (
              <Text size="sm" c="red" data-testid="browse-find-error">
                {find.error}
              </Text>
            )}
            {find.status === 'ready' && (
              <>
                <Text size="xs" c="dimmed" data-testid="browse-find-summary">
                  {find.result.runs.length === 0
                    ? `No run folder found under ${folderName(find.root)}`
                    : `${find.result.runs.length} run folder${find.result.runs.length === 1 ? '' : 's'} under ${folderName(find.root)}`}
                  {`, ${find.result.scanned} ${unit}${find.result.scanned === 1 ? '' : 's'} looked through.`}
                </Text>
                {find.result.truncated && (
                  <Text size="xs" c="dimmed" data-testid="browse-find-truncated">
                    The search stopped at its limits, so there may be more run folders. Search
                    from a folder further down to see them.
                  </Text>
                )}
                <Stack gap={0}>
                  {find.result.runs.map((run) => (
                    <NavLink
                      key={run.location}
                      component="button"
                      type="button"
                      active={normalizeFolder(run.location) === normalizeFolder(location)}
                      label={
                        isSearchedFolder(run.relative) ? (
                          <Text size="sm" fw={500}>
                            This folder
                          </Text>
                        ) : (
                          <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>
                            {run.relative || run.name}
                          </Text>
                        )
                      }
                      description={
                        run.detected?.pipeline
                          ? `${run.detected.pipeline}${run.detected.version ? ` ${formatVersion(run.detected.version)}` : ''}`
                          : run.markers.join(', ')
                      }
                      leftSection={<Icon icon="mdi:folder-check-outline" width={16} />}
                      onClick={() => onReveal(run.location)}
                      data-testid="browse-find-hit"
                      data-path={run.location}
                    />
                  ))}
                </Stack>
                <Anchor component="button" type="button" size="xs" onClick={() => setFind(null)}>
                  Clear the results
                </Anchor>
              </>
            )}
          </Stack>
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
    </Stack>
  );
};
