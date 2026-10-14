import React from 'react';
import { Box } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import type { MsaColourScheme } from './protein';
import AdvancedVizFrame from './AdvancedVizFrame';

/**
 * Mirrors `HmmLogoConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface HmmLogoConfig {
  profile_source?: 'hmm' | 'msa';
  entity_col?: string;
  position_col?: string;
  model_col?: string;
  state_col?: string;
  letter_col?: string;
  emission_col?: string;
  insert_prob_col?: string | null;
  insert_length_col?: string | null;
  occupancy_col?: string | null;
  consensus_col?: string | null;
  rf_col?: string | null;
  cs_col?: string | null;
  msa_id_col?: string;
  seq_id_col?: string;
  sequence_col?: string;
  rank_col?: string | null;
  height_mode?: 'relent_abovebg' | 'relent_all' | 'probability';
  color_scheme?: MsaColourScheme;
  show_indel_rows?: boolean;
  show_consensus?: boolean;
  hits_wf_id?: string | null;
  hits_dc_id?: string | null;
  hits_dc_tag?: string | null;
  hits_model_col?: string;
  hits_entity_col?: string;
  hits_from_col?: string;
  hits_to_col?: string;
  hits_length_col?: string | null;
  hits_evalue_col?: string | null;
  hits_score_col?: string | null;
  hits_ali_from_col?: string | null;
  hits_ali_to_col?: string | null;
  hits_evalue_max?: number | null;
  max_hits?: number;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: HmmLogoConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * `hmm_logo`: the HMM logo of one profile HMM (Skylign / hmmlogo semantics), with an optional
 * hits-coverage lane.
 *
 * Registered with the dispatch, the builder and the selection helpers ahead of its drawing code.
 * Until the renderer lands the frame shows its explained empty state, which replaces its children:
 * the `depictio-hmm-logo` root below is the one the drawn tile mounts, and is not mounted yet.
 */
const HmmLogoRenderer: React.FC<Props> = ({ metadata }) => (
  <AdvancedVizFrame
    title={metadata.title || 'HMM logo'}
    subtitle={(metadata as any).description || (metadata as any).subtitle}
    emptyMessage="HMM logo renderer lands in a later commit of this PR"
  >
    <Box className="depictio-hmm-logo" style={{ width: '100%', height: '100%' }} />
  </AdvancedVizFrame>
);

export default HmmLogoRenderer;
