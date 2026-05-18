/**
 * Live preview for the Text builder. Renders the canonical TextRenderer so
 * what the user sees here matches what the viewer/editor will render after
 * save — no data fetching needed.
 */
import React from 'react';
import { TextRenderer } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';

const TextPreview: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    order?: number | string;
    alignment?: string;
    body?: string;
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
    body: config.body ?? '',
  };

  return (
    <PreviewPanel minHeight={200}>
      <TextRenderer metadata={fakeMetadata} placeholder />
    </PreviewPanel>
  );
};

export default TextPreview;
