import React from 'react';
import { Alert } from '@mantine/core';
import type { StoredMetadata } from '../../api';

interface Props {
  metadata: StoredMetadata;
}

/**
 * Placeholder for the `transcript_structure` kind. The model side (roles, config, sampling,
 * metadata) is registered; the renderer is being written in parallel and
 * replaces this file wholesale.
 */
const TranscriptStructureRenderer: React.FC<Props> = ({ metadata }) => (
  <Alert color="gray" title="Transcript structure">
    Renderer not implemented yet for {String(metadata.viz_kind)}.
  </Alert>
);

export default TranscriptStructureRenderer;
