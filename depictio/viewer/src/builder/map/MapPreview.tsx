/**
 * Live preview for the Map builder. Pulls rows directly from
 * /deltatables/preview/{dc_id} and renders a Plotly scatter_map (or
 * density_map) inline, so the user sees an actual DC-specific map without
 * a save round-trip.
 *
 * Choropleth needs a geojson DC + feature ID lookup, which isn't doable
 * client-side from preview rows alone — that case falls back to a summary.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Stack, Text } from '@mantine/core';
import Plot from 'react-plotly.js';
import { fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';

interface MapConfig {
  map_type?: string;
  lat_column?: string;
  lon_column?: string;
  color_column?: string;
  size_column?: string;
  hover_columns?: string[];
  map_style?: string;
  opacity?: number;
}

const MapPreview: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as MapConfig;

  const [data, setData] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId || !config.lat_column || !config.lon_column) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId, 200)
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
  }, [dcId, config.lat_column, config.lon_column]);

  const fig = useMemo(() => {
    if (!data?.rows?.length || !config.lat_column || !config.lon_column) return null;
    const lats: number[] = [];
    const lons: number[] = [];
    const colors: (number | string)[] = [];
    const sizes: number[] = [];
    const texts: string[] = [];
    for (const row of data.rows) {
      const la = Number(row?.[config.lat_column]);
      const lo = Number(row?.[config.lon_column]);
      if (!Number.isFinite(la) || !Number.isFinite(lo)) continue;
      lats.push(la);
      lons.push(lo);
      if (config.color_column) colors.push(row?.[config.color_column] as number | string);
      if (config.size_column) {
        const s = Number(row?.[config.size_column]);
        sizes.push(Number.isFinite(s) ? s : 8);
      }
      if (config.hover_columns?.length) {
        texts.push(
          config.hover_columns
            .map((c) => `${c}: ${row?.[c] ?? '—'}`)
            .join('<br>'),
        );
      }
    }
    if (!lats.length) return null;

    const isDensity = config.map_type === 'density_map';
    const opacity =
      typeof config.opacity === 'number' ? config.opacity : 0.8;
    const mapStyle = config.map_style || 'carto-positron';

    const trace: Plotly.Data = isDensity
      ? ({
          type: 'densitymapbox',
          lat: lats,
          lon: lons,
          z: colors.length ? colors : lats.map(() => 1),
          opacity,
          radius: 20,
        } as unknown as Plotly.Data)
      : ({
          type: 'scattermapbox',
          mode: 'markers',
          lat: lats,
          lon: lons,
          marker: {
            size: sizes.length ? sizes : 8,
            color: colors.length ? colors : undefined,
            colorscale: colors.length ? 'Viridis' : undefined,
            opacity,
          },
          text: texts.length ? texts : undefined,
          hoverinfo: texts.length ? 'text' : 'lat+lon',
        } as unknown as Plotly.Data);

    const meanLat = lats.reduce((a, b) => a + b, 0) / lats.length;
    const meanLon = lons.reduce((a, b) => a + b, 0) / lons.length;

    return {
      data: [trace],
      layout: {
        autosize: true,
        margin: { l: 0, r: 0, t: 0, b: 0 },
        mapbox: {
          style: mapStyle,
          center: { lat: meanLat, lon: meanLon },
          zoom: 2,
        },
      } as Partial<Plotly.Layout>,
    };
  }, [data, config.lat_column, config.lon_column, config.color_column, config.size_column, config.map_type, config.map_style, config.opacity, config.hover_columns]);

  if (!config.lat_column || !config.lon_column) {
    return (
      <PreviewPanel
        minHeight={320}
        empty
        emptyMessage="Pick latitude and longitude columns to preview the map."
      />
    );
  }

  if (config.map_type === 'choropleth_map') {
    return (
      <PreviewPanel minHeight={320}>
        <Stack gap="xs">
          <Text size="sm">
            Choropleth maps need a GeoJSON data collection — preview will render
            after save.
          </Text>
          <Text size="xs" c="dimmed">
            Configured: <code>{config.lat_column}</code> / <code>{config.lon_column}</code>,
            color by <code>{config.color_column || 'none'}</code>
          </Text>
        </Stack>
      </PreviewPanel>
    );
  }

  return (
    <PreviewPanel minHeight={320} loading={loading} error={error}>
      {fig && (
        <Plot
          data={fig.data}
          layout={fig.layout}
          config={{ displaylogo: false, responsive: true }}
          useResizeHandler
          style={{ width: '100%', height: 320 }}
        />
      )}
    </PreviewPanel>
  );
};

export default MapPreview;
