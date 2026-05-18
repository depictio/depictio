/**
 * Inline MultiQC plot preview for the Project Data Manager DC viewer.
 *
 * Independent of the Component Designer's builder store — owns its own
 * module/plot/dataset state so the DC viewer can render a quick glance
 * without touching the builder flow. Cascading Selects mirror MultiQCBuilder,
 * the figure body mirrors MultiQCPreview (Plotly + MultiQC logo overlay).
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Center,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchMultiQCBuilderOptions,
  previewMultiQC,
} from 'depictio-react-core';
import type { MultiQCBuilderOptions } from 'depictio-react-core';
import Plot from 'react-plotly.js';

interface FigureData {
  data: Plotly.Data[];
  layout: Partial<Plotly.Layout>;
}

const GENERAL_STATS = 'general_stats';

function toSelectData(items: string[]): Array<{ value: string; label: string }> {
  return items.map((v) => ({ value: v, label: v }));
}

const MultiQCViewerPreview: React.FC<{ dcId: string }> = ({ dcId }) => {
  const { colorScheme } = useMantineColorScheme();
  const [opts, setOpts] = useState<MultiQCBuilderOptions | null>(null);
  const [optsLoading, setOptsLoading] = useState(true);
  const [optsError, setOptsError] = useState<string | null>(null);

  const [selectedModule, setSelectedModule] = useState<string | null>(null);
  const [selectedPlot, setSelectedPlot] = useState<string | null>(null);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);

  const [fig, setFig] = useState<FigureData | null>(null);
  const [figLoading, setFigLoading] = useState(false);
  const [figError, setFigError] = useState<string | null>(null);

  const isGeneralStats = selectedModule === GENERAL_STATS;

  useEffect(() => {
    if (!dcId) return;
    let cancelled = false;
    setOptsLoading(true);
    setOptsError(null);
    fetchMultiQCBuilderOptions(dcId)
      .then((data) => {
        if (cancelled) return;
        setOpts(data);
        // Skip general_stats when picking a default so the user lands on a
        // "real" plot first, but fall back to it when it's the only option.
        const firstModule =
          data.modules?.find((m) => m !== GENERAL_STATS) ||
          data.modules?.[0] ||
          null;
        if (!firstModule) return;
        setSelectedModule(firstModule);
        const firstPlot = data.plots?.[firstModule]?.[0] ?? null;
        setSelectedPlot(firstPlot);
        setSelectedDataset(
          (firstPlot && data.datasets?.[firstPlot]?.[0]) || null,
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setOptsError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setOptsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  const moduleOptions = useMemo(() => {
    if (!opts) return [];
    // Synthesise the General Stats entry — same as MultiQCBuilder, since the
    // MultiQC report's `modules` array doesn't include it even when present.
    return [
      { value: GENERAL_STATS, label: '⊞ General Stats Table' },
      ...toSelectData(opts.modules.filter((m) => m !== GENERAL_STATS)),
    ];
  }, [opts]);

  const plotOptions = useMemo(() => {
    if (!opts || !selectedModule || isGeneralStats) return [];
    return toSelectData(opts.plots[selectedModule] ?? []);
  }, [opts, selectedModule, isGeneralStats]);

  const datasetOptions = useMemo(() => {
    if (!opts || !selectedPlot) return [];
    return toSelectData(opts.datasets[selectedPlot] ?? []);
  }, [opts, selectedPlot]);

  useEffect(() => {
    if (!dcId || !selectedModule) {
      setFig(null);
      return;
    }
    // General Stats is its own module + plot pair — no dataset drill-down.
    const effectivePlot = isGeneralStats ? GENERAL_STATS : selectedPlot;
    if (!effectivePlot) {
      setFig(null);
      return;
    }
    let cancelled = false;
    setFigLoading(true);
    setFigError(null);
    previewMultiQC({
      dc_id: dcId,
      module: selectedModule,
      plot: effectivePlot,
      dataset: selectedDataset,
      theme: colorScheme === 'dark' ? 'dark' : 'light',
    })
      .then((res) => {
        if (cancelled) return;
        setFig({
          data: (res.figure?.data || []) as Plotly.Data[],
          layout: (res.figure?.layout || {}) as Partial<Plotly.Layout>,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setFigError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setFigLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, selectedModule, selectedPlot, selectedDataset, colorScheme, isGeneralStats]);

  if (optsLoading) {
    return (
      <Center mih={200}>
        <Loader size="sm" />
      </Center>
    );
  }
  if (optsError) {
    return (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
      >
        Failed to load MultiQC options: {optsError}
      </Alert>
    );
  }
  if (!opts || !opts.modules?.length) {
    return (
      <Alert
        color="yellow"
        variant="light"
        icon={<Icon icon="mdi:information-outline" width={18} />}
      >
        No MultiQC plots are available for this data collection.
      </Alert>
    );
  }

  const logoSrc =
    colorScheme === 'dark'
      ? `${import.meta.env.BASE_URL}logos/multiqc_icon_white.svg`
      : `${import.meta.env.BASE_URL}logos/multiqc_icon_dark.svg`;

  return (
    <Stack gap="sm">
      <Group grow gap="sm" wrap="nowrap">
        <Select
          label="Module"
          placeholder="Pick a module"
          data={moduleOptions}
          value={selectedModule}
          onChange={(val) => {
            if (val === GENERAL_STATS) {
              setSelectedModule(GENERAL_STATS);
              setSelectedPlot(GENERAL_STATS);
              setSelectedDataset(null);
              return;
            }
            setSelectedModule(val);
            const firstPlot = (val && opts.plots[val]?.[0]) || null;
            setSelectedPlot(firstPlot);
            setSelectedDataset(
              (firstPlot && opts.datasets[firstPlot]?.[0]) || null,
            );
          }}
          searchable
        />
        {!isGeneralStats && (
          <Select
            label="Plot"
            placeholder={
              !selectedModule ? 'Pick a module first' : 'Pick a plot'
            }
            data={plotOptions}
            value={selectedPlot}
            onChange={(val) => {
              setSelectedPlot(val);
              setSelectedDataset(
                (val && opts.datasets[val]?.[0]) || null,
              );
            }}
            searchable
            disabled={!plotOptions.length}
          />
        )}
        {!isGeneralStats && datasetOptions.length > 0 && (
          <Select
            label="Dataset"
            placeholder="Pick a dataset"
            data={datasetOptions}
            value={selectedDataset}
            onChange={setSelectedDataset}
            searchable
          />
        )}
      </Group>

      {figLoading ? (
        <Center mih={300}>
          <Loader size="sm" />
        </Center>
      ) : figError ? (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
        >
          Failed to render plot: {figError}
        </Alert>
      ) : !fig ? (
        <Center mih={200}>
          <Text size="sm" c="dimmed">
            Pick a plot to preview.
          </Text>
        </Center>
      ) : (
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
          <img
            src={logoSrc}
            title="Generated with MultiQC"
            alt=""
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              width: 40,
              height: 40,
              opacity: 0.6,
              pointerEvents: 'none',
              zIndex: 1,
            }}
          />
        </div>
      )}
    </Stack>
  );
};

export default MultiQCViewerPreview;
