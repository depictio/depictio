import React, { useMemo } from 'react';
import { Box, Text } from '@mantine/core';
import { createViewState } from '@jbrowse/react-app2';

import type { JBrowseSessionResponse } from '../../../api';
import { ExtraViewFrame, useExtraViewTheme } from './ExtraViewFrame';
import { absolutizeUris, buildBreakpointConfig, type ExtraViewPayload } from './sessions';

export interface BreakpointViewProps {
  payload: JBrowseSessionResponse;
  /** The locus on the top row (the call's own side). */
  locus: string;
  /** The locus on the bottom row (the call's mate). */
  mateLocus: string;
  /** Ids of the tracks open in the linear view; alignment tracks are listed first. */
  openTrackIds: string[];
}

type AppViewState = ReturnType<typeof createViewState>;

/**
 * JBrowse's Breakpoint split view: two stacked linear views, joined by the
 * split reads and discordant read pairs of the alignment tracks (and by the
 * breakends of variant tracks) that are open in both rows.
 *
 * It needs the full-app model of `@jbrowse/react-app2`, which already bundles
 * `@jbrowse/plugin-breakpoint-split-view`, since the embeddable linear view
 * only hosts one view type. Only the view itself is rendered, not the app's
 * menus or dock. Load it with `React.lazy`: this module is the whole app model
 * and must stay out of the main bundle.
 */
const BreakpointView: React.FC<BreakpointViewProps> = ({
  payload,
  locus,
  mateLocus,
  openTrackIds,
}) => {
  const jbTheme = useExtraViewTheme();
  const inputKey = `${locus}|${mateLocus}|${openTrackIds.join(',')}`;

  // The theme is baked into the model at creation, so a colour scheme switch
  // while the view is open is picked up by the MUI theme of the frame instead
  // of rebuilding the view (which would drop the user's navigation).
  const built = useMemo(() => {
    try {
      const { config } = buildBreakpointConfig(
        absolutizeUris(payload as unknown as ExtraViewPayload, window.location.origin),
        { locus, mateLocus, openTrackIds },
        jbTheme,
      );
      const state: AppViewState = createViewState({
        config: config as unknown as Parameters<typeof createViewState>[0]['config'],
      });
      return { state, error: null as string | null };
    } catch (e) {
      return { state: null, error: e instanceof Error ? e.message : String(e) };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload, inputKey]);

  if (built.error || !built.state) {
    return (
      <Text size="sm" c="red" p="md" data-testid="jbrowse-breakpoint-error">
        Breakpoint view failed: {built.error}
      </Text>
    );
  }
  const session = built.state.session as unknown as {
    views: Array<Parameters<typeof ExtraViewFrame>[0]['view']>;
  };
  const view = session.views[0];
  return (
    <Box data-testid="jbrowse-breakpoint-view" style={{ height: '100%', minHeight: 0 }}>
      <ExtraViewFrame session={built.state.session} view={view} jbTheme={jbTheme} />
    </Box>
  );
};

export default BreakpointView;
