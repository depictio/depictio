import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Card,
  Group,
  HoverCard,
  Image,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  fetchImagePaths,
  ImageGridResponse,
  InteractiveFilter,
  StoredMetadata,
} from '../api';
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

  const [response, setResponse] = useState<ImageGridResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalSrc, setModalSrc] = useState<string | null>(null);
  const [modalAlt, setModalAlt] = useState<string>('');
  // User-driven sort. ``null`` means "use server default" (the server picks
  // any acquisition* column it finds, otherwise no sort).
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  // Selection state — set of row IDs the user has clicked. (Falls back to
  // image filename when no row-id column resolves; see ``rowIdColumn``
  // below.) Cleared when ``onFilterChange`` zeroes our entry (e.g. via the
  // chrome reset icon).
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(
    () => new Set(),
  );
  // Last thumbnail the user clicked — used as the anchor for shift+click
  // range selection. Reset to null when the selection is externally cleared.
  const lastClickedRowIdRef = useRef<string | null>(null);

  // When the parent clears the filter (reset icon, "reset all filters"), we
  // need to drop the local selection so the cards reflect it. We detect
  // clearing by looking up our own filter entry in ``filters`` — when it's
  // gone, our local set should be empty too.
  useEffect(() => {
    const ours = filters.find(
      (f) => f.index === metadata.index && f.source === 'image_selection',
    );
    const valArr = Array.isArray(ours?.value) ? (ours!.value as unknown[]) : [];
    if (valArr.length === 0 && selectedRowIds.size > 0) {
      setSelectedRowIds(new Set());
      lastClickedRowIdRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  // The image grid must NOT filter itself by its own selection — otherwise
  // clicking one thumbnail shrinks the grid to that one row, leaving the
  // user with nothing else to click. Strip our own ``image_selection`` entry
  // before sending filters to the fetch. (Other renderers — figures,
  // tables, etc. — still see the selection in the filters array they
  // receive and narrow their data accordingly.)
  const filtersForFetch = useMemo(
    () =>
      filters.filter(
        (f) => !(f.index === metadata.index && f.source === 'image_selection'),
      ),
    [filters, metadata.index],
  );

  useEffect(() => {
    let cancelled = false;
    if (!metadata.dc_id || !imageColumn || !s3BaseFolder) {
      setError('Missing dc_id, image_column, or s3_base_folder.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchImagePaths(dashboardId, metadata.index, maxImages, filtersForFetch, sortBy, sortDir)
      .then((res) => {
        if (cancelled) return;
        setResponse(res);
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
    JSON.stringify(filtersForFetch),
    refreshTick,
    sortBy,
    sortDir,
  ]);

  const paths = response ? response.paths : null;
  const rows = response ? response.rows : null;
  const sortableColumns = response?.sortable_columns ?? [];
  const effectiveSortBy = response?.sort_by ?? null;

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

  // Pick a row-id column the backend can filter on. Prefer an explicit
  // `selection_column` from the YAML metadata (matches the FigureRenderer /
  // TableRenderer convention); otherwise auto-detect from row keys, looking
  // for `index_index`, `_id`, `id`, or any column ending in `_id`. Falls
  // back to the image_column itself (the old behaviour — selection acts on
  // image filename, so duplicate-image rows toggle together).
  const rowIdColumn = useMemo<string | null>(() => {
    const explicit = metadata.selection_column as string | undefined;
    if (typeof explicit === 'string' && explicit) return explicit;
    if (!rows || rows.length === 0) return null;
    const keys = Object.keys(rows[0] as Record<string, unknown>);
    const candidates = ['index_index', '_id', 'id'];
    for (const k of candidates) if (keys.includes(k)) return k;
    const idLike = keys.find((k) => k.toLowerCase().endsWith('_id'));
    return idLike ?? null;
  }, [metadata.selection_column, rows]);

  // One thumbnail PER ROW. The same image_column value can appear in many
  // rows (e.g. the same cell measured at different acquisition timestamps),
  // and each row carries distinct metadata the user wants to inspect /
  // select independently. Selection is keyed by row-id so clicking one
  // thumbnail visually toggles only that one — even when its image filename
  // duplicates elsewhere in the grid.
  const items = useMemo(() => {
    if (!rows) return [];
    return rows.slice(0, maxImages).map((row, idx) => {
      const r = row as Record<string, unknown>;
      const relPath = String(r[imageColumn] ?? '');
      const rowId =
        rowIdColumn != null && r[rowIdColumn] != null
          ? String(r[rowIdColumn])
          : `__row_${idx}__`; // fallback when no id column resolves
      return {
        relPath,
        row: r,
        rowId,
        // React key — guaranteed unique across duplicate filenames.
        key: `${relPath}__${rowId}`,
        url: buildImageUrl(relPath),
        filename: relPath.split('/').pop() || relPath,
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, maxImages, s3BaseFolder, imageColumn, rowIdColumn]);

  const totalRowsCount = rows ? rows.length : 0;

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

  // Build the filter payload from a set of row IDs. When a real row-id
  // column is available we pass row IDs straight through so the backend
  // filters per row (each thumbnail = one row, click = exact selection).
  // Falls back to dispatching the unique image filenames when no row-id
  // column resolves — the legacy behaviour where selection acts on filename.
  const dispatchFilter = (nextSet: Set<string>) => {
    if (!onFilterChange) return;
    let column: string;
    let value: string[];
    if (rowIdColumn) {
      column = rowIdColumn;
      value = Array.from(nextSet);
    } else {
      column = imageColumn;
      const filenames = new Set<string>();
      for (const it of items) {
        if (nextSet.has(it.rowId)) filenames.add(it.relPath);
      }
      value = Array.from(filenames);
    }
    onFilterChange({
      index: metadata.index,
      value,
      source: 'image_selection',
      column_name: column,
      interactive_component_type: 'MultiSelect',
      metadata: {
        dc_id: metadata.dc_id,
        column_name: column,
        interactive_component_type: 'MultiSelect',
      },
    });
  };

  // Click handler — three modes:
  //   plain click     → toggle this thumbnail in/out of the selection
  //   shift+click     → range select from the last-clicked thumbnail to here
  //   cmd/ctrl+click  → same as plain (kept distinct so we don't fight the
  //                     OS conventions on each platform — both feel "additive")
  // The dispatch happens inside the setState updater so two rapid clicks
  // (before React flushes either render) both see the freshest prev-set.
  const handleThumbnailClick = (rowId: string, event: React.MouseEvent) => {
    if (!selectionEnabled || !onFilterChange) return;
    const isShift = event.shiftKey;
    setSelectedRowIds((prev) => {
      const next = new Set(prev);
      if (isShift && lastClickedRowIdRef.current) {
        const last = lastClickedRowIdRef.current;
        const lastIdx = items.findIndex((it) => it.rowId === last);
        const currIdx = items.findIndex((it) => it.rowId === rowId);
        if (lastIdx >= 0 && currIdx >= 0) {
          const [a, b] = lastIdx <= currIdx ? [lastIdx, currIdx] : [currIdx, lastIdx];
          for (let i = a; i <= b; i++) next.add(items[i].rowId);
        } else {
          // Anchor not in the current page — fall through to plain toggle.
          if (next.has(rowId)) next.delete(rowId);
          else next.add(rowId);
        }
      } else {
        if (next.has(rowId)) next.delete(rowId);
        else next.add(rowId);
      }
      lastClickedRowIdRef.current = rowId;
      dispatchFilter(next);
      return next;
    });
  };

  // Sort dropdown options. ``sortable_columns`` from the server lists every
  // column on the underlying DC; we add an "auto" placeholder so the user can
  // hand sorting back to the server's acquisition-timestamp default.
  const sortOptions = useMemo(() => {
    const opts = [{ value: '__auto__', label: 'Default (newest first)' }];
    for (const col of sortableColumns) opts.push({ value: col, label: col });
    return opts;
  }, [sortableColumns]);

  const clearSelection = () => {
    if (!onFilterChange) return;
    setSelectedRowIds(new Set());
    lastClickedRowIdRef.current = null;
    onFilterChange({
      index: metadata.index,
      value: [],
      source: 'image_selection',
      column_name: rowIdColumn ?? imageColumn,
      interactive_component_type: 'MultiSelect',
      metadata: {
        dc_id: metadata.dc_id,
        column_name: rowIdColumn ?? imageColumn,
        interactive_component_type: 'MultiSelect',
      },
    });
  };

  return (
    <Paper p="sm" withBorder radius="md" style={{ height: '100%' }}>
      {/* Header is left-aligned (justify="flex-start"): title, then sort
       * controls, then any selection badge. The chrome toolbar
       * (`MetadataPopover` / `ResetButton` / etc.) floats at the top-right
       * via absolute positioning — keeping our local controls on the left
       * avoids overlap without restructuring the chrome itself. */}
      <Group gap="xs" align="center" mb="xs" wrap="nowrap">
        {metadata.title && (
          <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>
            {metadata.title as string}
            {response && (
              <Text component="span" c="dimmed" size="xs" ml="xs">
                ({items.length}
                {totalRowsCount > items.length ? ` of ${totalRowsCount}` : ''} rows
                {effectiveSortBy ? ` · sorted by ${effectiveSortBy} ${sortDir}` : ''}
                {selectionEnabled ? ' · click to select, shift+click for range' : ''})
              </Text>
            )}
          </Text>
        )}
        {sortableColumns.length > 0 && (
          <>
            <Select
              size="xs"
              data={sortOptions}
              value={sortBy ?? '__auto__'}
              onChange={(v) => setSortBy(v === '__auto__' ? null : v)}
              allowDeselect={false}
              w={170}
              aria-label="Sort image grid by column"
            />
            <ActionIcon
              size="sm"
              variant="default"
              onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
              title={`Toggle sort direction (currently ${sortDir})`}
            >
              <Icon
                icon={sortDir === 'asc' ? 'mdi:sort-ascending' : 'mdi:sort-descending'}
                width={14}
              />
            </ActionIcon>
          </>
        )}
        {selectionEnabled && selectedRowIds.size > 0 && (
          <Badge
            size="sm"
            variant="filled"
            color="blue"
            rightSection={
              <ActionIcon
                size="xs"
                variant="transparent"
                c="white"
                onClick={clearSelection}
                title="Clear image selection"
              >
                <Icon icon="mdi:close" width={12} />
              </ActionIcon>
            }
          >
            {selectedRowIds.size} selected
          </Badge>
        )}
      </Group>

      {/* Initial fetch (no response yet): show the big loader. Subsequent
          fetches keep the existing grid mounted with a small overlay. */}
      {response === null && loading && (
        <Stack align="center" justify="center" gap="xs" mih={200}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">
            Loading images…
          </Text>
        </Stack>
      )}

      {error && response === null && (
        <Stack mih={200} justify="center" align="center">
          <Text size="sm" c="red">
            Image gallery failed: {error}
          </Text>
        </Stack>
      )}

      {response !== null && !error && items.length === 0 && (
        <Stack mih={120} justify="center" align="center" style={{ position: 'relative' }}>
          <Text size="sm" c="dimmed">
            No images found.
          </Text>
          <RefetchOverlay visible={loading} />
        </Stack>
      )}

      {response !== null && !error && items.length > 0 && (
        <Box pos="relative">
          <ScrollArea.Autosize mah={600} type="auto" offsetScrollbars>
            <SimpleGrid cols={columns} spacing="xs" verticalSpacing="xs" p={4}>
              {items.map((it) => {
                const selected = selectedRowIds.has(it.rowId);
                const isNew = highlightActive && newPaths.has(it.relPath);
                const cardClasses = [
                  isNew ? 'depictio-card-new' : null,
                  selected ? 'depictio-card-selected' : null,
                ]
                  .filter(Boolean)
                  .join(' ') || undefined;
                return (
                  <Box key={it.key} pos="relative">
                    <HoverCard
                      width={320}
                      shadow="md"
                      openDelay={350}
                      closeDelay={80}
                      position="top"
                      withinPortal
                    >
                      <HoverCard.Target>
                        <UnstyledButton
                          onClick={(e) => {
                            if (selectionEnabled) handleThumbnailClick(it.rowId, e);
                            else {
                              setModalSrc(it.url);
                              setModalAlt(it.filename);
                            }
                          }}
                          title={
                            selectionEnabled
                              ? `${it.filename} — click to ${selected ? 'deselect' : 'select'} (shift+click for range)`
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
                      </HoverCard.Target>
                      <HoverCard.Dropdown>
                        <Stack gap={4}>
                          <Text fw={600} size="sm" truncate>
                            {it.filename}
                          </Text>
                          {Object.entries(it.row as Record<string, unknown>).map(
                            ([k, v]) => (
                              <Group key={k} gap="xs" wrap="nowrap" justify="space-between">
                                <Text size="xs" c="dimmed" truncate>
                                  {k}
                                </Text>
                                <Text size="xs" ff="monospace" truncate maw={180} ta="right">
                                  {v == null ? '—' : String(v)}
                                </Text>
                              </Group>
                            ),
                          )}
                        </Stack>
                      </HoverCard.Dropdown>
                    </HoverCard>
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
