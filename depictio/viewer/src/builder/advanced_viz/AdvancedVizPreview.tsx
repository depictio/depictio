/**
 * Live preview pane for the advanced_viz builder.
 *
 * Builds a synthetic StoredMetadata from the current viz_kind + column mapping
 * and dispatches it through ComponentRenderer (same path the dashboard viewer
 * uses at runtime), under the dashboard's active filters carried into the
 * builder (see useBuilderPreviewFilters). Debounces config edits so each
 * keystroke in the Select dropdowns doesn't fire a fetch.
 *
 * `onReady` fires (true) once the bindings are valid AND the debounce has
 * fired — i.e. the synthetic config is structurally complete and the renderer
 * has been handed it. We don't get a "render succeeded" signal back from
 * ComponentRenderer, so this gate is "bindings ok to attempt" rather than
 * "plot actually drew". Wired to useBuilderStore.setPreviewReady → gates the
 * Save button in StepDesign.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ComponentRenderer } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

import PreviewPanel from '../shared/PreviewPanel';
import { buildAdvancedVizConfigBlob } from './configBlob';
import { useBuilderPreviewFilters } from '../useBuilderPreviewFilters';

interface Props {
  vizKind: string;
  columnMapping: Record<string, string | string[]>;
  wfId: string;
  dcId: string;
  bindingsValid: boolean;
  onReady?: (ready: boolean) => void;
  /** Catalog/saved preset whose viz-control extras (threshold, top-N…) the
   *  preview should reflect, so Edit & Add matches the catalog preview. */
  presetConfig?: Record<string, unknown> | null;
}

const DEBOUNCE_MS = 300;

const AdvancedVizPreview: React.FC<Props> = ({
  vizKind,
  columnMapping,
  wfId,
  dcId,
  bindingsValid,
  onReady,
  presetConfig,
}) => {
  const previewFilters = useBuilderPreviewFilters();
  const cmKey = JSON.stringify(columnMapping);
  const presetKey = JSON.stringify(presetConfig ?? null);
  const [debouncedConfig, setDebouncedConfig] = useState<Record<string, unknown> | null>(
    null,
  );
  // The debounce window is the one stretch nothing else covers: the renderer
  // draws its own skeleton once it has the config, but until the timer fires
  // the pane still shows the previous plot (or the empty hint) with no sign
  // that an edit is on its way.
  const [debouncing, setDebouncing] = useState(false);

  useEffect(() => {
    if (!bindingsValid) {
      setDebouncedConfig(null);
      setDebouncing(false);
      onReady?.(false);
      return;
    }
    setDebouncing(true);
    const t = window.setTimeout(() => {
      setDebouncedConfig(buildAdvancedVizConfigBlob(vizKind, columnMapping, presetConfig));
      setDebouncing(false);
      onReady?.(true);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(t);
    // cmKey/presetKey collapse object identity into stable strings so we don't
    // re-debounce on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vizKind, cmKey, presetKey, wfId, dcId, bindingsValid]);

  // `debouncing` is raised from an effect, so it is still false on the first
  // render after arriving with bindings already valid — hitting "Edit" on a
  // catalog render, where everything is pre-bound. That frame would show the
  // "pick a viz kind" prompt, which is both a flash and untrue.
  const settling = bindingsValid && !debouncedConfig;

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

  // The same panel every other builder's preview uses, so this one gets the
  // shared loading / empty treatment instead of a second set of conventions.
  // minHeight 520 fits Manhattan / heatmap / phylogenetic which need real
  // vertical room — 320 cropped them.
  return (
    <PreviewPanel
      minHeight={520}
      loading={debouncing || settling}
      empty={!metadata && !debouncing && !settling}
      emptyMessage="Pick a viz kind and bind required columns to see a live preview."
    >
      {metadata && (
        <div style={{ height: '100%', minHeight: 480, position: 'relative' }}>
          <ComponentRenderer
            dashboardId="__preview__"
            metadata={metadata}
            filters={previewFilters}
            showDragHandle={false}
          />
        </div>
      )}
    </PreviewPanel>
  );
};

export default AdvancedVizPreview;
