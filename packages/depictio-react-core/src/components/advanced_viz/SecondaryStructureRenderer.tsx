import React from 'react';
import { Box } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

/**
 * Mirrors `SecondaryStructureConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface SecondaryStructureConfig {
  entity_col?: string;
  position_col?: string;
  residue_col?: string | null;
  state_col?: string;
  source_col?: string | null;
  reference_source?: string | null;
  p_helix_col?: string | null;
  p_strand_col?: string | null;
  p_coil_col?: string | null;
  confidence_col?: string | null;
  show_probabilities?: boolean;
  show_agreement?: boolean;
  show_segments?: boolean;
  show_composition?: boolean;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SecondaryStructureConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * `secondary_structure`: a protein's secondary structure as a topology ribbon, confidence shading,
 * P(H/E/C) lanes and a comparison of sources.
 *
 * Registered with the dispatch, the builder and the selection helpers ahead of its drawing code.
 * Until the renderer lands the frame shows its explained empty state, which replaces its children:
 * the `depictio-secondary-structure` root below is the one the drawn tile mounts, and is not
 * mounted yet.
 */
const SecondaryStructureRenderer: React.FC<Props> = ({ metadata }) => (
  <AdvancedVizFrame
    title={metadata.title || 'Secondary structure'}
    subtitle={(metadata as any).description || (metadata as any).subtitle}
    emptyMessage="Secondary structure renderer lands in a later commit of this PR"
  >
    <Box className="depictio-secondary-structure" style={{ width: '100%', height: '100%' }} />
  </AdvancedVizFrame>
);

export default SecondaryStructureRenderer;
