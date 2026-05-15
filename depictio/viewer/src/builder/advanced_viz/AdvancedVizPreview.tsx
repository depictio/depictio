/**
 * Live preview pane for the advanced_viz builder.
 *
 * Builds a synthetic StoredMetadata from the current viz_kind + column mapping
 * and dispatches it through ComponentRenderer (same path the dashboard viewer
 * uses at runtime), with no interactive filters. Debounces config edits so
 * each keystroke in the Select dropdowns doesn't fire a fetch.
 *
 * `onReady` fires (true) once the bindings are valid AND the debounce has
 * fired — i.e. the synthetic config is structurally complete and the renderer
 * has been handed it. We don't get a "render succeeded" signal back from
 * ComponentRenderer, so this gate is "bindings ok to attempt" rather than
 * "plot actually drew". Wired to useBuilderStore.setPreviewReady → gates the
 * Save button in StepDesign.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Paper, Stack, Text } from '@mantine/core';
import { ComponentRenderer } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

import { buildAdvancedVizConfigBlob } from './configBlob';

interface Props {
  vizKind: string;
  columnMapping: Record<string, string | string[]>;
  wfId: string;
  dcId: string;
  bindingsValid: boolean;
  onReady?: (ready: boolean) => void;
}

const DEBOUNCE_MS = 300;

const AdvancedVizPreview: React.FC<Props> = ({
  vizKind,
  columnMapping,
  wfId,
  dcId,
  bindingsValid,
  onReady,
}) => {
  const cmKey = JSON.stringify(columnMapping);
  const [debouncedConfig, setDebouncedConfig] = useState<Record<string, unknown> | null>(
    null,
  );

  useEffect(() => {
    if (!bindingsValid) {
      setDebouncedConfig(null);
      onReady?.(false);
      return;
    }
    const t = window.setTimeout(() => {
      setDebouncedConfig(buildAdvancedVizConfigBlob(vizKind, columnMapping));
      onReady?.(true);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(t);
    // cmKey collapses columnMapping identity into a stable string so we don't
    // re-debounce on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vizKind, cmKey, wfId, dcId, bindingsValid]);

  const metadata: StoredMetadata | null = useMemo(() => {
    if (!debouncedConfig) return null;
    return {
      index: '__preview__',
      component_type: 'advanced_viz',
      title: 'Preview',
      wf_id: wfId,
      dc_id: dcId,
      viz_kind: vizKind,
      config: debouncedConfig,
    } as unknown as StoredMetadata;
  }, [debouncedConfig, vizKind, wfId, dcId]);

  // minHeight 520 fits Manhattan / heatmap / phylogenetic which need real
  // vertical room — 320 cropped them. `overflow: hidden` keeps any renderer
  // that misbehaves from leaking into the surrounding form rows.
  return (
    <Paper
      withBorder
      p="sm"
      radius="md"
      style={{ minHeight: 520, overflow: 'hidden' }}
    >
      <Stack gap={6} style={{ height: '100%' }}>
        <Text size="xs" fw={600} c="dimmed">
          Live preview
        </Text>
        {metadata ? (
          <div style={{ flex: 1, minHeight: 480, position: 'relative' }}>
            <ComponentRenderer
              dashboardId="__preview__"
              metadata={metadata}
              filters={[]}
              showDragHandle={false}
            />
          </div>
        ) : (
          <Text size="xs" c="dimmed" ta="center" mt="lg">
            Pick a viz kind and bind required columns to see a live preview.
          </Text>
        )}
      </Stack>
    </Paper>
  );
};

export default AdvancedVizPreview;
