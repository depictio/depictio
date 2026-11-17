import React, { Suspense } from 'react';
import { Center, Loader, Modal } from '@mantine/core';

import type { JBrowseSessionResponse } from '../../api';

// Each view is its own chunk (the split view and the circular view pull in
// `@jbrowse/react-app2` and `react-circular-genome-view2`), fetched when the
// reader first opens one and never otherwise.
const BreakpointView = React.lazy(() => import('./views/BreakpointView'));
const CircularView = React.lazy(() => import('./views/CircularView'));

export type JBrowseExtraView = 'breakpoint' | 'circular';

export const EXTRA_VIEW_TITLE: Record<JBrowseExtraView, string> = {
  breakpoint: 'Breakpoint view',
  circular: 'Circular view',
};

interface JBrowseViewsModalProps {
  /** The view to show; null keeps the dialog closed. */
  view: JBrowseExtraView | null;
  onClose: () => void;
  payload: JBrowseSessionResponse | null;
  /** The two sides of the call the tile is on (the breakpoint view's two panes). */
  locus: string;
  mateLocus: string;
  openTrackIds: string[];
  /** The fullscreen element when the tile is fullscreen: the dialog is
   *  portaled into it, or it would be painted behind. */
  portalTarget?: HTMLElement | null;
}

/** A large dialog over the tile for the breakpoint split view and the circular
 *  view. Mounted only while open, so closing it drops JBrowse's second state tree. */
const JBrowseViewsModal: React.FC<JBrowseViewsModalProps> = ({
  view,
  onClose,
  payload,
  locus,
  mateLocus,
  openTrackIds,
  portalTarget,
}) => (
  <Modal
    opened={view !== null && payload !== null}
    onClose={onClose}
    title={view ? EXTRA_VIEW_TITLE[view] : ''}
    size="min(1200px, 94vw)"
    centered
    keepMounted={false}
    portalProps={{ target: portalTarget ?? undefined }}
    data-testid="jbrowse-views-modal"
  >
    {view && payload && (
      <Suspense
        fallback={
          <Center mih={240}>
            <Loader size="sm" />
          </Center>
        }
      >
        {view === 'breakpoint' ? (
          <BreakpointView
            payload={payload}
            locus={locus}
            mateLocus={mateLocus}
            openTrackIds={openTrackIds}
          />
        ) : (
          <CircularView
            payload={payload}
            locus={locus}
            mateLocus={mateLocus}
            openTrackIds={openTrackIds}
          />
        )}
      </Suspense>
    )}
  </Modal>
);

export default JBrowseViewsModal;
