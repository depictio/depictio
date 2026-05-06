/**
 * MultiQC builder. Cascading module → plot → dataset picker driven by
 * /api/v1/multiqc/builder_options. Persists `multiqc_module`,
 * `multiqc_plot`, `multiqc_dataset`, `s3_locations` and `is_general_stats`
 * matching the canonical multiqc metadata shape (see
 * depictio/dash/modules/multiqc_component/utils.py:214).
 *
 * Mirrors depictio/dash/modules/multiqc_component/frontend.py:design_multiqc
 * (lines 126-327) — module/plot/dataset cascade with a side-by-side preview.
 */
import React, { useEffect, useState } from 'react';
import {
  Alert,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from '../store/useBuilderStore';
import DesignShell from '../shared/DesignShell';
import MultiQCPreview from './MultiQCPreview';

interface BuilderOptions {
  modules: string[];
  plots: Record<string, string[]>; // module → plots
  datasets: Record<string, string[]>; // plot → datasets
  s3_locations: string[];
  /** Module + plot pairs that map to general_stats (rendered as table). */
  general_stats?: Array<{ module: string; plot: string }>;
}

async function fetchBuilderOptions(dcId: string): Promise<BuilderOptions> {
  const res = await fetch(
    `/depictio/api/v1/multiqc/builder_options?data_collection_id=${dcId}`,
    {
      headers: (() => {
        const headers: Record<string, string> = {};
        try {
          const stored = localStorage.getItem('local-store');
          if (stored) {
            const parsed = JSON.parse(stored);
            if (parsed?.access_token) {
              headers.Authorization = `Bearer ${parsed.access_token}`;
            }
          }
        } catch {
          // ignore
        }
        return headers;
      })(),
    },
  );
  if (!res.ok) throw new Error(`Failed to fetch MultiQC options: ${res.status}`);
  return res.json();
}

const MultiQCBuilder: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    multiqc_module?: string;
    multiqc_plot?: string;
    multiqc_dataset?: string;
    s3_locations?: string[];
    is_general_stats?: boolean;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [opts, setOpts] = useState<BuilderOptions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId) return;
    setLoading(true);
    setError(null);
    fetchBuilderOptions(dcId)
      .then((data) => {
        setOpts(data);
        if (!config.s3_locations) {
          patchConfig({ s3_locations: data.s3_locations });
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [dcId, config.s3_locations, patchConfig]);

  // Always offer "General Stats Table" at the top of the module list — this
  // mirrors the Dash design callback (depictio/dash/modules/multiqc_component/
  // callbacks/design.py:124) which prepends it unconditionally. The MultiQC
  // report's ``modules`` array doesn't include ``general_stats`` even when the
  // table is available, so we synthesise the entry client-side.
  const moduleOptions = [
    { value: 'general_stats', label: '⊞ General Stats Table' },
    ...(opts?.modules ?? [])
      .filter((m) => m !== 'general_stats')
      .map((m) => ({ value: m, label: m })),
  ];
  const plotOptions = opts?.plots[config.multiqc_module || ''] ?? [];
  const datasetOptions =
    opts?.datasets[config.multiqc_plot || ''] ?? [];

  const isGeneralStats = Boolean(
    opts?.general_stats?.find(
      (gs) =>
        gs.module === config.multiqc_module && gs.plot === config.multiqc_plot,
    ),
  );

  // Auto-flag general stats so the renderer dispatches correctly at view time.
  useEffect(() => {
    if (isGeneralStats !== Boolean(config.is_general_stats)) {
      patchConfig({ is_general_stats: isGeneralStats });
    }
  }, [isGeneralStats, config.is_general_stats, patchConfig]);

  const form = (
    <Stack gap="md">
      <Group gap="xs" align="center">
        <Icon icon="mdi:chart-line" width={20} color="orange" />
        <Title order={6}>MultiQC Report</Title>
      </Group>

      {error && (
        <Alert color="red" title="Failed to load MultiQC options">
          <Text size="xs">{error}</Text>
        </Alert>
      )}
      {loading && (
        <Group>
          <Loader size="xs" />
          <Text size="sm">Loading modules…</Text>
        </Group>
      )}

      <Select
        label="Module"
        placeholder="Pick a MultiQC module"
        data={moduleOptions}
        value={config.multiqc_module ?? null}
        onChange={(val) => {
          // "General Stats Table" is one click — module and plot are both
          // ``general_stats``, no further drill-down needed.
          if (val === 'general_stats') {
            patchConfig({
              multiqc_module: 'general_stats',
              multiqc_plot: 'general_stats',
              multiqc_dataset: undefined,
            });
            return;
          }
          patchConfig({
            multiqc_module: val,
            multiqc_plot: undefined,
            multiqc_dataset: undefined,
          });
        }}
        searchable
        disabled={!opts || !moduleOptions.length}
      />

      {config.multiqc_module !== 'general_stats' && (
        <Select
          label="Plot"
          placeholder={
            !config.multiqc_module ? 'Pick a module first' : 'Pick a plot'
          }
          data={plotOptions}
          value={config.multiqc_plot ?? null}
          onChange={(val) =>
            patchConfig({ multiqc_plot: val, multiqc_dataset: undefined })
          }
          searchable
          disabled={!plotOptions.length}
        />
      )}

      {datasetOptions.length > 0 && config.multiqc_module !== 'general_stats' && (
        <Select
          label="Dataset"
          placeholder="Pick a dataset"
          data={datasetOptions}
          value={config.multiqc_dataset ?? null}
          onChange={(val) => patchConfig({ multiqc_dataset: val })}
          searchable
        />
      )}
    </Stack>
  );

  return (
    <DesignShell
      formSlot={form}
      previewSlot={<MultiQCPreview />}
      hideColumns
    />
  );
};

export default MultiQCBuilder;
