/**
 * Inline scatter-map preview for coordinate-table DCs in the Project Data
 * Manager. Reads the first 100 preview rows via fetchDataCollectionPreview
 * and renders a Plotly scattermapbox where hovering a marker shows the row's
 * non-coord columns — same hover UX as the dashboard's Map component.
 */
import React, { useEffect, useMemo, useState } from 'react';
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
import { fetchDataCollectionPreview } from 'depictio-react-core';
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

  // Auto-center on the mean lat/lon so the map opens roughly framed.
  const center = useMemo(() => {
    if (!lats.length) return { lat: 0, lon: 0 };
    const sumLat = lats.reduce((a, b) => a + b, 0);
    const sumLon = lons.reduce((a, b) => a + b, 0);
    return { lat: sumLat / lats.length, lon: sumLon / lons.length };
  }, [lats, lons]);

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
      <div style={{ width: '100%', height: 360 }}>
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
              zoom: 1,
            },
            showlegend: false,
          }}
          config={{ displaylogo: false, responsive: true }}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
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
