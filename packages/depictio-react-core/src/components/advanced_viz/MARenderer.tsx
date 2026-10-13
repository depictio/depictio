import React, { useMemo } from 'react';

import { InteractiveFilter, StoredMetadata } from '../../api';
import type { GroupRenderState } from '../../selectionGroups';
import VolcanoRenderer from './VolcanoRenderer';

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: Record<string, unknown> };
  filters: InteractiveFilter[];
  refreshTick?: number;
  groupRender?: GroupRenderState;
}

/**
 * `ma` is a view of the differential-expression tile, not a kind of its own.
 *
 * A volcano and an MA plot are the same rows with a different x: same
 * thresholds, same UP / DN / NS tiers, same labels, same selection. They now
 * share one tile with a switch in its header (see `VolcanoRenderer`), and the
 * model resolves a stored `kind: ma` to `volcano` with `view: ma`.
 *
 * This file stays because the kind string stays: dashboards in Mongo, shipped
 * YAML, `.db_seeds` and catalog `renders_as` entries all name it, and the
 * dispatch's `RENDERERS` map is read by the alignment tests. It maps the two
 * field names the retired MA config used onto the survivor's, so a config
 * written before the merge opens on the right axes.
 */
const MARenderer: React.FC<Props> = (props) => {
  const metadata = useMemo(() => {
    const config = (props.metadata.config || {}) as Record<string, unknown>;
    return {
      ...props.metadata,
      viz_kind: 'volcano',
      config: {
        ...config,
        view: 'ma',
        // The volcano view needs an effect column; an MA-authored config only
        // named the fold change, which is the same quantity.
        effect_size_col: config.effect_size_col ?? config.log2_fold_change_col,
      },
    };
  }, [props.metadata]);

  return <VolcanoRenderer {...props} metadata={metadata as never} />;
};

export default MARenderer;
