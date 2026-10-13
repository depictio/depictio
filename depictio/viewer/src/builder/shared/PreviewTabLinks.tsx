/**
 * Lets a builder preview resolve `tab:` names the way the viewer does, so a
 * tab accent, a tab link or a card's link shows its tab's colour and icon
 * while it is being authored.
 *
 * The links themselves are inert here: following one would leave the builder
 * and lose the unsaved component.
 */
import React from 'react';
import type { DashboardSummary } from 'depictio-react-core';
import TabLinkProvider from '../../chrome/TabLinkProvider';

const PreviewTabLinks: React.FC<{ tabs: DashboardSummary[]; children: React.ReactNode }> = ({
  tabs,
  children,
}) => (
  <TabLinkProvider tabs={tabs}>
    <div
      // `contents` keeps the wrapper out of the preview card's flex layout.
      style={{ display: 'contents' }}
      onClickCapture={(e) => {
        if ((e.target as HTMLElement).closest('a[href]')) e.preventDefault();
      }}
    >
      {children}
    </div>
  </TabLinkProvider>
);

export default PreviewTabLinks;
