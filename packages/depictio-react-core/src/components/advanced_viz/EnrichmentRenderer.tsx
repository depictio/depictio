import React from 'react';

import { StoredMetadata } from '../../api';
import DotPlotRenderer from './DotPlotRenderer';

type DotPlotProps = React.ComponentProps<typeof DotPlotRenderer>;

/** `enrichment` is a view of `dot_plot`, not a renderer of its own.
 *
 *  A pathway dot plot is the marker dot plot read over a gene-set table: the
 *  same marks, the same size and colour channels, different axes. The two now
 *  share `DotPlotRenderer`, and this file stays because `enrichment` is a kind
 *  string stored in dashboards. It pins the view that kind means and forwards
 *  everything else, so an enrichment tile authored before the merge keeps
 *  rendering and gains whatever the shared renderer grows.
 *
 *  It deliberately reads no config key of its own: the config travels whole to
 *  the survivor, which is the only place that knows what the keys mean. */
interface Props extends Omit<DotPlotProps, 'metadata'> {
  metadata: StoredMetadata & { viz_kind?: string; config?: Record<string, unknown> };
}

const EnrichmentRenderer: React.FC<Props> = (props) => (
  <DotPlotRenderer
    {...props}
    metadata={
      {
        ...props.metadata,
        viz_kind: 'dot_plot',
        config: { ...(props.metadata.config ?? {}), view: 'enrichment' },
      } as unknown as DotPlotProps['metadata']
    }
  />
);

export default EnrichmentRenderer;
