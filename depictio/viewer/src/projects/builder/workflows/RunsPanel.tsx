/**
 * What the runs regex takes in, read from the folders as the scan will read
 * them: how many runs, the layout their files share (a `*` stands for a name
 * that belongs to one run, a sample), and the runs that depart from it. It
 * re-reads when the regex changes, so typing shows its effect.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Anchor, Badge, Collapse, Group, Loader, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { builderRunsOverview } from 'depictio-react-core';
import type { BuilderRootSpec, BuilderRunsOverview } from 'depictio-react-core';

const READ_DELAY_MS = 400;

type State =
  | { status: 'idle' }
  | { status: 'loading'; previous: BuilderRunsOverview | null }
  | { status: 'ready'; overview: BuilderRunsOverview }
  | { status: 'error'; message: string };

function useRunsOverview(root: BuilderRootSpec, regex: string): State {
  const [state, setState] = useState<State>({ status: 'idle' });
  const location = root.data_root;
  const storageKey = JSON.stringify(root.storage ?? null);

  useEffect(() => {
    const trimmed = regex.trim();
    if (!trimmed) {
      setState({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setState((prev) => ({
      status: 'loading',
      previous: prev.status === 'ready' ? prev.overview : prev.status === 'loading' ? prev.previous : null,
    }));
    const timer = window.setTimeout(() => {
      builderRunsOverview(root, trimmed, { signal: controller.signal })
        .then((overview) => {
          if (!controller.signal.aborted) setState({ status: 'ready', overview });
        })
        .catch((err: Error) => {
          if (!controller.signal.aborted) setState({ status: 'error', message: err.message });
        });
    }, READ_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // `root.storage` is a fresh object per render; its key decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location, storageKey, regex]);

  return state;
}

const Chips: React.FC<{ names: string[]; total: number; dimmed?: boolean }> = ({ names, total, dimmed }) => (
  <Group gap={4} wrap="wrap">
    {names.map((name) => (
      <Badge key={name} size="sm" variant={dimmed ? 'outline' : 'light'} color="gray" tt="none" ff="monospace">
        {name}
      </Badge>
    ))}
    {total > names.length && (
      <Text size="xs" c="dimmed">
        and {total - names.length} more
      </Text>
    )}
  </Group>
);

export const RunsPanel: React.FC<{ root: BuilderRootSpec; regex: string }> = ({ root, regex }) => {
  const state = useRunsOverview(root, regex);
  const [showRuns, setShowRuns] = useState(false);
  const [showDiffs, setShowDiffs] = useState(false);

  if (state.status === 'idle') return null;
  if (state.status === 'error') {
    return (
      <Alert color="red" variant="light" p="xs" data-testid="builder-runs-error">
        <Text size="xs">{state.message}</Text>
      </Alert>
    );
  }
  const overview = state.status === 'ready' ? state.overview : state.previous;
  if (!overview) {
    return (
      <Group gap={6} data-testid="builder-runs-panel" data-state="loading">
        <Loader size={12} />
        <Text size="xs" c="dimmed">
          Reading the runs...
        </Text>
      </Group>
    );
  }
  const loading = state.status === 'loading';
  const none = overview.runs_total === 0;
  const uniform = !none && overview.deviating_total === 0;
  const total = overview.runs_read;

  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      style={{ opacity: loading ? 0.6 : 1 }}
      data-testid="builder-runs-panel"
      data-state={none ? 'none' : uniform ? 'consistent' : 'mixed'}
    >
      <Stack gap="xs">
        <Group gap="xs" wrap="wrap">
          <Icon icon="mdi:folder-multiple-outline" width={18} />
          <Text size="sm" fw={600} data-testid="builder-runs-count">
            {overview.runs_total} run{overview.runs_total === 1 ? '' : 's'} taken in
          </Text>
          {overview.skipped.length > 0 && (
            <Text size="xs" c="dimmed">
              {overview.skipped.length} other folder{overview.skipped.length === 1 ? '' : 's'} left out
            </Text>
          )}
          {loading && <Loader size={12} />}
          <Badge
            ml="auto"
            size="sm"
            variant="light"
            color={none ? 'red' : uniform ? 'green' : 'yellow'}
            tt="none"
            leftSection={
              <Icon icon={none ? 'mdi:alert-circle-outline' : uniform ? 'mdi:check' : 'mdi:alert-outline'} width={12} />
            }
            data-testid="builder-runs-status"
          >
            {none
              ? 'No folder matches the regex'
              : uniform
                ? `Same layout in ${overview.runs_total === total ? 'every run' : `the ${total} runs read`}`
                : `${overview.deviating_total} of ${total} runs differ`}
          </Badge>
        </Group>

        {none && (
          <Text size="xs" c="dimmed">
            The regex is read against the name of each folder directly under the data root. Press Detect to
            have it read from the folders.
          </Text>
        )}

        {overview.layout.length > 0 && (
          <Stack gap={4} data-testid="builder-runs-layout">
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              What each run contains
            </Text>
            <Text size="xs" c="dimmed">
              Every file of the {total} runs read ({overview.files.toLocaleString()} in all), grouped by shape.
              A <b>*</b> stands for a name that changes from one sample or run to the next. The count says in
              how many runs the shape is found: fewer than {total} means the other runs do not have it.
            </Text>
            {overview.layout.map((item) => {
              const full = item.runs === total;
              return (
                <Group key={item.shape} gap="xs" wrap="nowrap">
                  <Icon
                    icon={full ? 'mdi:check-circle-outline' : 'mdi:alert-circle-outline'}
                    width={14}
                    color={full ? 'var(--mantine-color-green-6)' : 'var(--mantine-color-yellow-7)'}
                  />
                  <Text size="xs" ff="monospace" truncate style={{ minWidth: 0, flex: 1 }}>
                    {item.shape}
                  </Text>
                  <Text size="xs" c={full ? 'dimmed' : 'yellow.8'} style={{ flexShrink: 0 }}>
                    {full ? 'in every run' : `in ${item.runs} of ${total} runs (${total - item.runs} without)`}
                  </Text>
                </Group>
              );
            })}
          </Stack>
        )}

        {overview.deviating.length > 0 && (
          <>
            <Anchor
              size="xs"
              component="button"
              type="button"
              onClick={() => setShowDiffs((v) => !v)}
              style={{ alignSelf: 'flex-start' }}
              data-testid="builder-runs-diffs-toggle"
            >
              {showDiffs ? 'Hide' : 'Show'} the runs that differ
            </Anchor>
            <Collapse in={showDiffs}>
              <Stack gap={6} data-testid="builder-runs-diffs">
                {overview.deviating.map((d) => (
                  <div key={d.run}>
                    <Text size="xs" fw={600} ff="monospace">
                      {d.run}{' '}
                      <Text span size="xs" c="dimmed" ff="inherit">
                        ({d.files} file{d.files === 1 ? '' : 's'})
                      </Text>
                    </Text>
                    {d.missing.length > 0 && (
                      <Text size="xs" c="dimmed">
                        missing: {d.missing.join(', ')}
                      </Text>
                    )}
                    {d.extra.length > 0 && (
                      <Text size="xs" c="dimmed">
                        only here: {d.extra.join(', ')}
                      </Text>
                    )}
                  </div>
                ))}
                {overview.deviating_total > overview.deviating.length && (
                  <Text size="xs" c="dimmed">
                    and {overview.deviating_total - overview.deviating.length} more
                  </Text>
                )}
              </Stack>
            </Collapse>
          </>
        )}

        {overview.runs.length > 0 && (
          <>
            <Anchor
              size="xs"
              component="button"
              type="button"
              onClick={() => setShowRuns((v) => !v)}
              style={{ alignSelf: 'flex-start' }}
              data-testid="builder-runs-list-toggle"
            >
              {showRuns ? 'Hide' : 'Show'} the runs and the folders left out
            </Anchor>
            <Collapse in={showRuns}>
              <Stack gap={6} data-testid="builder-runs-list">
                <Chips names={overview.runs} total={overview.runs_total} />
                {overview.skipped.length > 0 && (
                  <>
                    <Text size="xs" c="dimmed">
                      Not runs:
                    </Text>
                    <Chips names={overview.skipped} total={overview.skipped.length} dimmed />
                  </>
                )}
              </Stack>
            </Collapse>
          </>
        )}

        {overview.truncated && (
          <Text size="xs" c="dimmed">
            Large data root: only part of it was read for this summary.
          </Text>
        )}
      </Stack>
    </Paper>
  );
};

export default RunsPanel;
