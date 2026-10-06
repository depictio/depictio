/**
 * Live preview for the Text builder. Renders the canonical TextRenderer so
 * what the user sees here matches what the viewer/editor will render after
 * save — no data fetching needed.
 */
import React from 'react';
import { TextRenderer } from 'depictio-react-core';
import type { DashboardSummary, StoredMetadata } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';
import PreviewTabLinks from '../shared/PreviewTabLinks';

const TextPreview: React.FC<{ tabs: DashboardSummary[] }> = ({ tabs }) => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    order?: number | string;
    alignment?: string;
    vertical_alignment?: string;
    body?: string;
    surface?: StoredMetadata['surface'];
    accent?: string;
  };
  const componentId = useBuilderStore((s) => s.componentId);

  // Synthesize a minimal StoredMetadata for the renderer. wf_id / dc_id are
  // intentionally omitted — text components don't need data binding.
  const fakeMetadata: StoredMetadata = {
    index: componentId ?? 'preview',
    component_type: 'text',
    title: config.title ?? '',
    order:
      typeof config.order === 'number'
        ? config.order
        : config.order
          ? Number(config.order)
          : 1,
    alignment: config.alignment ?? 'left',
    vertical_alignment: config.vertical_alignment ?? 'center',
    body: config.body ?? '',
    surface: config.surface ?? 'none',
    accent: config.accent,
  };

  return (
    <PreviewPanel minHeight={200}>
      {/* With the tab family, `tab:` accents, tab links and tab tiles render
          as they will on the dashboard instead of as plain text. */}
      <PreviewTabLinks tabs={tabs}>
        <TextRenderer metadata={fakeMetadata} placeholder />
      </PreviewTabLinks>
    </PreviewPanel>
  );
};

export default TextPreview;
