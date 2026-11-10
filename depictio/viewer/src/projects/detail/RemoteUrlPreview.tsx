/**
 * The "One file from its URL" source of Add data and New project, checked
 * before anything is made: `remoteUrlProblem` catches what the browser can tell alone (scheme,
 * host, a folder instead of a file), and `RemoteUrlPreview` asks the server
 * for the first rows (`previewRemoteUrl`), which also runs the server's own
 * policy: a refused host or bucket is refused here, not after Create.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Group, Loader, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { previewRemoteUrl } from 'depictio-react-core';
import type { RunFilePreview } from 'depictio-react-core';

import { PreviewBody } from '../fromRun/FilePreview';

const TABLE_SUFFIX = /\.(csv|tsv|tab|txt|parquet|feather|arrow|ipc)(\.gz)?$/i;
const PREVIEW_DELAY_MS = 600;

function parsed(url: string): URL | null {
  try {
    return new URL(url.trim());
  } catch {
    return null;
  }
}

/** Why `url` cannot be a table file's URL, or null when it may be. */
export function remoteUrlProblem(url: string): string | null {
  const trimmed = url.trim();
  if (!trimmed) return null;
  const u = parsed(trimmed);
  const scheme = u?.protocol.replace(':', '').toLowerCase();
  if (!u || !scheme || !['https', 'http', 's3'].includes(scheme)) {
    return 'Start the URL with https://, s3:// or http://.';
  }
  if (!u.hostname) {
    return scheme === 's3' ? 'Name the bucket: s3://bucket/path/file.csv.' : 'The URL has no host.';
  }
  if (!u.pathname || u.pathname === '/' || u.pathname.endsWith('/')) {
    return 'This is a folder, not a file. Give the URL of one table file.';
  }
  return null;
}

/** Things worth knowing that do not stop the URL from being used. */
function remoteUrlHints(url: string): string[] {
  const u = parsed(url);
  if (!u) return [];
  const hints: string[] = [];
  if (u.protocol === 'http:') {
    hints.push('Plain http:// is only accepted when the server allows it; prefer https://.');
  }
  const name = decodeURIComponent(u.pathname.split('/').pop() ?? '');
  if (name && !TABLE_SUFFIX.test(name)) {
    hints.push(
      `"${name}" has no table extension (.csv, .tsv, .parquet, .feather): pick the format below.`,
    );
  }
  return hints;
}

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; preview: RunFilePreview };

export const RemoteUrlPreview: React.FC<{ url: string }> = ({ url }) => {
  const trimmed = url.trim();
  const usable = trimmed.length > 0 && remoteUrlProblem(trimmed) === null;
  const [state, setState] = useState<State>({ status: 'idle' });

  useEffect(() => {
    if (!usable) {
      setState({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    // Wait for the typing to settle: every keystroke is a different URL.
    const timer = window.setTimeout(() => {
      previewRemoteUrl(trimmed, { signal: controller.signal })
        .then((preview) => {
          if (!controller.signal.aborted) setState({ status: 'ready', preview });
        })
        .catch((err: Error) => {
          if (!controller.signal.aborted) {
            setState({ status: 'error', error: err.message || 'The URL could not be read.' });
          }
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, usable]);

  if (!usable) return null;
  const hints = remoteUrlHints(trimmed);
  return (
    <Paper
      withBorder
      radius="sm"
      p="xs"
      style={{ contain: 'inline-size', minWidth: 0 }}
      data-testid="remote-url-preview"
      data-state={state.status}
      aria-live="polite"
    >
      <Stack gap={6}>
        {hints.map((hint) => (
          <Text key={hint} size="xs" c="dimmed">
            {hint}
          </Text>
        ))}
        {state.status === 'loading' && (
          <Group gap="xs" wrap="nowrap">
            <Loader size="xs" />
            <Text size="xs" c="dimmed">
              Reading the start of the file from the server...
            </Text>
          </Group>
        )}
        {state.status === 'error' && (
          <Alert
            color="red"
            variant="light"
            p="xs"
            icon={<Icon icon="mdi:link-off" width={14} />}
            data-testid="remote-url-preview-error"
          >
            <Text size="xs">{state.error}</Text>
          </Alert>
        )}
        {state.status === 'ready' && (
          <>
            <Group gap={6} wrap="nowrap">
              <Icon icon="mdi:check-circle-outline" width={14} color="var(--mantine-color-teal-6)" />
              <Text size="xs" fw={500}>
                The server can read {state.preview.name}
              </Text>
            </Group>
            <PreviewBody preview={state.preview} />
          </>
        )}
      </Stack>
    </Paper>
  );
};
