/**
 * What a collection would ingest: how many files (or stores, for zarr
 * bioimages and SpatialData tables), the first of them (each marked when its
 * schema differs from the first file's), whether they agree on a schema,
 * indexes not found, run folders, a genomic tracks manifest's checks, and
 * the server's warnings.
 */
import React from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderMatchResult, BuilderSchemaMismatch, BuilderTracksCheck } from 'depictio-react-core';

import { matchResultOf } from './useBuilderMatch';
import type { MatchState } from './useBuilderMatch';

/** "missing a, b · extra c · d: int64 → str". */
function mismatchText(m: BuilderSchemaMismatch): string {
  const parts: string[] = [];
  if (m.missing.length) parts.push(`missing ${m.missing.join(', ')}`);
  if (m.extra.length) parts.push(`extra ${m.extra.join(', ')}`);
  const changed = Object.entries(m.changed).map(([column, [from, to]]) => `${column}: ${from} → ${to}`);
  if (changed.length) parts.push(changed.join(', '));
  return parts.join(' · ') || 'differs';
}

function agreementText(result: BuilderMatchResult): string {
  if (result.count === 1) return 'Schema read for the matched file.';
  if (result.truncated) return `The files checked share one schema (${result.count} files in all).`;
  return `All ${result.count} files share one schema.`;
}

/** A list of paths under a one-line heading, as an alert. */
const PathList: React.FC<{ color: string; title: string; paths: string[]; testId: string }> = ({
  color,
  title,
  paths,
  testId,
}) =>
  paths.length ? (
    <Alert color={color} variant="light" p="xs" icon={<Icon icon="mdi:alert" width={14} />} data-testid={testId}>
      <Text size="xs" fw={600} mb={2}>
        {title}
      </Text>
      <ScrollArea.Autosize mah={96} type="auto">
        <Stack gap={0}>
          {paths.map((p) => (
            <Text key={p} size="xs" ff="monospace" c="dimmed">
              {p}
            </Text>
          ))}
        </Stack>
      </ScrollArea.Autosize>
    </Alert>
  ) : null;

/** What `/match` checked of a genomic tracks manifest. */
const TracksChecks: React.FC<{ tracks: BuilderTracksCheck }> = ({ tracks }) => {
  const accent = useBrandAccents();
  const absolute = tracks.absolute_uris ?? [];
  const clean =
    !tracks.missing_uri_column &&
    !tracks.unknown_format.length &&
    !tracks.duplicate_uris.length &&
    !tracks.missing_files.length &&
    !tracks.missing_indexes.length &&
    !absolute.length;
  return (
    <Stack gap={6} data-testid="builder-matches-tracks">
      <Group gap={6} wrap="nowrap">
        <Icon
          icon={clean ? 'mdi:check-circle' : 'mdi:playlist-check'}
          width={15}
          color={clean ? `var(--mantine-color-${accent.secondary}-6)` : 'var(--mantine-color-dimmed)'}
        />
        <Text size="xs" fw={600}>
          Manifest: {tracks.rows.toLocaleString()} track{tracks.rows === 1 ? '' : 's'}
          {tracks.truncated ? ' (the first ones checked)' : ''}
        </Text>
      </Group>
      {tracks.missing_uri_column && (
        <Alert color="red" variant="light" p="xs" icon={<Icon icon="mdi:alert-circle-outline" width={14} />}>
          <Text size="xs">The manifest has no file column by that name: pick the column holding each track.</Text>
        </Alert>
      )}
      <PathList
        color="red"
        title="Absolute paths: ingestion does not keep them inside the data root"
        paths={absolute}
        testId="builder-matches-tracks-absolute"
      />
      <PathList color="yellow" title="Files not found" paths={tracks.missing_files} testId="builder-matches-tracks-missing" />
      <PathList
        color="yellow"
        title="Indexes not found"
        paths={tracks.missing_indexes}
        testId="builder-matches-tracks-missing-indexes"
      />
      <PathList color="yellow" title="Listed twice" paths={tracks.duplicate_uris} testId="builder-matches-tracks-duplicates" />
      {tracks.unknown_format.length > 0 && (
        <Text size="xs" c="yellow.8">
          Unknown formats: {tracks.unknown_format.join(', ')}
        </Text>
      )}
    </Stack>
  );
};

export const MatchesPanel: React.FC<{
  state: MatchState;
  /** Ask again with nothing changed; offered on S3 roots. */
  onRefresh?: () => void;
  /** The matches are stores, when the answer does not say. */
  stores?: boolean;
}> = ({ state, onRefresh, stores = false }) => {
  const accent = useBrandAccents();
  const result = matchResultOf(state);
  const loading = state.status === 'loading';
  const noun = result?.stores ?? stores ? 'store' : 'file';

  if (state.status === 'idle') {
    return (
      <Text size="xs" c="dimmed" data-testid="builder-matches-idle">
        Give a file or a pattern to see what it matches.
      </Text>
    );
  }

  const issues = new Map((result?.mismatches ?? []).map((m) => [m.file, m]));
  const missingIndexes = new Set(result?.missing_indexes ?? []);

  return (
    <Stack gap={6} data-testid="builder-matches" data-state={state.status} aria-live="polite">
      <Group gap="xs">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          Matches
        </Text>
        {result && (
          <Badge
            size="sm"
            variant="light"
            color={result.count === 0 ? 'red' : result.consistent === false ? 'yellow' : accent.secondary}
            data-testid="builder-matches-count"
            data-count={result.count}
          >
            {result.count.toLocaleString()} {noun}
            {result.count === 1 ? '' : 's'}
            {result.truncated ? '+' : ''}
          </Badge>
        )}
        {result && result.runs.length > 0 && (
          <Tooltip label={result.runs.join(', ')} multiline maw={360} withArrow>
            <Badge size="sm" variant="light" color="gray" tt="none">
              {result.runs.length} run{result.runs.length === 1 ? '' : 's'}
            </Badge>
          </Tooltip>
        )}
        {loading && <Loader size={12} />}
        {onRefresh && (
          <Tooltip label="Match again: S3 listings are not watched" withArrow>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              ml="auto"
              onClick={onRefresh}
              aria-label="Match again"
              data-testid="builder-matches-refresh"
            >
              <Icon icon="mdi:refresh" width={15} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>

      {state.status === 'error' && (
        <Alert color="red" variant="light" p="xs" icon={<Icon icon="mdi:alert-circle-outline" width={14} />}>
          <Text size="xs">{state.error}</Text>
        </Alert>
      )}

      {result && result.count === 0 && (
        <Text size="xs" c="dimmed">
          Nothing in the root matches. A pattern without a <code>/</code> matches file names; one
          with a <code>/</code> matches paths from the root.
        </Text>
      )}

      {result && result.files.length > 0 && (
        <Paper withBorder radius="sm">
          <ScrollArea.Autosize mah={180} type="auto">
            <Stack gap={0}>
              {result.files.map((file, i) => {
                const issue = issues.get(file);
                const noIndex = missingIndexes.has(file);
                const flagged = Boolean(issue) || noIndex;
                return (
                  <Group
                    key={file}
                    gap={6}
                    wrap="nowrap"
                    px="sm"
                    py={3}
                    style={{
                      borderTop: i === 0 ? undefined : '1px solid var(--mantine-color-default-border)',
                    }}
                    data-testid="builder-matches-file"
                    data-path={file}
                  >
                    <Icon
                      icon={flagged ? 'mdi:alert' : 'mdi:check'}
                      width={13}
                      color={flagged ? 'var(--mantine-color-yellow-6)' : `var(--mantine-color-${accent.secondary}-6)`}
                      style={{ flexShrink: 0 }}
                    />
                    <Text size="xs" ff="monospace" truncate style={{ minWidth: 0 }}>
                      {file}
                    </Text>
                    {noIndex && (
                      <Badge size="xs" variant="light" color="yellow" tt="none" style={{ flexShrink: 0 }}>
                        no index
                      </Badge>
                    )}
                  </Group>
                );
              })}
            </Stack>
          </ScrollArea.Autosize>
        </Paper>
      )}

      {result && result.count > result.files.length && (
        <Text size="xs" c="dimmed">
          The first {result.files.length.toLocaleString()} are listed.
        </Text>
      )}

      {result && result.consistent === true && result.count > 0 && (
        <Group gap={6} wrap="nowrap">
          <Icon icon="mdi:check-circle" width={15} color={`var(--mantine-color-${accent.secondary}-6)`} />
          <Text size="xs" fw={600} c={accent.secondary}>
            {agreementText(result)}
          </Text>
        </Group>
      )}

      {result && result.consistent === false && result.mismatches.length > 0 && (
        <Alert color="yellow" variant="light" p="xs" icon={<Icon icon="mdi:alert" width={14} />}>
          <Text size="xs" fw={600} mb={2}>
            Schemas differ across the files: the collection can still be created.
          </Text>
          <Stack gap={0}>
            {result.mismatches.map((m) => (
              <Text key={m.file} size="xs" c="dimmed">
                <b>{m.file}</b>: {mismatchText(m)}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {result && result.missing_indexes.length > 0 && (
        <Text size="xs" c="yellow.8">
          {result.missing_indexes.length} file{result.missing_indexes.length === 1 ? ' has' : 's have'} no
          index next to {result.missing_indexes.length === 1 ? 'it' : 'them'}.
        </Text>
      )}

      {result?.tracks && <TracksChecks tracks={result.tracks} />}

      {result?.warnings.map((w) => (
        <Group key={w} gap={6} wrap="nowrap" align="flex-start">
          <Icon icon="mdi:information-outline" width={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <Text size="xs" c="dimmed">
            {w}
          </Text>
        </Group>
      ))}
    </Stack>
  );
};
