/**
 * Live preview for the MultiQC builder. Calls the new
 * `POST /api/v1/multiqc/preview` endpoint (no saved component required) and
 * renders the returned Plotly figure inline, matching what the dashboard
 * grid will render after save.
 *
 * Debounced 400ms so rapid cascade picks don't thrash the backend.
 */
import React, { useEffect, useState } from 'react';
import { previewMultiQC } from 'depictio-react-core';
import Plot from 'react-plotly.js';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';

interface FigureData {
  data: Plotly.Data[];
  layout: Partial<Plotly.Layout>;
}

const MultiQCPreview: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    multiqc_module?: string;
    multiqc_plot?: string;
    multiqc_dataset?: string;
  };
  const [fig, setFig] = useState<FigureData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const moduleName = config.multiqc_module;
  const plotName = config.multiqc_plot;
  const datasetName = config.multiqc_dataset;

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
        <Plot
          data={fig.data}
          layout={{
            ...fig.layout,
            autosize: true,
            margin: { l: 40, r: 20, t: 30, b: 40 },
          }}
          config={{ displaylogo: false, responsive: true }}
          useResizeHandler
          style={{ width: '100%', height: 360 }}
        />
      )}
    </PreviewPanel>
  );
};

export default MultiQCPreview;
