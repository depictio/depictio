import React, { useEffect, useMemo, useState } from 'react';
import { Paper, Loader, Text, Stack, Modal } from '@mantine/core';

import { fetchImagePaths, StoredMetadata } from '../api';

interface ImageRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
}

/**
 * Renders a CSS-grid gallery of S3-hosted images (PNG/JPG/etc.) for the
 * `image` component_type. Mirrors `depictio/dash/modules/image_component`:
 *
 *   - Reads `image_column`, `s3_base_folder`, `thumbnail_size`, `columns`,
 *     `max_images` from `metadata`.
 *   - Resolves each row's image path -> full S3 path -> serve URL via the
 *     existing `/depictio/api/v1/files/serve/image?s3_path=…` endpoint, with
 *     URL-encoding identical to `build_image_url`.
 *   - Click a thumbnail -> Mantine `Modal` with the full-size image.
 *
 * Filter-aware iteration is intentionally deferred — the gallery is read-only
 * for the MVP. (Wire the parent `filters` array through if/when needed.)
 */
const ImageRenderer: React.FC<ImageRendererProps> = ({
  dashboardId,
  metadata,
}) => {
  const imageColumn = (metadata.image_column as string) || '';
  const s3BaseFolder = (metadata.s3_base_folder as string) || '';
  const thumbnailSize =
    typeof metadata.thumbnail_size === 'number'
      ? (metadata.thumbnail_size as number)
      : 150;
  const columns =
    typeof metadata.columns === 'number' ? (metadata.columns as number) : 4;
  const maxImages =
    typeof metadata.max_images === 'number'
      ? (metadata.max_images as number)
      : 50;

  const [paths, setPaths] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalSrc, setModalSrc] = useState<string | null>(null);
  const [modalAlt, setModalAlt] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    if (!metadata.dc_id || !imageColumn || !s3BaseFolder) {
      setError('Missing dc_id, image_column, or s3_base_folder.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchImagePaths(
      dashboardId,
      metadata.index,
      metadata.dc_id as string,
      imageColumn,
      s3BaseFolder,
      maxImages,
    )
      .then((res: string[]) => {
        if (cancelled) return;
        setPaths(res);
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
  }, [dashboardId, metadata.index, metadata.dc_id, imageColumn, s3BaseFolder, maxImages]);

  // Mirror `build_image_url`: combine s3_base_folder + relative path then
  // URL-encode the entire `s3_path` query parameter.
  const buildImageUrl = (relativePath: string): string => {
    const base = s3BaseFolder.replace(/\/+$/, '');
    const fullS3Path = `${base}/${relativePath}`;
    return `/depictio/api/v1/files/serve/image?s3_path=${encodeURIComponent(fullS3Path)}`;
  };

  const items = useMemo(() => {
    if (!paths) return [];
    return paths.slice(0, maxImages).map((relPath) => ({
      relPath,
      url: buildImageUrl(relPath),
      filename: relPath.split('/').pop() || relPath,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paths, maxImages, s3BaseFolder]);

  return (
    <Paper p="sm" withBorder radius="md" style={{ height: '100%' }}>
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title as string}
          {paths && (
            <Text component="span" c="dimmed" size="xs" ml="xs">
              ({items.length}
              {paths.length > maxImages ? ` of ${paths.length}` : ''} images)
            </Text>
          )}
        </Text>
      )}

      {loading && (
        <Stack align="center" justify="center" gap="xs" mih={200}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">
            Loading images…
          </Text>
        </Stack>
      )}

      {error && !loading && (
        <Stack mih={200} justify="center" align="center">
          <Text size="sm" c="red">
            Image gallery failed: {error}
          </Text>
        </Stack>
      )}

      {!loading && !error && items.length === 0 && (
        <Stack mih={120} justify="center" align="center">
          <Text size="sm" c="dimmed">
            No images found.
          </Text>
        </Stack>
      )}

      {!loading && !error && items.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${columns}, 1fr)`,
            gap: '8px',
            maxHeight: 600,
            overflowY: 'auto',
            overflowX: 'hidden',
            padding: 4,
          }}
        >
          {items.map((it) => (
            <button
              key={it.relPath}
              type="button"
              onClick={() => {
                setModalSrc(it.url);
                setModalAlt(it.filename);
              }}
              style={{
                padding: 0,
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                display: 'block',
                width: '100%',
              }}
              title={it.filename}
            >
              <img
                src={it.url}
                alt={it.filename}
                loading="lazy"
                style={{
                  width: '100%',
                  height: thumbnailSize,
                  objectFit: 'cover',
                  borderRadius: 4,
                  display: 'block',
                }}
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.opacity = '0.3';
                }}
              />
            </button>
          ))}
        </div>
      )}

      <Modal
        opened={modalSrc !== null}
        onClose={() => setModalSrc(null)}
        size="xl"
        centered
        withCloseButton
        title={modalAlt}
      >
        {modalSrc && (
          <img
            src={modalSrc}
            alt={modalAlt}
            style={{
              maxWidth: '100%',
              maxHeight: '80vh',
              objectFit: 'contain',
              display: 'block',
              margin: '0 auto',
            }}
          />
        )}
      </Modal>
    </Paper>
  );
};

export default ImageRenderer;
