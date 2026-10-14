import React from 'react';
import { Box } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

/**
 * Mirrors `DomainArchitectureConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface DomainArchitectureConfig {
  entity_col?: string;
  start_col?: string;
  end_col?: string;
  label_col?: string;
  protein_length_col?: string | null;
  hmm_from_col?: string | null;
  hmm_to_col?: string | null;
  hmm_length_col?: string | null;
  hmm_coverage_col?: string | null;
  evalue_col?: string | null;
  source_col?: string | null;
  description_col?: string | null;
  accession_col?: string | null;
  view?: 'proteins' | 'architectures';
  max_architectures?: number;
  max_proteins?: number;
  evalue_threshold?: number | null;
  sources?: string[] | null;
  scale?: 'shared' | 'per_protein';
  color_by?: 'label' | 'source';
  partial_coverage?: number;
  position_col_for_selection?: string;
  label_selection?: boolean;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DomainArchitectureConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * `domain_architecture`: proteins as a backbone with coloured domains and partial-match edges, or
 * grouped by architecture with counts.
 *
 * Registered with the dispatch, the builder and the selection helpers ahead of its drawing code.
 * Until the renderer lands the frame shows its explained empty state, which replaces its children:
 * the `depictio-domain-architecture` root below is the one the drawn tile mounts, and is not
 * mounted yet.
 */
const DomainArchitectureRenderer: React.FC<Props> = ({ metadata }) => (
  <AdvancedVizFrame
    title={metadata.title || 'Domain architecture'}
    subtitle={(metadata as any).description || (metadata as any).subtitle}
    emptyMessage="Domain architecture renderer lands in a later commit of this PR"
  >
    <Box className="depictio-domain-architecture" style={{ width: '100%', height: '100%' }} />
  </AdvancedVizFrame>
);

export default DomainArchitectureRenderer;
