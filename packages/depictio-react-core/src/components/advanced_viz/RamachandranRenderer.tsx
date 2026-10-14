import React from 'react';
import { Box } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

/**
 * Mirrors `RamachandranConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface RamachandranConfig {
  structure_source?: 'file' | 'resolve';
  structure_wf_id?: string | null;
  structure_dc_id?: string | null;
  structure_dc_tag?: string | null;
  uniprot_col?: string | null;
  gene_col?: string | null;
  sequence_col?: string | null;
  taxon?: number;
  entity_col?: string;
  position_col?: string;
  chain_col?: string | null;
  value_col?: string | null;
  category_col?: string | null;
  color_mode?: 'plddt' | 'residue_class' | 'secondary_structure' | 'value' | 'category' | 'chain';
  show_regions?: boolean;
  residue_classes?: Array<'general' | 'glycine' | 'proline' | 'pre_proline'> | null;
  marker_size?: number;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RamachandranConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * `ramachandran`: the phi/psi angles of every residue, computed from the structure's backbone and
 * drawn as a scatter.
 *
 * Registered with the dispatch, the builder and the selection helpers ahead of its drawing code.
 * Until the renderer lands the frame shows its explained empty state, which replaces its children:
 * the `depictio-ramachandran` root below is the one the drawn tile mounts, and is not mounted yet.
 */
const RamachandranRenderer: React.FC<Props> = ({ metadata }) => (
  <AdvancedVizFrame
    title={metadata.title || 'Ramachandran plot'}
    subtitle={(metadata as any).description || (metadata as any).subtitle}
    emptyMessage="Ramachandran plot renderer lands in a later commit of this PR"
  >
    <Box className="depictio-ramachandran" style={{ width: '100%', height: '100%' }} />
  </AdvancedVizFrame>
);

export default RamachandranRenderer;
