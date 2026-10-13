import React from 'react';

import { HeaderView, useHeaderModel } from '../Header';
import type { HeaderProps } from '../Header';
import { useTabNav } from '../Sidebar';
import type { SidebarProps } from '../Sidebar';
import { useDashboardShell } from '../variants';
import type { DashboardShellProps } from './types';

export interface ShellHostProps extends Omit<DashboardShellProps, 'header' | 'nav'> {
  headerProps: HeaderProps;
  nav: Omit<DashboardShellProps['nav'], 'model'> &
    Pick<SidebarProps, 'tabs' | 'activeId' | 'guide' | 'versionId'>;
}

/**
 * Builds the header and tab models and hands the page to the active chrome
 * style's Shell. Mounted inside the page's providers (brand scope above all),
 * so the models read the dashboard's own branding.
 */
const ShellHost: React.FC<ShellHostProps> = ({ headerProps, nav, ...rest }) => {
  const Shell = useDashboardShell();
  const model = useHeaderModel(headerProps);
  const { tabs, activeId, guide, versionId, ...navState } = nav;
  const navModel = useTabNav({ tabs, activeId, guide, versionId });
  return (
    <Shell
      {...rest}
      header={{ model, node: <HeaderView model={model} /> }}
      nav={{ ...navState, model: navModel }}
    />
  );
};

export default ShellHost;
