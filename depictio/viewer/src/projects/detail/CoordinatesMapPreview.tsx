/**
 * Inline scatter-map preview for coordinate-table DCs in the Project Data
 * Manager. Reads the first 100 preview rows via fetchDataCollectionPreview
 * and renders a Plotly scattermapbox where hovering a marker shows the row's
 * non-coord columns — same hover UX as the dashboard's Map component.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { collapseMapAttribution, fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import Plot from 'react-plotly.js';

interface DcLike {
  _id?: string;
  id?: string;
  config?: {
    dc_specific_properties?: Record<string, unknown>;
  };
}

/** Escape HTML so user-controlled column names can't break out of the static
 *  parts of a Plotly hovertemplate. Per-point values come in via customdata
 *  and are escaped by Plotly. */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const MAP_HEIGHT = 360;
// Leave a margin so edge points aren't flush against the frame.
const ZOOM_PADDING = 0.5;
// Keep a lone point (or tightly-clustered points) from zooming to street level.
const MAX_ZOOM = 12;
const SINGLE_POINT_ZOOM = 9;

/**
 * Web-Mercator "fit these bounds into a WxH viewport" zoom — Plotly's
 * scattermapbox has no fitBounds, so we derive the zoom that frames every
 * point. Mirrors the classic Google Maps getBoundsZoom, using mapbox-gl's
 * 512px world tile. Returns the tighter of the lat/lon fits so both axes stay
 * inside the viewport.
 */
function fitBoundsZoom(
  minLat: number,
  maxLat: number,
  minLon: number,
  maxLon: number,
  widthPx: number,
  heightPx: number,
): number {
  const WORLD = 512;
  const latRad = (lat: number) => {
    const sin = Math.sin((lat * Math.PI) / 180);
    const rad = Math.log((1 + sin) / (1 - sin)) / 2;
    return Math.max(Math.min(rad, Math.PI), -Math.PI) / 2;
  };
  const latFraction = (latRad(maxLat) - latRad(minLat)) / Math.PI;
  let lonDiff = maxLon - minLon;
  if (lonDiff < 0) lonDiff += 360;
  const lonFraction = lonDiff / 360;
  const latZoom = Math.log2(heightPx / WORLD / (latFraction || Number.EPSILON));
  const lonZoom = Math.log2(widthPx / WORLD / (lonFraction || Number.EPSILON));
  return Math.min(latZoom, lonZoom);
}

const CoordinatesMapPreview: React.FC<{ dc: DcLike }> = ({ dc }) => {
  const { colorScheme } = useMantineColorScheme();
  const dcId = dc._id ?? dc.id;
  const props = dc.config?.dc_specific_properties;
  const latCol = props?.lat_column as string | undefined;
  const lonCol = props?.lon_column as string | undefined;

  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId)
      .then((res) => {
        if (!cancelled) setPreview(res);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  // Keep only rows where lat/lon parse to numbers — sloppy data shouldn't
  // crash the preview.
  const { lats, lons, customdata, hovertemplate, otherCols, usableCount } =
    useMemo(() => {
      const empty = {
        lats: [] as number[],
        lons: [] as number[],
        customdata: [] as Array<Array<string>>,
        hovertemplate: '',
        otherCols: [] as string[],
        usableCount: 0,
      };
      if (!preview || !latCol || !lonCol) return empty;
      const cols = preview.columns.filter((c) => c !== latCol && c !== lonCol);
      const ls: number[] = [];
      const ns: number[] = [];
      const cd: Array<Array<string>> = [];
      for (const row of preview.rows) {
        const la = Number(row[latCol]);
        const lo = Number(row[lonCol]);
        if (!Number.isFinite(la) || !Number.isFinite(lo)) continue;
        ls.push(la);
        ns.push(lo);
        cd.push(cols.map((c) => String(row[c] ?? '—')));
      }
      const lines = cols
        .map((c, i) => `<b>${escapeHtml(c)}</b>: %{customdata[${i}]}`)
        .join('<br>');
      return {
        lats: ls,
        lons: ns,
        customdata: cd,
        hovertemplate: `${lines}<extra></extra>`,
        otherCols: cols,
        usableCount: ls.length,
      };
    }, [preview, latCol, lonCol]);

  // Measure the rendered map width so the fit-bounds zoom accounts for the
  // actual aspect ratio (height is fixed at MAP_HEIGHT). Starts at 0 → first
  // paint uses a sensible fallback, then the ResizeObserver refines it.
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const [mapWidth, setMapWidth] = useState(0);
  useEffect(() => {
    const el = mapContainerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w) setMapWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Frame the view to the points' bounding box: center on the bbox midpoint and
  // pick the zoom that fits every point (padded + clamped), instead of a fixed
  // world-scale zoom.
  const { center, zoom } = useMemo(() => {
    if (!lats.length) return { center: { lat: 0, lon: 0 }, zoom: 1 };
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const center = { lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2 };
    // All points coincident (or a single point): no span to fit.
    if (minLat === maxLat && minLon === maxLon) {
      return { center, zoom: SINGLE_POINT_ZOOM };
    }
    const width = mapWidth || 600;
    const raw = fitBoundsZoom(minLat, maxLat, minLon, maxLon, width, MAP_HEIGHT);
    let z = raw - ZOOM_PADDING;
    if (!Number.isFinite(z)) z = SINGLE_POINT_ZOOM;
    z = Math.max(0, Math.min(z, MAX_ZOOM));
    return { center, zoom: z };
  }, [lats, lons, mapWidth]);

  if (!latCol || !lonCol) {
    return (
      <Alert
        color="yellow"
        variant="light"
        icon={<Icon icon="mdi:information-outline" width={18} />}
      >
        This data collection doesn't have <code>lat_column</code> /{' '}
        <code>lon_column</code> set in its configuration.
      </Alert>
    );
  }
  if (loading) {
    return (
      <Center mih={200}>
        <Loader size="sm" />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
      >
        Failed to load preview: {error}
      </Alert>
    );
  }
  if (!preview || usableCount === 0) {
    return (
      <Alert
        color="yellow"
        variant="light"
        icon={<Icon icon="mdi:information-outline" width={18} />}
      >
        No usable lat/lon values in the first {preview?.rows.length ?? 0} rows.
      </Alert>
    );
  }

  const mapStyle =
    colorScheme === 'dark' ? 'carto-darkmatter' : 'carto-positron';
  const isTruncated = preview.total_rows > preview.rows.length;
  const skippedSomeRows = usableCount !== preview.rows.length;

  return (
    <Stack gap="xs">
      <Group justify="space-between" gap="xs">
        <Text size="sm" c="dimmed">
          {skippedSomeRows
            ? `Showing ${usableCount} of ${preview.rows.length} preview rows (others had non-numeric coords)`
            : `Showing ${usableCount} point${usableCount === 1 ? '' : 's'}`}
        </Text>
        {isTruncated && (
          <Badge color="grape" variant="light" size="sm" radius="sm">
            Preview of first {preview.rows.length} of {preview.total_rows} rows
          </Badge>
        )}
      </Group>
      <div ref={mapContainerRef} style={{ width: '100%', height: MAP_HEIGHT }}>
        <Plot
          data={[
            {
              type: 'scattermapbox',
              mode: 'markers',
              lat: lats,
              lon: lons,
              customdata,
              hovertemplate,
              marker: {
                size: 8,
                color: 'var(--mantine-color-grape-6)',
                opacity: 0.85,
              },
              name: '',
            } as Plotly.Data,
          ]}
          layout={{
            autosize: true,
            margin: { l: 0, r: 0, t: 0, b: 0 },
            mapbox: {
              style: mapStyle,
              center,
              zoom,
            },
            showlegend: false,
          }}
          config={{ displaylogo: false, responsive: true }}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          onInitialized={(_f, gd) => collapseMapAttribution(gd)}
          onUpdate={(_f, gd) => collapseMapAttribution(gd)}
        />
      </div>
      {otherCols.length > 0 && (
        <Text size="xs" c="dimmed">
          Hover over a marker to see its other columns ({otherCols.join(', ')}).
        </Text>
      )}
    </Stack>
  );
};

export default CoordinatesMapPreview;
