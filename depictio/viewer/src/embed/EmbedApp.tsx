/**
 * Bare shell for an embedded Depictio component.
 *
 * Deliberately minimal: one `ComponentRenderer` filling the viewport, no
 * navigation, no dashboard chrome, no provenance. The host page owns the layout
 * around it, so anything we add here fights with it.
 *
 * `dashboardId` is a placeholder — the offline api shim ignores it and reads the
 * embedded payload instead — but `ComponentRenderer` requires it to be truthy
 * before it will render figure / table / map / image / multiqc types.
 */
import React from 'react';
import { Alert, Box } from '@mantine/core';
import { ComponentRenderer } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

import type { EmbedGlobal } from '../offline/mockApi';

/** Keeps a renderer crash inside the frame instead of blanking the host page. */
class EmbedBoundary extends React.Component<
  { children: React.ReactNode },
  { error?: string }
> {
  state: { error?: string } = {};

  static getDerivedStateFromError(err: unknown) {
    return { error: err instanceof Error ? err.message : String(err) };
  }

  render() {
    if (this.state.error) {
      return (
        <Alert color="red" variant="light" title="Component failed to render">
          {this.state.error}
        </Alert>
      );
    }
    return this.props.children;
  }
}

interface Props {
  payload: EmbedGlobal;
}

const EmbedApp: React.FC<Props> = ({ payload }) => {
  const metadata = payload.component as unknown as StoredMetadata;

  if (!metadata || !metadata.component_type) {
    return (
      <Alert color="red" variant="light" title="Nothing to render">
        This embed carries no component metadata.
      </Alert>
    );
  }

  return (
    <Box
      style={{
        width: '100%',
        // Fill the iframe rather than the content's natural height, so the host
        // page controls the size purely through the iframe's own dimensions.
        height: '100vh',
        overflow: 'hidden',
        padding: 8,
        boxSizing: 'border-box',
      }}
    >
      <EmbedBoundary>
        <ComponentRenderer
          metadata={metadata}
          filters={[]}
          dashboardId="embed"
          cardValue={
            (payload.data?.cards?.values as Record<string, unknown> | undefined)?.[
              String(metadata.index)
            ]
          }
          cardSecondaryValues={
            (
              payload.data?.cards?.secondary as
                | Record<string, Record<string, unknown>>
                | undefined
            )?.[String(metadata.index)]
          }
        />
      </EmbedBoundary>
    </Box>
  );
};

export default EmbedApp;
