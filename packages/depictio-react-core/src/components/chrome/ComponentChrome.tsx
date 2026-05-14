import React, { useEffect, useRef, useState } from 'react';
import { ActionIcon, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import MetadataPopover from './MetadataPopover';
import FullscreenButton from './FullscreenButton';
import DownloadButton from './DownloadButton';
import ResetButton from './ResetButton';
import './chrome.css';

export type ChromeAction = 'metadata' | 'fullscreen' | 'download' | 'reset' | 'drag';

export interface ComponentChromeProps {
  metadata: StoredMetadata;
  componentType: string;
  /** Title prop is ignored — renderers display their own titles. Kept for API parity. */
  title?: string;
  onResetFilter?: () => void;
  children: React.ReactNode;
  agGridApiRef?: React.RefObject<{ exportDataAsCsv: () => void } | null>;
  /** Element to fullscreen — defaults to the chrome wrapper itself. */
  fullscreenRef?: React.RefObject<HTMLDivElement | null>;
  /**
   * Additional action-icon nodes appended after the standard actions in the
   * chrome row. Editor uses this to inject the per-cell "..." edit menu so it
   * lives in the same hover cluster (single z-index, no overlap with the
   * input widget on interactive components).
   */
  extraActions?: React.ReactNode;
  /** When true, render the drag-handle action (3×3 grip). The actual drag is
   *  wired by react-grid-layout via `draggableHandle=".react-grid-dragHandle"`. */
  showDragHandle?: boolean;
  /** When true, an orange corner badge is rendered top-left to signal that
   *  this component is currently the SOURCE of an active dashboard filter
   *  (e.g. a scatter selection, a table row selection, a map polygon).
   *  Clicking the badge invokes `onResetFilter`. When this is true the
   *  redundant `'reset'` entry in the action-icon row is suppressed. */
  sourceFilterActive?: boolean;
}

/** View-accessible action visibility per component type. Mirrors the
 *  view-accessible subset of `_create_component_buttons` in
 *  `depictio/dash/layouts/edit.py:236-428`. ``reset`` is always last in the
 *  list so the chrome can hide it when ``onResetFilter`` isn't provided. */
export function actionsFor(componentType: string): ChromeAction[] {
  switch (componentType) {
    case 'figure':
    case 'map':
      return ['metadata', 'fullscreen', 'reset'];
    case 'multiqc':
      return ['metadata', 'fullscreen'];
    case 'table':
      return ['metadata', 'fullscreen', 'download', 'reset'];
    case 'interactive':
      return ['metadata', 'reset'];
    case 'card':
    case 'image':
    case 'jbrowse':
      return ['metadata'];
    default:
      return ['metadata'];
  }
}

/** Action-row orientation per component type. Mirrors `button_configs` in
 *  `depictio/dash/layouts/edit.py:282-334` (figure/multiqc/map = vertical,
 *  everything else horizontal). */
export function orientationFor(componentType: string): 'horizontal' | 'vertical' {
  switch (componentType) {
    case 'figure':
    case 'multiqc':
    case 'map':
      return 'vertical';
    default:
      return 'horizontal';
  }
}

/**
 * Per-component action chrome. Renders the wrapped component as-is and adds a
 * floating, hover-revealed action-icon row at top-right. The chrome itself is
 * background-less so the renderer's own Paper/styling shows through.
 *
 * Fullscreen: the chrome wrapper itself is the fullscreen target. The Plotly
 * div is found via querySelector inside the wrapper — no prop drilling into
 * each renderer needed.
 */
const ComponentChrome: React.FC<ComponentChromeProps> = ({
  metadata,
  componentType,
  onResetFilter,
  children,
  agGridApiRef,
  fullscreenRef: externalFullscreenRef,
  extraActions,
  showDragHandle = false,
  sourceFilterActive = false,
}) => {
  const localFullscreenRef = useRef<HTMLDivElement | null>(null);
  const fullscreenRef = externalFullscreenRef ?? localFullscreenRef;

  const [isFullscreenActive, setIsFullscreenActive] = useState(false);
  useEffect(() => {
    const onChange = () => {
      setIsFullscreenActive(document.fullscreenElement === fullscreenRef.current);
    };
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, [fullscreenRef]);

  // Source-filter badge replaces the per-component 'reset' action icon when
  // a filter is active from this component — keeps a single, visible reset
  // affordance instead of duplicating it.
  const actions = actionsFor(componentType).filter(
    (a) => !(a === 'reset' && sourceFilterActive),
  );
  const showSourceBadge = sourceFilterActive && Boolean(onResetFilter);

  const renderAction = (action: ChromeAction) => {
    switch (action) {
      case 'metadata':
        return <MetadataPopover key="metadata" metadata={metadata} />;
      case 'fullscreen':
        return <FullscreenButton key="fullscreen" fullscreenRef={fullscreenRef} />;
      case 'download':
        return (
          <DownloadButton
            key="download"
            componentType={componentType}
            metadata={metadata}
            agGridApiRef={agGridApiRef}
            fullscreenRef={fullscreenRef}
          />
        );
      case 'reset':
        // Skip reset entirely when the host didn't wire one up — keeps the
        // figure/table/map chrome clean for components without selection.
        if (!onResetFilter) return null;
        return <ResetButton key="reset" onResetFilter={onResetFilter} />;
    }
  };

  return (
    <div
      ref={fullscreenRef as React.RefObject<HTMLDivElement>}
      className={
        'depictio-component-chrome' +
        (isFullscreenActive ? ' fullscreen-active' : '')
      }
    >
      {showSourceBadge && (
        <span
          className="dgl-no-drag depictio-source-filter-badge"
          onMouseDown={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <Tooltip label="Reset filter from this component" withArrow>
            <ActionIcon
              variant="filled"
              color="orange"
              size="sm"
              radius="xl"
              onClick={() => onResetFilter?.()}
              aria-label="Reset filter from this component"
            >
              <Icon icon="bx:reset" width={14} height={14} />
            </ActionIcon>
          </Tooltip>
        </span>
      )}
      <Group
        gap={4}
        className={
          'depictio-component-actions' +
          (orientationFor(componentType) === 'vertical' ? ' depictio-actions-vertical' : '')
        }
        wrap="nowrap"
      >
        {/* Drag handle sits alongside the other action icons. drag is gated
         * via `draggableHandle=".react-grid-dragHandle"` on the GridLayout;
         * non-handle icons stop propagation to prevent accidental drag. */}
        {showDragHandle && (
          // Wrapped in a span so it sits as the same kind of flex child as
          // the other action icons; the wrapper itself carries the
          // `react-grid-dragHandle` class so a mousedown anywhere on it (or
          // its descendants) is recognised by react-grid-layout's
          // draggableHandle selector. NO stopPropagation here — drag MUST
          // bubble up.
          <span
            className="react-grid-dragHandle depictio-drag-handle"
            style={{ display: 'inline-flex', alignItems: 'center' }}
          >
            <ActionIcon
              variant="light"
              color="gray"
              size="sm"
              aria-label="Drag to move"
              tabIndex={-1}
            >
              <Icon icon="mdi:dots-grid" width={16} height={16} />
            </ActionIcon>
          </span>
        )}
        {actions.map((a) => (
          <span
            key={a}
            className="dgl-no-drag"
            style={{ display: 'inline-flex', alignItems: 'center' }}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {renderAction(a)}
          </span>
        ))}
        {extraActions && (
          <span
            className="dgl-no-drag"
            style={{ display: 'inline-flex', alignItems: 'center' }}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {extraActions}
          </span>
        )}
      </Group>
      {children}
    </div>
  );
};

export default ComponentChrome;
