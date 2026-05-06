/**
 * Live preview for the Image builder. Pulls real values from the chosen
 * `image_column` via /deltatables/preview/{dc_id}, then renders a small
 * gallery grid showing the actual filenames the dashboard component will
 * load after save.
 *
 * The actual S3-resolved image bytes can't be loaded without the saved
 * component (the renderer uses a dashboard/component-id round-trip), so
 * tiles show filenames + an icon. This still gives the user real DC-specific
 * feedback ("yes, that's the column I want") without backend coupling.
 */
import React, { useEffect, useState } from 'react';
import { Card, Center, SimpleGrid, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';

const ImagePreview: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    image_column?: string;
    s3_base_folder?: string;
  };

  const [data, setData] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId || !config.image_column) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId, 24)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, config.image_column]);

  if (!config.image_column) {
    return (
      <PreviewPanel
        minHeight={200}
        empty
        emptyMessage="Pick an image column to preview the gallery."
      />
    );
  }

  const filenames: string[] = (() => {
    if (!data?.rows || !config.image_column) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const row of data.rows) {
      const v = row?.[config.image_column];
      if (v == null) continue;
      const s = String(v);
      if (s && !seen.has(s)) {
        seen.add(s);
        out.push(s);
      }
      if (out.length >= 6) break;
    }
    return out;
  })();

  return (
    <PreviewPanel minHeight={200} loading={loading} error={error}>
      <Stack gap="sm">
        <Stack gap={2}>
          <Text fw={700}>{config.title || 'Untitled gallery'}</Text>
          <Text size="xs" c="dimmed">
            First {filenames.length} unique value{filenames.length === 1 ? '' : 's'} of{' '}
            <code>{config.image_column}</code>
            {config.s3_base_folder ? (
              <>
                {' '}— prefixed with <code>{config.s3_base_folder}</code> at runtime
              </>
            ) : null}
            .
          </Text>
        </Stack>
        <SimpleGrid cols={3} spacing="xs">
          {(filenames.length ? filenames : Array.from({ length: 6 }, () => '')).map(
            (name, idx) => (
              <Tooltip key={idx} label={name || 'No data yet'} disabled={!name}>
                <Card withBorder radius="md" p="xs">
                  <Center>
                    <Stack gap={4} align="center">
                      <Icon
                        icon="mdi:image-area"
                        width={32}
                        color="var(--mantine-color-dimmed)"
                      />
                      <Text size="xs" c="dimmed" lineClamp={1} maw={120}>
                        {name || 'Image'}
                      </Text>
                    </Stack>
                  </Center>
                </Card>
              </Tooltip>
            ),
          )}
        </SimpleGrid>
      </Stack>
    </PreviewPanel>
  );
};

export default ImagePreview;
