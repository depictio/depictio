/**
 * Live preview of one (file, viz spec) pair, rendered through the viewer's REAL
 * `ComponentRenderer`.
 *
 * Mechanism: POST /studio/render returns build_payload's blob ({renders, data}).
 * We write it onto `window.__CATALOG_PREVIEW__` so the api shim (mockApi.ts) can
 * read the render payloads, then render `renders[0]` — exactly how
 * catalog-preview's OutputView renders a fixture. Card values come from
 * `bulkComputeCards`, which the shim answers from the same blob.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Box, Center, Loader, Text } from '@mantine/core';
import { ComponentRenderer, bulkComputeCards } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import { renderSpec, type RenderPayload } from './backend';
import { toRenderSpec, type VizSpec } from './spec';

const DASHBOARD_ID = 'studio';

class CellBoundary extends React.Component<
  { children: React.ReactNode },
  { error?: string }
> {
  state: { error?: string } = {};
  static getDerivedStateFromError(err: unknown) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
  render() {
    if (this.state.error) {
      return (
        <Alert color="red" variant="light" title="Render failed">
          {this.state.error}
        </Alert>
      );
    }
    return this.props.children;
  }
}

interface Props {
  file: string | null;
  spec: VizSpec | null;
  theme: 'light' | 'dark';
}

const LivePreview: React.FC<Props> = ({ file, spec, theme }) => {
  const [meta, setMeta] = useState<StoredMetadata | null>(null);
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardSecondary, setCardSecondary] = useState<Record<string, Record<string, unknown>>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!file || !spec) {
      setMeta(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderSpec(file, toRenderSpec(spec), theme)
      .then(async (blob: RenderPayload) => {
        if (cancelled) return;
        // Feed the api shim (mockApi.ts reads this global).
        window.__CATALOG_PREVIEW__ = {
          theme: blob.theme,
          initialOutputId: null,
          tools: [],
          data: blob.data,
        } as unknown as typeof window.__CATALOG_PREVIEW__;
        const cards = await bulkComputeCards(DASHBOARD_ID, []);
        if (cancelled) return;
        setCardValues(cards.values as Record<string, unknown>);
        setCardSecondary((cards.secondary_values || {}) as Record<string, Record<string, unknown>>);
        setMeta((blob.renders[0] as unknown as StoredMetadata) ?? null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [file, spec, theme]);

  if (!file) return <Placeholder text="Pick a file to preview data." />;
  if (!spec) return <Placeholder text="Design or pick a visualization to preview it." />;
  if (loading && !meta)
    return (
      <Center h={240}>
        <Loader size="sm" />
      </Center>
    );
  if (error)
    return (
      <Alert color="red" variant="light" title="Preview error">
        {error}
      </Alert>
    );
  if (!meta) return <Placeholder text="Nothing to preview yet." />;

  const rec = meta as Record<string, unknown>;
  const note = (rec._unsupported || rec._error) as string | undefined;
  if (note)
    return (
      <Alert color="gray" variant="light" title={String(meta.component_type)}>
        {note}
      </Alert>
    );

  const height = (rec._preview_height as number) || 420;
  return (
    <Box style={{ height, minHeight: 120 }}>
      <CellBoundary>
        <ComponentRenderer
          metadata={meta}
          filters={[]}
          dashboardId={DASHBOARD_ID}
          cardValue={cardValues[meta.index]}
          cardSecondaryValues={cardSecondary[meta.index]}
          cardLoading={false}
        />
      </CellBoundary>
    </Box>
  );
};

const Placeholder: React.FC<{ text: string }> = ({ text }) => (
  <Center h={200}>
    <Text size="sm" c="dimmed">
      {text}
    </Text>
  </Center>
);

export default LivePreview;
