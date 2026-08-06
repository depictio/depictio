import React, { useEffect, useRef, useState } from 'react';
import { ActionIcon, Group } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import { StaticTierBadge } from './StaticBadgeContext';
import MetadataPopover from './MetadataPopover';
import FullscreenButton from './FullscreenButton';
import InspectButton from './InspectButton';
import { useInspectorControl } from './InspectorContext';
import DownloadButton from './DownloadButton';
import ResetButton from './ResetButton';
import './chrome.css';

export type ChromeAction =
  | 'inspect'
  | 'metadata'
  | 'fullscreen'
  | 'download'
  | 'reset'
  | 'drag';

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
  /** When true, this component is the SOURCE of an active dashboard filter
   *  (e.g. a scatter selection, a table row selection, a map polygon). The
   *  reset action icon stays in its original position in the chrome row but
   *  switches to a filled-orange style; otherwise it renders disabled in the
   *  light variant. The action-icon order is preserved either way. Whether it
   *  also stays visible without hover is a further question — see
   *  `persistentReset` below. */
  sourceFilterActive?: boolean;
  /**
   * Render the action row at the density of a filter-panel row rather than of a
   * dashboard tile.
   *
   * The row floats at the component's top-right, and a tile has a corner to
   * spare there. An interactive control does not: it is a title line and its
   * input, so a `sm` ActionIcon lands on the select's chevron or the slider's
   * track. It also puts a second, larger set of icons next to the `xs` ones an
   * `InteractiveGroupCard` header already carries, which reads as two unrelated
   * toolbars stacked in a ~280px column rather than as one hierarchy.
   *
   * Only the chrome's own geometry changes — which actions exist, and what they
   * do, is unaffected. The sizing itself lives in chrome.css, because each
   * action is its own component with its own hard-coded `size`.
   */
  compact?: boolean;
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
    case 'advanced_viz':
      // metadata + fullscreen + reset. Download is dropped — advanced viz
      // export is handled by the Settings popover (Newick export for trees,
      // PNG snapshots are out-of-scope for the multi-trace plotly figures).
      // The Settings + Show-data ActionIcons are injected via extraActions
      // from ComponentRenderer's advanced_viz dispatch.
      return ['metadata', 'fullscreen', 'reset'];
    case 'card':
    case 'image':
    case 'jbrowse':
      return ['metadata'];
    case 'text':
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
    case 'advanced_viz':
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
  compact = false,
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

  // Prepended rather than folded into `actionsFor`, which stays a pure function
  // of the component type: whether this action exists is a property of the app
  // (is the inspector enabled?), not of the component. A null control — the
  // default when no provider is mounted — leaves the chrome exactly as it was.
  const inspector = useInspectorControl();
  const actions: ChromeAction[] = [];
  if (inspector) actions.push('inspect');
  actions.push(...actionsFor(componentType));

  /**
   * Whether the reset icon stays on screen without hover.
   *
   * The action row floats over the component, so a persistent icon costs
   * whatever is under the top-right corner. A figure, table or map has plot
   * area to spare there, and it needs the icon: a scatter selection or a
   * highlighted row is easy to miss, and nothing else on screen says the
   * component is filtering the dashboard.
   *
   * An interactive control has neither. Its frame is a title line and the
   * control itself with nothing in reserve, so the icon lands on the slider
   * track or the select's chevron — and it is the one component type whose
   * active filter is already legible, because the value is displayed in the
   * control. The panel's summary list, the group headers and "Reset all" all
   * carry a persistent clear for it too. So here the icon reverts to
   * hover-only, like every other action; it still turns filled-orange when
   * revealed, so the state it signalled is not lost.
   */
  const persistentReset =
    sourceFilterActive && Boolean(onResetFilter) && componentType !== 'interactive';

  const renderAction = (action: ChromeAction) => {
    switch (action) {
      case 'inspect':
        if (!inspector) return null;
        return (
          <InspectButton
            key="inspect"
            componentId={metadata.index}
            active={inspector.selectedId === metadata.index}
            onInspect={inspector.select}
          />
        );
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
        return (
          <ResetButton
            key="reset"
            onResetFilter={onResetFilter}
            active={sourceFilterActive}
          />
        );
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
      <Group
        gap={compact ? 2 : 4}
        className={
          'depictio-component-actions' +
          (orientationFor(componentType) === 'vertical' ? ' depictio-actions-vertical' : '') +
          (persistentReset ? ' has-active-reset' : '') +
          (compact ? ' is-compact' : '')
        }
        wrap="nowrap"
      >
        {/* Static-bundle liveness badge. Vertical-orientation components
         * (figure/map/multiqc/advanced_viz) render it as the FIRST cell of
         * this action column so it hugs the empty top-right corner and the
         * hover-revealed icons flow below it instead of on top of it.
         * Horizontal components get it bottom-right instead (see below the
         * Group): their titles run along the top edge, so any top corner
         * placement collides on narrow components (e.g. interactive filters).
         * Renders nothing outside the static runtime (no StaticBadgeProvider
         * mounted) or for live components; always visible inside a bundle
         * (exempt from the row's hover-only opacity — see chrome.css). */}
        {orientationFor(componentType) === 'vertical' && (
          <StaticTierBadge componentIndex={metadata?.index} />
        )}
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
        {actions.map((a) => {
          // Render first and skip actions that produce nothing (e.g. `reset`
          // with no `onResetFilter`). Emitting an empty wrapper span would
          // leave a `gap`-sized hole in the row, so any following icon (the
          // Load-All toggle) looks detached / misaligned from the rest.
          const node = renderAction(a);
          if (!node) return null;
          const isActiveReset = a === 'reset' && persistentReset;
          return (
            <span
              key={a}
              className={'dgl-no-drag' + (isActiveReset ? ' depictio-active-reset' : '')}
              style={{ display: 'inline-flex', alignItems: 'center' }}
              onMouseDown={(e) => e.stopPropagation()}
              onTouchStart={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
            >
              {node}
            </span>
          );
        })}
        {/* Per-child wrap so each extra action becomes its own flex item in
         *  the chrome row (= one cell in the vertical column for figure /
         *  map / multiqc / advanced_viz). Wrapping all extras in a single
         *  span would force them to share one slot and break the vertical
         *  orientation. */}
        {extraActions
          ? React.Children.toArray(
              // Flatten fragments so <>{a}{b}</> contributes two children.
              ((): React.ReactNode[] => {
                const collected: React.ReactNode[] = [];
                const walk = (node: React.ReactNode) => {
                  if (node == null || node === false) return;
                  if (Array.isArray(node)) {
                    node.forEach(walk);
                    return;
                  }
                  if (React.isValidElement(node) && node.type === React.Fragment) {
                    React.Children.forEach((node.props as any).children, walk);
                    return;
                  }
                  collected.push(node);
                };
                walk(extraActions);
                return collected;
              })(),
            ).map((child, i) => (
              <span
                key={`extra-${i}`}
                className="dgl-no-drag"
                style={{ display: 'inline-flex', alignItems: 'center' }}
                onMouseDown={(e) => e.stopPropagation()}
                onTouchStart={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
              >
                {child}
              </span>
            ))
          : null}
      </Group>
      {/* Horizontal-orientation static-bundle badge — pinned to the empty
       * bottom-right corner (titles/values sit along the top edge on these
       * components, so the top corners are contested; the bottom-right is
       * padding). Same z-index as the action row so it clears Plotly-style
       * embedded chrome. StaticTierBadge renders null outside static bundles,
       * leaving only a zero-size inert span here in server builds. */}
      {orientationFor(componentType) !== 'vertical' && (
        <span
          style={{
            position: 'absolute',
            bottom: 8,
            right: 8,
            zIndex: 1100,
            display: 'inline-flex',
            pointerEvents: 'none',
          }}
        >
          <StaticTierBadge componentIndex={metadata?.index} />
        </span>
      )}
      {children}
    </div>
  );
};

export default ComponentChrome;
