import React from 'react';

import { StoredMetadata } from '../../api';
import PrBenchmarkRenderer from './PrBenchmarkRenderer';

type PrBenchmarkProps = React.ComponentProps<typeof PrBenchmarkRenderer>;

/** `roc_pr_curve` is a view of `pr_benchmark`, not a renderer of its own.
 *
 *  The threshold sweep and the operating points picked off it are one table
 *  read at two zoom levels, so they share `PrBenchmarkRenderer` and a control
 *  in the tile's header. This file stays because `roc_pr_curve` is a kind
 *  string stored in dashboards: it pins the sweep view and forwards everything
 *  else, so a curve authored before the merge keeps rendering and gains the
 *  overlay view alongside it.
 *
 *  It deliberately reads no config key of its own: the config travels whole to
 *  the survivor, which is the only place that knows what the keys mean. */
interface Props extends Omit<PrBenchmarkProps, 'metadata'> {
  metadata: StoredMetadata & { viz_kind?: string; config?: Record<string, unknown> };
}

const RocPrCurveRenderer: React.FC<Props> = (props) => (
  <PrBenchmarkRenderer
    {...props}
    metadata={
      {
        ...props.metadata,
        viz_kind: 'pr_benchmark',
        config: { ...(props.metadata.config ?? {}), view: 'roc' },
      } as unknown as PrBenchmarkProps['metadata']
    }
  />
);

export default RocPrCurveRenderer;
