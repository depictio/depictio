import React from 'react';
import { Box } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import type { ColourScale } from './colourScales';
import AdvancedVizFrame from './AdvancedVizFrame';

/**
 * Mirrors `PaeMatrixConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface PaeMatrixConfig {
  entity_col?: string;
  position_col?: string;
  value_col?: string | null;
  chain_col?: string | null;
  pae_wf_id?: string | null;
  pae_dc_id?: string | null;
  pae_dc_tag?: string | null;
  max_pae?: number | null;
  colour_scale?: ColourScale | null;
  brush?: 'diagonal' | 'rectangle';
  show_plddt?: boolean;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PaeMatrixConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * `pae_matrix`: the predicted aligned error of one structure as a residue by residue heatmap, read
 * from the entity's PAE file.
 *
 * Registered with the dispatch, the builder and the selection helpers ahead of its drawing code.
 * Until the renderer lands the frame shows its explained empty state, which replaces its children:
 * the `depictio-pae-matrix` root below is the one the drawn tile mounts, and is not mounted yet.
 */
const PaeMatrixRenderer: React.FC<Props> = ({ metadata }) => (
  <AdvancedVizFrame
    title={metadata.title || 'PAE matrix'}
    subtitle={(metadata as any).description || (metadata as any).subtitle}
    emptyMessage="PAE matrix renderer lands in a later commit of this PR"
  >
    <Box className="depictio-pae-matrix" style={{ width: '100%', height: '100%' }} />
  </AdvancedVizFrame>
);

export default PaeMatrixRenderer;
