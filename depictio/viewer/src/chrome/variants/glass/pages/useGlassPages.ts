import React from 'react';
import { useChromeStyle } from 'depictio-react-core';

import { useChromeVariant } from '../../index';

export const GLASS_ID = 'glass';

/** Applies the chrome variant on a page app and says whether Glass is on. */
export function useGlassPages(): boolean {
  useChromeVariant();
  return useChromeStyle().id === GLASS_ID;
}

/** Marks <html> while a Glass page shell is mounted, so the surfaces it
 *  portals (modals, menus, popovers) can be styled for the pages only. */
export function usePageMark(name: string): void {
  React.useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-gp-page', name);
    return () => root.removeAttribute('data-gp-page');
  }, [name]);
}
