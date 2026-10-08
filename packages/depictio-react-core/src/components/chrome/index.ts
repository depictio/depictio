import React from 'react';

import ComponentChrome from './ComponentChrome';
import type { StoredMetadata } from '../../api';

export { default as ComponentChrome, actionsFor } from './ComponentChrome';
export { canDuplicate } from './chromeActions';
export type { ComponentChromeProps, ChromeAction } from './ComponentChrome';
export { default as MetadataPopover } from './MetadataPopover';
export { default as MetadataBody } from './MetadataBody';
export { default as CatalogButton } from './CatalogButton';
export { default as CatalogOrigin } from './CatalogOrigin';
export { default as FullscreenButton } from './FullscreenButton';
export { default as InspectButton } from './InspectButton';
export { InspectorProvider, useInspectorControl } from './InspectorContext';
export type { InspectorControl } from './InspectorContext';
export { default as CommentsButton } from './CommentsButton';
export { CommentsControlProvider, useCommentsControl } from './CommentsContext';
export type { CommentsControl } from './CommentsContext';
export { default as DownloadButton } from './DownloadButton';
export { default as ResetButton } from './ResetButton';
export { default as ClearSelectionButton } from './ClearSelectionButton';
export { default as LoadAllButton } from './LoadAllButton';
export type { LoadAllState } from './LoadAllButton';
export { SelectionHintAction } from './SaveGroupAction';
export {
  EDIT_MENU_STYLE,
  FULLSCREEN_EXIT_ICON,
  LOAD_ALL_ACTIVE_ICON,
  TILE_ACTION_STYLE,
} from './actionStyles';
export type { EditMenuStyleKey, TileActionStyle, TileActionStyleKey } from './actionStyles';

export interface WrapWithChromeOpts {
  onResetFilter?: () => void;
  agGridApiRef?: React.RefObject<{ exportDataAsCsv: () => void } | null>;
  fullscreenRef?: React.RefObject<HTMLDivElement | null>;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
  sourceFilterActive?: boolean;
  selectionCount?: number;
  compact?: boolean;
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
      extraActions: opts?.extraActions,
      showDragHandle: opts?.showDragHandle,
      sourceFilterActive: opts?.sourceFilterActive,
      selectionCount: opts?.selectionCount,
      compact: opts?.compact,
    },
  );
}
