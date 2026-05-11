/**
 * MultiQC builder. Cascading module → plot → dataset picker driven by
 * /api/v1/multiqc/builder_options. Persists `selected_module`,
 * `selected_plot`, `selected_dataset`, `s3_locations` and `is_general_stats`
 * matching the canonical shape that
 * depictio.api.v1.endpoints.dashboards_endpoints.routes.render_multiqc_endpoint
 * reads (and that depictio.dash.modules.multiqc_component.models.MultiQCState
 * stores).
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
import {
  fetchMultiQCBuilderOptions,
  readMultiqcSelection,
} from 'depictio-react-core';
import type { MultiQCBuilderOptions } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import DesignShell from '../shared/DesignShell';
import MultiQCPreview from './MultiQCPreview';

const MultiQCBuilder: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const rawConfig = useBuilderStore((s) => s.config) as {
    s3_locations?: string[];
    is_general_stats?: boolean;
  };
  // Read with legacy `multiqc_*` fallback so existing components pre-fill
  // the cascade. Persist always writes `selected_*` (buildMetadata.ts).
  const sel = readMultiqcSelection(rawConfig as Record<string, unknown>);
  const config = {
    ...rawConfig,
    selected_module: sel.module,
    selected_plot: sel.plot,
    selected_dataset: sel.dataset,
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [opts, setOpts] = useState<MultiQCBuilderOptions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId) return;
    setLoading(true);
    setError(null);
    fetchMultiQCBuilderOptions(dcId)
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
  const plotOptions = opts?.plots[config.selected_module || ''] ?? [];
  const datasetOptions =
    opts?.datasets[config.selected_plot || ''] ?? [];

  const isGeneralStats = Boolean(
    opts?.general_stats?.find(
      (gs) =>
        gs.module === config.selected_module && gs.plot === config.selected_plot,
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
        <Icon icon="mdi:chart-line" width={20} color="var(--mantine-color-orange-6)" />
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
        value={config.selected_module ?? null}
        onChange={(val) => {
          // "General Stats Table" is one click — module and plot are both
          // ``general_stats``, no further drill-down needed.
          if (val === 'general_stats') {
            patchConfig({
              selected_module: 'general_stats',
              selected_plot: 'general_stats',
              selected_dataset: undefined,
            });
            return;
          }
          patchConfig({
            selected_module: val,
            selected_plot: undefined,
            selected_dataset: undefined,
          });
        }}
        searchable
        disabled={!opts || !moduleOptions.length}
      />

      {config.selected_module !== 'general_stats' && (
        <Select
          label="Plot"
          placeholder={
            !config.selected_module ? 'Pick a module first' : 'Pick a plot'
          }
          data={plotOptions}
          value={config.selected_plot ?? null}
          onChange={(val) =>
            patchConfig({ selected_plot: val, selected_dataset: undefined })
          }
          searchable
          disabled={!plotOptions.length}
        />
      )}

      {datasetOptions.length > 0 && config.selected_module !== 'general_stats' && (
        <Select
          label="Dataset"
          placeholder="Pick a dataset"
          data={datasetOptions}
          value={config.selected_dataset ?? null}
          onChange={(val) => patchConfig({ selected_dataset: val })}
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
