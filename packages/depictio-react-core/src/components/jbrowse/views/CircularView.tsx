import React, { useMemo } from 'react';
import { Box, Text } from '@mantine/core';
import { createViewState } from '@jbrowse/react-circular-genome-view2';

import type { JBrowseSessionResponse } from '../../../api';
import { ExtraViewFrame, useExtraViewTheme } from './ExtraViewFrame';
import { absolutizeUris, buildCircularOptions, type ExtraViewPayload } from './sessions';

export interface CircularViewProps {
  payload: JBrowseSessionResponse;
  /** Part of the shared contract with `BreakpointView`; the circular view always
   *  spans the whole assembly, so it does not read the loci. */
  locus?: string;
  mateLocus?: string;
  openTrackIds?: string[];
}

/**
 * JBrowse's circular genome view of the structural variants: the tracks listed
 * in `payload.sv_track_ids` (SV VCFs, drawn as chords) on the payload's
 * assembly. Load it with `React.lazy`, so the circular model stays out of the
 * main bundle.
 */
const CircularView: React.FC<CircularViewProps> = ({ payload }) => {
  const jbTheme = useExtraViewTheme();

  const built = useMemo(() => {
    try {
      const { options, trackIds } = buildCircularOptions(
        absolutizeUris(payload as unknown as ExtraViewPayload, window.location.origin),
        jbTheme,
      );
      if (trackIds.length === 0) return { state: null, error: null, empty: true };
      const state = createViewState(
        options as unknown as Parameters<typeof createViewState>[0],
      );
      return { state, error: null as string | null, empty: false };
    } catch (e) {
      return { state: null, error: e instanceof Error ? e.message : String(e), empty: false };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload]);

  if (built.empty) {
    return (
      <Text size="sm" c="dimmed" p="md" data-testid="jbrowse-circular-empty">
        No structural variant track to draw.
      </Text>
    );
  }
  if (built.error || !built.state) {
    return (
      <Text size="sm" c="red" p="md" data-testid="jbrowse-circular-error">
        Circular view failed: {built.error}
      </Text>
    );
  }
  const session = built.state.session as unknown as {
    view: Parameters<typeof ExtraViewFrame>[0]['view'];
  };
  return (
    <Box data-testid="jbrowse-circular-view" style={{ height: '100%', minHeight: 0 }}>
      <ExtraViewFrame session={built.state.session} view={session.view} jbTheme={jbTheme} fillHeight />
    </Box>
  );
};

export default CircularView;
