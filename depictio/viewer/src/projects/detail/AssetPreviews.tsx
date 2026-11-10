/**
 * Previews of the collections that are not tables: a grid of the images, the
 * tree as dashboards draw it, the map a GeoJSON file holds.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Center,
  Group,
  Image,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { useElementSize } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import {
  collapseMapAttribution,
  fetchDataCollectionPreview,
  fetchGeojson,
  fetchTracksPreview,
  imageServeUrl,
  JBrowseRenderer,
  PhylogeneticRenderer,
} from 'depictio-react-core';
import type { GeoJsonCollection, GeoJsonFeature, PreviewResult } from 'depictio-react-core';
import Plot from 'react-plotly.js';

import { GEO_COLOR, GEO_ICON } from '../dcTypeIcon';
import { escapeHtml, fitMapView, MAP_HEIGHT } from './CoordinatesMapPreview';

interface DcLike {
  _id?: string;
  id?: string;
  config?: { dc_specific_properties?: Record<string, unknown> };
}

const MAX_IMAGES = 24;
const TREE_HEIGHT = 520;
const TRACKS_MIN_HEIGHT = 420;
/** Past this a file costs the browser more than a preview is worth. */
const MAX_GEOJSON_BYTES = 20 * 1024 * 1024;
/** Hover markers past this add cost, not information. */
const MAX_HOVER_FEATURES = 2000;
const MAX_HOVER_PROPERTIES = 5;

const dcIdOf = (dc: DcLike) => dc._id ?? dc.id ?? null;

/** What `load` returns for `key`; a null key loads nothing. */
function useLoaded<T>(key: string | null, load: (k: string) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(key !== null);
  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    load(key)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // `load` is a module-level function at every call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { data, error, loading };
}

const Notice: React.FC<{ color: string; children: React.ReactNode }> = ({ color, children }) => (
  <Alert color={color} variant="light" icon={<Icon icon="mdi:information-outline" width={18} />}>
    {children}
  </Alert>
);

const Loading: React.FC = () => (
  <Center mih={200}>
    <Loader size="sm" />
  </Center>
);

const ImageThumb: React.FC<{ url: string; name: string }> = ({ url, name }) => {
  // TIFF and the like: stored and served, but no browser draws them.
  const [failed, setFailed] = useState(false);
  return (
    <Stack gap={4} data-testid="asset-preview-image">
      <Anchor href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${name}`}>
        {failed ? (
          <Center h={120} bg="var(--mantine-color-default-hover)" style={{ borderRadius: 8 }}>
            <Icon icon="mdi:image-off-outline" width={28} />
          </Center>
        ) : (
          <Image
            src={url}
            alt={name}
            h={120}
            fit="contain"
            radius="sm"
            loading="lazy"
            onError={() => setFailed(true)}
          />
        )}
      </Anchor>
      <Text size="xs" c="dimmed" truncate="end" title={name}>
        {name}
      </Text>
    </Stack>
  );
};

const loadImages = (dcId: string): Promise<PreviewResult> =>
  fetchDataCollectionPreview(dcId, MAX_IMAGES);

export const ImagesPreview: React.FC<{ dc: DcLike }> = ({ dc }) => {
  const props = dc.config?.dc_specific_properties;
  const imageColumn = props?.image_column as string | undefined;
  const baseFolder = (props?.s3_base_folder as string | undefined) ?? '';
  const { data, error, loading } = useLoaded(dcIdOf(dc), loadImages);

  if (loading) return <Loading />;
  if (error) return <Notice color="red">Failed to load preview: {error}</Notice>;
  const paths = (data?.rows ?? [])
    .map((row) => String(row[imageColumn ?? ''] ?? ''))
    .filter(Boolean);
  if (paths.length === 0) return <Notice color="yellow">No image to show.</Notice>;

  return (
    <Stack gap="xs" data-testid="asset-preview-images">
      {(data?.total_rows ?? 0) > paths.length && (
        <Text size="sm" c="dimmed">
          First {paths.length} of {data?.total_rows} images
        </Text>
      )}
      <SimpleGrid cols={{ base: 2, sm: 4, md: 6 }} spacing="sm">
        {paths.map((path) => (
          <ImageThumb
            key={path}
            url={imageServeUrl(baseFolder, path)}
            name={path.split('/').pop() || path}
          />
        ))}
      </SimpleGrid>
    </Stack>
  );
};

export const TreePreview: React.FC<{ dcId: string }> = ({ dcId }) => {
  const metadata = useMemo(
    () => ({
      index: `dc-preview-${dcId}`,
      component_type: 'advanced_viz',
      viz_kind: 'phylogenetic',
      config: { tree_wf_id: '', tree_dc_id: dcId },
    }),
    [dcId],
  );
  return (
    <Box h={TREE_HEIGHT} data-testid="asset-preview-tree">
      <PhylogeneticRenderer metadata={metadata} filters={[]} />
    </Box>
  );
};

export const TracksPreview: React.FC<{ dcId: string }> = ({ dcId }) => {
  const metadata = useMemo(
    () => ({ index: `dc-preview-${dcId}`, component_type: 'jbrowse', dc_id: dcId }),
    [dcId],
  );
  const loadSession = useCallback(() => fetchTracksPreview(dcId), [dcId]);
  return (
    <Box mih={TRACKS_MIN_HEIGHT} data-testid="asset-preview-tracks">
      <JBrowseRenderer
        dashboardId={`dc-preview-${dcId}`}
        metadata={metadata}
        filters={[]}
        loadSession={loadSession}
      />
    </Box>
  );
};

/** A legacy collection is read from its own JBrowse session: no manifest here. */
export const LegacyTracksNotice: React.FC = () => (
  <Notice color="gray">
    This legacy JBrowse2 collection has no track list to preview. Add a genome browser to a
    dashboard to see it.
  </Notice>
);

/** Every [lon, lat] pair under a geometry's `coordinates`. */
function collectPairs(value: unknown, pairs: Array<[number, number]>): void {
  if (!Array.isArray(value)) return;
  if (typeof value[0] === 'number' && typeof value[1] === 'number') {
    pairs.push([value[0], value[1]]);
    return;
  }
  for (const item of value) collectPairs(item, pairs);
}

function hoverText(feature: GeoJsonFeature): string {
  return Object.entries(feature.properties ?? {})
    .slice(0, MAX_HOVER_PROPERTIES)
    .map(([key, value]) => `<b>${escapeHtml(key)}</b>: ${escapeHtml(String(value ?? '—'))}`)
    .join('<br>');
}

/** The extent of a file, and one hover marker at the middle of each feature. */
function summarize(geojson: GeoJsonCollection) {
  const lats: number[] = [];
  const lons: number[] = [];
  const markers = { lat: [] as number[], lon: [] as number[], text: [] as string[] };
  (geojson.features ?? []).forEach((feature, index) => {
    const pairs: Array<[number, number]> = [];
    collectPairs(feature.geometry?.coordinates, pairs);
    if (pairs.length === 0) return;
    let lonSum = 0;
    let latSum = 0;
    for (const [lon, lat] of pairs) {
      lons.push(lon);
      lats.push(lat);
      lonSum += lon;
      latSum += lat;
    }
    if (index < MAX_HOVER_FEATURES) {
      markers.lon.push(lonSum / pairs.length);
      markers.lat.push(latSum / pairs.length);
      markers.text.push(hoverText(feature) || `Feature ${index + 1}`);
    }
  });
  return { lats, lons, markers };
}

export const GeoJsonPreview: React.FC<{ dc: DcLike }> = ({ dc }) => {
  const { colorScheme } = useMantineColorScheme();
  // Plotly parses colours itself, so a CSS variable never resolves.
  const color = useMantineTheme().colors[GEO_COLOR][6];
  const { ref, width } = useElementSize();
  const size = dc.config?.dc_specific_properties?.file_size_bytes as number | undefined;
  const tooLarge = (size ?? 0) > MAX_GEOJSON_BYTES;
  const { data, error, loading } = useLoaded(tooLarge ? null : dcIdOf(dc), fetchGeojson);
  const summary = useMemo(() => (data ? summarize(data) : null), [data]);

  // The wrapper stays mounted, or its size would never be measured.
  let notice: React.ReactNode = null;
  if (tooLarge) notice = <Notice color="gray">This file is too large to preview here.</Notice>;
  else if (loading) notice = <Loading />;
  else if (error) notice = <Notice color="red">Failed to load preview: {error}</Notice>;
  else if (!summary || summary.lats.length === 0) {
    notice = <Notice color="yellow">No coordinates to show in this file.</Notice>;
  }

  const count = data?.features?.length ?? 0;
  const { center, zoom } = summary
    ? fitMapView(summary.lats, summary.lons, width)
    : { center: { lat: 0, lon: 0 }, zoom: 1 };
  const layer = { sourcetype: 'geojson', source: data, color };

  return (
    <Stack gap="xs" ref={ref} data-testid="asset-preview-geojson">
      {notice ?? (
        <>
          <Group gap={6} wrap="nowrap">
            <Icon icon={GEO_ICON} width={16} color={`var(--mantine-color-${GEO_COLOR}-6)`} />
            <Badge color={GEO_COLOR} variant="light" size="sm">
              {count} feature{count === 1 ? '' : 's'}
            </Badge>
          </Group>
          <div style={{ width: '100%', height: MAP_HEIGHT }}>
            <Plot
              data={[
                {
                  type: 'scattermap',
                  mode: 'markers',
                  lat: summary?.markers.lat,
                  lon: summary?.markers.lon,
                  text: summary?.markers.text,
                  hovertemplate: '%{text}<extra></extra>',
                  marker: { size: 8, color, opacity: 0.5 },
                  name: '',
                } as Plotly.Data,
              ]}
              layout={
                {
                  autosize: true,
                  margin: { l: 0, r: 0, t: 0, b: 0 },
                  showlegend: false,
                  map: {
                    style: colorScheme === 'dark' ? 'carto-darkmatter' : 'carto-positron',
                    center,
                    zoom,
                    // A circle layer would also dot every polygon vertex, so
                    // points come from the hover markers alone.
                    layers: [
                      { ...layer, type: 'fill', opacity: 0.3 },
                      { ...layer, type: 'line', line: { width: 1.5 } },
                    ],
                  },
                } as Partial<Plotly.Layout>
              }
              config={{ displaylogo: false, responsive: true }}
              useResizeHandler
              style={{ width: '100%', height: '100%' }}
              onInitialized={(_f, gd) => collapseMapAttribution(gd)}
              onUpdate={(_f, gd) => collapseMapAttribution(gd)}
            />
          </div>
        </>
      )}
    </Stack>
  );
};
