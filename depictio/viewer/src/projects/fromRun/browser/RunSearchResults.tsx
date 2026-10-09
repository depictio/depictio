/**
 * The hits of a run search in the folder browser's detail pane: one row per
 * run folder found below the searched one, each saying who made the run in
 * the words of the rest of the flow (workflow mark, pipeline, version, run
 * records).
 */
import React from 'react';
import { Anchor, Group, Loader, NavLink, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  folderName,
  formatVersion,
  isS3Location,
  normalizeFolder,
  splitTemplateId,
} from 'depictio-react-core';
import type { FindRunsResult, FoundRunFolder } from 'depictio-react-core';

import { TemplateSourceLogo } from '../../template';
import { FlowBadge } from '../FlowBadge';
import { FolderPath } from '../FolderPath';
import { plural } from '../plural';
import { RunMarkers } from '../RunMarkers';

export type FindState =
  | { status: 'loading'; root: string }
  | { status: 'error'; root: string; error: string }
  | { status: 'ready'; root: string; result: FindRunsResult };

/** `find_runs` lists the searched folder itself as `relative: "."` when it
 *  is a run folder. */
const isSearchedFolder = (relative: string | null | undefined): boolean =>
  relative === '.' || relative === './';

/** The second line of a run search hit: what made the run when the search
 *  recognised it (detection runs for the first hits of a local search only),
 *  else that selecting it tells; the run records found in both cases. */
const HitIdentity: React.FC<{ run: FoundRunFolder }> = ({ run }) => {
  const d = run.detected;
  return (
    <Group component="span" gap={6} wrap="wrap" mt={4} style={{ rowGap: 4 }}>
      {d?.pipeline ? (
        <>
          <TemplateSourceLogo source={splitTemplateId(d.pipeline).source} size={16} />
          <Text
            span
            size="xs"
            fw={600}
            c="var(--mantine-color-text)"
            data-testid="browse-find-hit-pipeline"
          >
            {d.pipeline}
          </Text>
          <Text span size="xs" ff="monospace" data-testid="browse-find-hit-version">
            {d.version ? formatVersion(d.version) : 'version unknown'}
          </Text>
        </>
      ) : (
        <>
          <FlowBadge status="run-folder" />
          <Text span size="xs" c="dimmed" data-testid="browse-find-hit-unidentified">
            Select it to identify the pipeline
          </Text>
        </>
      )}
      {run.markers.length > 0 && <RunMarkers markers={run.markers} />}
    </Group>
  );
};

/** "2 run folders under results, 40 folders looked through." */
function findSummary(result: FindRunsResult, root: string, unit: string): string {
  const found =
    result.runs.length === 0
      ? `No run folder found under ${folderName(root)}`
      : `${plural(result.runs.length, 'run folder')} under ${folderName(root)}`;
  return `${found}, ${plural(result.scanned, unit)} looked through.`;
}

interface RunSearchResultsProps {
  find: FindState;
  /** The selected folder: the searched one, or a folder below it. */
  location: string;
  onReveal: (location: string) => void;
  onClear: () => void;
}

export const RunSearchResults: React.FC<RunSearchResultsProps> = ({
  find,
  location,
  onReveal,
  onClear,
}) => {
  const unit = isS3Location(location) ? 'object' : 'folder';
  return (
    <Stack gap="xs" data-testid="browse-find-results" data-state={find.status} aria-live="polite">
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
          <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
            <Text size="xs" c="dimmed" data-testid="browse-find-summary">
              {findSummary(find.result, find.root, unit)}
            </Text>
            <Anchor
              component="button"
              type="button"
              size="xs"
              onClick={onClear}
              style={{ flexShrink: 0 }}
            >
              Clear the results
            </Anchor>
          </Group>
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
                    <Text span size="sm" fw={500}>
                      This folder
                    </Text>
                  ) : (
                    <FolderPath
                      location={run.location}
                      label={run.relative || run.name}
                      withCopy={false}
                      maxLength={56}
                    />
                  )
                }
                description={<HitIdentity run={run} />}
                leftSection={<Icon icon="mdi:folder-check-outline" width={16} />}
                onClick={() => onReveal(run.location)}
                data-testid="browse-find-hit"
                data-path={run.location}
                data-detected={run.detected?.pipeline ? 'true' : 'false'}
              />
            ))}
          </Stack>
        </>
      )}
    </Stack>
  );
};
