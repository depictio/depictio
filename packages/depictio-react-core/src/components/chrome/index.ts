import React from 'react';

import ComponentChrome from './ComponentChrome';
import type { StoredMetadata } from '../../api';

export { default as ComponentChrome, actionsFor } from './ComponentChrome';
export type { ComponentChromeProps, ChromeAction } from './ComponentChrome';
export { default as MetadataPopover } from './MetadataPopover';
export { default as FullscreenButton } from './FullscreenButton';
export { default as DownloadButton } from './DownloadButton';
export { default as ResetButton } from './ResetButton';

export interface WrapWithChromeOpts {
  onResetFilter?: () => void;
  agGridApiRef?: React.RefObject<{ exportDataAsCsv: () => void } | null>;
  fullscreenRef?: React.RefObject<HTMLDivElement | null>;
}

/**
 * Convenience helper for ComponentRenderer — wraps `children` in a
 * `ComponentChrome`. Plotly's div is auto-located inside the chrome wrapper
 * via querySelector, so renderers don't need to expose internal refs.
 */
export function wrapWithChrome(
  componentType: string,
  metadata: StoredMetadata,
  title: string | undefined,
  children: React.ReactNode,
  opts?: WrapWithChromeOpts,
): React.ReactNode {
  return React.createElement(
    ComponentChrome,
    {
      componentType,
      metadata,
      title,
      children,
      onResetFilter: opts?.onResetFilter,
      agGridApiRef: opts?.agGridApiRef,
      fullscreenRef: opts?.fullscreenRef,
    },
  );
}
