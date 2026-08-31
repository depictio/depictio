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
 *
 * ## Embedding an interactive control
 *
 * An `interactive` component renders here as the real Depictio control, but a
 * selection inside a cross-origin frame is invisible to the page around it —
 * the host cannot read frame state, and the frame cannot reach into the host.
 * `postMessage` is the only channel across that boundary, so a selection is
 * posted out as:
 *
 *     { source: "depictio-embed", type: "filter",
 *       componentId, dcId, filter: { interactive_component_type, column_name, value } }
 *
 * The host listens, and forwards the filter to its other components as
 * `?filters=[…]`. That makes an embedded control usable as the filter UI for a
 * page whose figures are plain JSON exports — the frame supplies the widget,
 * the host owns the wiring.
 *
 * `targetOrigin` is `"*"` because the bundle is built once and served to every
 * allow-listed embedder; it cannot know at build time which origin will frame
 * it. Nothing sensitive travels in the message — it carries a column name and a
 * value the user just picked — and the host must verify `event.origin` itself,
 * which is the check that actually matters.
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

/** Wire protocol marker, so a host can tell our messages from anyone else's. */
const MESSAGE_SOURCE = 'depictio-embed';

const EmbedApp: React.FC<Props> = ({ payload }) => {
  const metadata = payload.component as unknown as StoredMetadata;

  const publishFilter = React.useCallback(
    (filter: unknown) => {
      if (typeof window === 'undefined' || window.parent === window) return;
      window.parent.postMessage(
        {
          source: MESSAGE_SOURCE,
          type: 'filter',
          componentId: String((metadata as { index?: unknown })?.index ?? ''),
          dcId: String((metadata as { dc_id?: unknown })?.dc_id ?? ''),
          filter,
        },
        '*',
      );
    },
    [metadata],
  );

  // Tell the host the frame is live and what it is, so a page can lay out
  // around a control before the user touches it.
  React.useEffect(() => {
    if (typeof window === 'undefined' || window.parent === window) return;
    window.parent.postMessage(
      {
        source: MESSAGE_SOURCE,
        type: 'ready',
        componentId: String((metadata as { index?: unknown })?.index ?? ''),
        componentType: metadata?.component_type ?? null,
      },
      '*',
    );
  }, [metadata]);

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
          onFilterChange={publishFilter}
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
