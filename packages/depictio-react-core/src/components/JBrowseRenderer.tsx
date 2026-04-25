import React, { useEffect, useState } from 'react';
import { Paper, Loader, Text, Stack } from '@mantine/core';

import { fetchJBrowseSession, InteractiveFilter, StoredMetadata } from '../api';

interface JBrowseRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
}

interface JBrowseSession {
  iframe_url: string;
  assembly: string;
  location: string;
  tracks?: string[];
  metadata?: { filter_applied?: boolean };
}

/**
 * Renders a JBrowse 2 genome browser by mounting an `<iframe>` whose `src` is
 * synthesised server-side. The Dash version (see
 * `depictio/dash/modules/jbrowse_component/utils.py:build_jbrowse`) does the
 * same — JBrowse 2 runs standalone at `localhost:3000` and pulls its session
 * config from `localhost:9010/sessions/...`. The React port keeps the
 * iframe-wrapper pattern; backend supplies the URL plus assembly/location/
 * tracks metadata so the chrome can stay in sync with filter state.
 */
const JBrowseRenderer: React.FC<JBrowseRendererProps> = ({
  dashboardId,
  metadata,
  filters,
}) => {
  const [session, setSession] = useState<JBrowseSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Backend honors `metadata.height`. Default matches the spec (600 px).
  const iframeHeight =
    typeof metadata.height === 'number' ? (metadata.height as number) : 600;

  // Optional CSS scale-down hack — only enable when the metadata explicitly
  // asks for it. Mirrors the Dash version's `transform: scale(0.8)` style.
  const scaleEnabled = metadata.iframe_scale === true;
  const scaleFactor =
    typeof metadata.iframe_scale_factor === 'number'
      ? (metadata.iframe_scale_factor as number)
      : 0.8;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchJBrowseSession(dashboardId, metadata.index, filters)
      .then((res: JBrowseSession) => {
        if (cancelled) return;
        setSession(res);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filters)]);

  const iframeStyle: React.CSSProperties = scaleEnabled
    ? {
        width: `${100 / scaleFactor}%`,
        height: '100%',
        border: 0,
        transform: `scale(${scaleFactor})`,
        transformOrigin: '0 0',
      }
    : { width: '100%', height: '100%', border: 0 };

  return (
    <Paper
      p="sm"
      withBorder
      radius="md"
      style={{ minHeight: iframeHeight + 40, display: 'flex', flexDirection: 'column' }}
    >
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title as string}
        </Text>
      )}

      {loading && (
        <Stack align="center" justify="center" gap="xs" mih={iframeHeight - 40}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">
            Loading JBrowse…
          </Text>
        </Stack>
      )}

      {error && !loading && (
        <div
          className="dashboard-error"
          style={{
            minHeight: iframeHeight - 40,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
            textAlign: 'center',
          }}
        >
          <Text size="sm" c="red">
            JBrowse failed: {error}
          </Text>
        </div>
      )}

      {session && !loading && !error && (
        <div
          style={{
            width: '100%',
            height: iframeHeight,
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <iframe
            title={`jbrowse-${metadata.index}`}
            src={session.iframe_url}
            style={iframeStyle}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          />
        </div>
      )}
    </Paper>
  );
};

export default JBrowseRenderer;
