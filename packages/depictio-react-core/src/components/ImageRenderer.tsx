import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Card,
  Image,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  SimpleGrid,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchImagePaths, InteractiveFilter, StoredMetadata } from '../api';
import { useNewItemIds } from '../hooks/useNewItemIds';
import { useTransientFlag } from '../hooks/useTransientFlag';
import RefetchOverlay from './RefetchOverlay';

interface ImageRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters?: InteractiveFilter[];
  /** Receives a filter entry with ``source="image_selection"`` whenever a
   *  thumbnail is selected / deselected. Pass ``value: []`` to clear. When
   *  omitted, the component falls back to its preview-only behaviour. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
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
 * Filters narrow the grid the same way they narrow figures/tables — including
 * selection-source filters (``scatter_selection`` / ``table_selection``) and
 * cross-DC link filters resolved server-side via ``extend_filters_via_links``.
 * Mirrors Dash ``_extract_filters_for_image``.
 */
const ImageRenderer: React.FC<ImageRendererProps> = ({
  dashboardId,
  metadata,
  filters = [],
  onFilterChange,
  refreshTick,
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
  // Selection state — set of relPaths the user has clicked. Cleared when
  // ``onFilterChange`` zeroes our entry (e.g. via the chrome reset icon).
  const [selectedRelPaths, setSelectedRelPaths] = useState<Set<string>>(
    () => new Set(),
  );

  // When the parent clears the filter (reset icon, "reset all filters"), we
  // need to drop the local selection so the cards reflect it. We detect
  // clearing by looking up our own filter entry in ``filters`` — when it's
  // gone, our local set should be empty too.
  useEffect(() => {
    const ours = filters.find(
      (f) => f.index === metadata.index && f.source === 'image_selection',
    );
    const valArr = Array.isArray(ours?.value) ? (ours!.value as unknown[]) : [];
    if (valArr.length === 0 && selectedRelPaths.size > 0) {
      setSelectedRelPaths(new Set());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

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
      filters,
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    dashboardId,
    metadata.index,
    metadata.dc_id,
    imageColumn,
    s3BaseFolder,
    maxImages,
    JSON.stringify(filters),
    refreshTick,
  ]);

  // Mirror `build_image_url`: combine s3_base_folder + relative path then
  // URL-encode the entire `s3_path` query parameter. Strip a leading copy of
  // the s3_base_folder's last segment from the relative path — some pipelines
  // record paths like `phenobase/cell_001.png` even when s3_base_folder
  // already ends with `/phenobase/`, which would otherwise produce
  // `…/phenobase/phenobase/cell_001.png` and 404.
  const buildImageUrl = (relativePath: string): string => {
    const base = s3BaseFolder.replace(/\/+$/, '');
    const lastSegment = base.split('/').pop() || '';
    let rel = relativePath.replace(/^\/+/, '');
    if (lastSegment && rel.startsWith(`${lastSegment}/`)) {
      rel = rel.slice(lastSegment.length + 1);
    }
    const fullS3Path = `${base}/${rel}`;
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

  // ── New-item highlight pipeline ───────────────────────────────────────────
  // ``useNewItemIds`` is the WHAT (which paths just arrived);
  // ``useTransientFlag`` is the WHEN (only ~3 s after a refreshTick
  // increment). Filter edits don't change refreshTick → no glow.
  const highlightDurationMs =
    typeof metadata.highlight_duration_ms === 'number'
      ? (metadata.highlight_duration_ms as number)
      : 3000;
  const newPaths = useNewItemIds(paths || [], refreshTick);
  const highlightActive = useTransientFlag(refreshTick, highlightDurationMs);

  const selectionEnabled = !!onFilterChange && !!imageColumn;

  // Toggle selection for a thumbnail and dispatch the updated selection set
  // upstream as an ``image_selection`` filter. ``interactive_component_type``
  // is set to ``MultiSelect`` so the backend's ``add_filter`` runs the same
  // ``is_in()`` path used by scatter / table selections.
  //
  // Uses the function form of ``setState`` so two rapid clicks (before React
  // flushes either render) both see the fresh prev-set instead of stale
  // closure state. The dispatch happens inside the updater so ``onFilterChange``
  // also gets the merged result.
  const toggleSelection = (relPath: string) => {
    if (!selectionEnabled || !onFilterChange) return;
    setSelectedRelPaths((prev) => {
      const next = new Set(prev);
      if (next.has(relPath)) next.delete(relPath);
      else next.add(relPath);
      onFilterChange({
        index: metadata.index,
        value: Array.from(next),
        source: 'image_selection',
        column_name: imageColumn,
        interactive_component_type: 'MultiSelect',
        metadata: {
          dc_id: metadata.dc_id,
          column_name: imageColumn,
          interactive_component_type: 'MultiSelect',
        },
      });
      return next;
    });
  };

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

      {/* Initial fetch (no paths yet): show the big loader. Subsequent
          fetches keep the existing grid mounted with a small overlay. */}
      {paths === null && loading && (
        <Stack align="center" justify="center" gap="xs" mih={200}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">
            Loading images…
          </Text>
        </Stack>
      )}

      {error && paths === null && (
        <Stack mih={200} justify="center" align="center">
          <Text size="sm" c="red">
            Image gallery failed: {error}
          </Text>
        </Stack>
      )}

      {paths !== null && !error && items.length === 0 && (
        <Stack mih={120} justify="center" align="center" style={{ position: 'relative' }}>
          <Text size="sm" c="dimmed">
            No images found.
          </Text>
          <RefetchOverlay visible={loading} />
        </Stack>
      )}

      {paths !== null && !error && items.length > 0 && (
        <Box pos="relative">
          <ScrollArea.Autosize mah={600} type="auto" offsetScrollbars>
            <SimpleGrid cols={columns} spacing="xs" verticalSpacing="xs" p={4}>
              {items.map((it) => {
                const selected = selectedRelPaths.has(it.relPath);
                const isNew = highlightActive && newPaths.has(it.relPath);
                const cardClasses = [
                  isNew ? 'depictio-card-new' : null,
                  selected ? 'depictio-card-selected' : null,
                ]
                  .filter(Boolean)
                  .join(' ') || undefined;
                return (
                  <Box key={it.relPath} pos="relative">
                    <UnstyledButton
                      onClick={() => {
                        if (selectionEnabled) toggleSelection(it.relPath);
                        else {
                          setModalSrc(it.url);
                          setModalAlt(it.filename);
                        }
                      }}
                      title={
                        selectionEnabled
                          ? `${it.filename} — click to ${selected ? 'deselect' : 'select'}`
                          : it.filename
                      }
                      display="block"
                      style={{ width: '100%' }}
                    >
                      <Card
                        padding={0}
                        radius="sm"
                        withBorder
                        className={cardClasses}
                        style={
                          selected
                            ? {
                                outline: '3px solid var(--mantine-color-blue-6)',
                                outlineOffset: -3,
                              }
                            : undefined
                        }
                      >
                        <Image
                          src={it.url}
                          alt={it.filename}
                          h={thumbnailSize}
                          w="100%"
                          fit="cover"
                          loading="lazy"
                          fallbackSrc="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='1.5'><path d='M3 5h18v14H3z'/><circle cx='9' cy='10' r='2'/><path d='M21 17l-6-6-9 9'/></svg>"
                        />
                      </Card>
                    </UnstyledButton>
                    {selectionEnabled && (
                      <ActionIcon
                        size="sm"
                        variant="filled"
                        color="gray"
                        radius="sm"
                        pos="absolute"
                        top={4}
                        right={4}
                        onClick={(e) => {
                          e.stopPropagation();
                          setModalSrc(it.url);
                          setModalAlt(it.filename);
                        }}
                        title="Preview"
                        style={{ opacity: 0.85 }}
                      >
                        <Icon icon="mdi:magnify" width={14} />
                      </ActionIcon>
                    )}
                  </Box>
                );
              })}
            </SimpleGrid>
          </ScrollArea.Autosize>
          <RefetchOverlay visible={loading} />
        </Box>
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
          <Image
            src={modalSrc}
            alt={modalAlt}
            fit="contain"
            mah="80vh"
            mx="auto"
          />
        )}
      </Modal>
    </Paper>
  );
};

export default ImageRenderer;
