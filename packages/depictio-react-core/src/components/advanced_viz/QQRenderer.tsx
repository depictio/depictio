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
 * `qq` is a view of the differential-expression tile, not a kind of its own.
 *
 * The QQ plot asks whether the p-value column behaves, which is the question a
 * reader asks immediately before or after reading the volcano built from the
 * same column. They share one tile, one fetch and one switch in the header (see
 * `VolcanoRenderer`), and the model resolves a stored `kind: qq` to `volcano`
 * with `view: qq`.
 *
 * The file stays because the kind string stays: dashboards in Mongo, shipped
 * YAML, `.db_seeds` and catalog `renders_as` entries all name it. It points the
 * survivor's significance binding at the p-value column so the server keeps the
 * significant tail of the table whole.
 */
const QQRenderer: React.FC<Props> = (props) => {
  const metadata = useMemo(() => {
    const config = (props.metadata.config || {}) as Record<string, unknown>;
    return {
      ...props.metadata,
      viz_kind: 'volcano',
      config: {
        ...config,
        view: 'qq',
        significance_col: config.significance_col ?? config.p_value_col,
        significance_is_neg_log10: false,
      },
    };
  }, [props.metadata]);

  return <VolcanoRenderer {...props} metadata={metadata as never} />;
};

export default QQRenderer;
