/**
 * spatial_cells: what the role mapping cannot say.
 *
 * The cell table's columns go through the usual role mapping (and the marker
 * list through the Marker columns picker beside it). What is left is the frame
 * (image y-down or plot y-up), how several images are shown, the optional
 * image underlay (an Image DC of previews, one per sample, or a URL template)
 * and whether a lasso selects cells. All plain config, written as viz
 * overrides like the protein kinds' settings.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Group, NumberInput, Paper, SegmentedControl, Stack, Switch, Text } from '@mantine/core';
import { fetchProjectFromDashboard } from 'depictio-react-core';
import type { WorkflowEntry } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { companionOptions } from './proteinBindings';
import { ColumnPicker, CompanionPicker, str, useDcColumns } from './protein/common';

export interface SpatialCellsSettingsProps {
  /** What Save will write: the role bindings, the saved blob and the overrides. */
  config: Record<string, unknown> | null;
  /** Writes config fields; `undefined` drops a key the saved config never had. */
  onChange: (patch: Record<string, unknown>) => void;
}

const SpatialCellsSettings: React.FC<SpatialCellsSettingsProps> = ({ config, onChange }) => {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const boundDcId = useBuilderStore((s) => s.dcId);
  const [workflows, setWorkflows] = useState<WorkflowEntry[] | null>(null);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchProjectFromDashboard(dashboardId)
      .then(({ project }) => {
        if (!cancelled) setWorkflows(project.workflows ?? []);
      })
      .catch(() => {
        if (!cancelled) setWorkflows([]);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const imageOptions = useMemo(
    () => companionOptions(workflows ?? [], 'background', boundDcId),
    [workflows, boundDcId],
  );
  const imageColumns = useDcColumns(str(config?.background_dc_id));
  const yAxis = str(config?.y_axis) ?? 'image';
  const sampleDisplay = str(config?.sample_display) ?? 'select';
  const scale = typeof config?.background_image_scale === 'number' ? config.background_image_scale : 1;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Text fw={600} size="sm">
          Spatial frame
        </Text>
        <Group grow gap="xs" align="flex-end">
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Y axis
            </Text>
            <SegmentedControl
              size="xs"
              value={yAxis}
              onChange={(v) => onChange({ y_axis: v })}
              data={[
                { value: 'image', label: 'Image (y down)' },
                { value: 'cartesian', label: 'Plot (y up)' },
              ]}
            />
          </Stack>
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Samples
            </Text>
            <SegmentedControl
              size="xs"
              value={sampleDisplay}
              onChange={(v) => onChange({ sample_display: v })}
              data={[
                { value: 'select', label: 'One at a time' },
                { value: 'facet', label: 'Side by side' },
              ]}
            />
          </Stack>
        </Group>

        <CompanionPicker
          label="Image underlay"
          description="Optional Image collection with one preview per sample, drawn under the cells"
          base="background"
          options={imageOptions}
          config={config}
          onChange={onChange}
          loading={workflows === null}
          emptyMessage="No image collection in this project"
        />
        {config?.background_dc_id ? (
          <>
            <Group grow gap="xs">
              <ColumnPicker
                label="Sample"
                field="background_sample_col"
                fallback="sample"
                columns={imageColumns}
                config={config}
                onChange={onChange}
              />
              <ColumnPicker
                label="Width (px)"
                field="background_width_col"
                fallback="width"
                columns={imageColumns}
                config={config}
                onChange={onChange}
              />
              <ColumnPicker
                label="Height (px)"
                field="background_height_col"
                fallback="height"
                columns={imageColumns}
                config={config}
                onChange={onChange}
              />
            </Group>
            <NumberInput
              size="xs"
              label="Coordinate units per image pixel"
              description="1 when the centroids are in pixels of this image; the downscale factor of a preview"
              value={scale}
              min={0.0001}
              decimalScale={4}
              // Emptied, the field falls back to its default: a null is refused.
              onChange={(v) => onChange({ background_image_scale: Number(v) > 0 ? Number(v) : 1 })}
            />
          </>
        ) : null}

        <Switch
          size="xs"
          label="Lasso selects cells (emits their ids as a dashboard filter)"
          checked={config?.selection_enabled === true}
          onChange={(e) => onChange({ selection_enabled: e.currentTarget.checked })}
        />
      </Stack>
    </Paper>
  );
};

export default SpatialCellsSettings;
