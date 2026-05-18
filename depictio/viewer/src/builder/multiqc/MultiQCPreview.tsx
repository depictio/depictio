/**
 * Live preview for the MultiQC builder. Calls the new
 * `POST /api/v1/multiqc/preview` endpoint (no saved component required) and
 * renders the returned Plotly figure inline, matching what the dashboard
 * grid will render after save.
 *
 * Debounced 400ms so rapid cascade picks don't thrash the backend.
 */
import React, { useEffect, useState } from 'react';
import { useMantineColorScheme } from '@mantine/core';
import { previewMultiQC, readMultiqcSelection } from 'depictio-react-core';
import Plot from 'react-plotly.js';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';

interface FigureData {
  data: Plotly.Data[];
  layout: Partial<Plotly.Layout>;
}

const MultiQCPreview: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as Record<string, unknown>;
  const { colorScheme } = useMantineColorScheme();
  const [fig, setFig] = useState<FigureData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read with legacy `multiqc_*` fallback for in-flight builder state.
  const sel = readMultiqcSelection(config);
  const moduleName = sel.module;
  const plotName = sel.plot;
  const datasetName = sel.dataset;

  useEffect(() => {
    if (!dcId || !moduleName || !plotName) {
      setFig(null);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      previewMultiQC({
        dc_id: dcId,
        module: moduleName,
        plot: plotName,
        dataset: datasetName ?? null,
      })
        .then((res) => {
          if (cancelled) return;
          setFig({
            data: (res.figure?.data || []) as Plotly.Data[],
            layout: (res.figure?.layout || {}) as Partial<Plotly.Layout>,
          });
        })
        .catch((e) => {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [dcId, moduleName, plotName, datasetName]);

  if (!moduleName || !plotName) {
    return (
      <PreviewPanel
        minHeight={360}
        empty
        emptyMessage={
          !moduleName
            ? 'Pick a MultiQC module to preview the plot.'
            : 'Pick a plot…'
        }
      />
    );
  }

  return (
    <PreviewPanel minHeight={360} loading={loading} error={error}>
      {fig && (
        <div style={{ position: 'relative', width: '100%', height: 360 }}>
          <Plot
            data={fig.data}
            layout={{
              ...fig.layout,
              autosize: true,
              margin: { l: 40, r: 20, t: 30, b: 40 },
            }}
            config={{ displaylogo: false, responsive: true }}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
          />
          {/* MultiQC logo overlay — mirrors MultiQCFigure.tsx so the builder
            preview reads visually the same as the dashboard runtime. */}
          <img
            src={
              colorScheme === 'dark'
                ? '/dashboard-beta/logos/multiqc_icon_white.svg'
                : '/dashboard-beta/logos/multiqc_icon_dark.svg'
            }
            title="Generated with MultiQC"
            alt="MultiQC"
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              width: 40,
              height: 40,
              opacity: 0.6,
              pointerEvents: 'none',
              zIndex: 1000,
            }}
          />
        </div>
      )}
    </PreviewPanel>
  );
};

export default MultiQCPreview;
