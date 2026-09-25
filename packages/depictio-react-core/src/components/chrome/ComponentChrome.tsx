import React, { useContext, useEffect, useRef, useState } from 'react';
import { ActionIcon, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import CatalogButton from './CatalogButton';
import MetadataPopover from './MetadataPopover';
import FullscreenButton from './FullscreenButton';
import InspectButton from './InspectButton';
import { useInspectorControl } from './InspectorContext';
import DownloadButton from './DownloadButton';
import ResetButton from './ResetButton';
import ClearSelectionButton from './ClearSelectionButton';
import SaveGroupAction, { SaveGroupContext, SelectionHintAction } from './SaveGroupAction';
import { supportsSelectionGrouping } from '../../selection';
import { useGroupingColorVar } from '../../selectionGroups';
import './chrome.css';

export type ChromeAction =
  | 'inspect'
  | 'catalog'
  | 'description'
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
   *  (e.g. a scatter selection, a table row selection, a map polygon). A
   *  selection source then shows its clear action even without hover (see
   *  `showClear` below); an interactive control's in-row reset switches to a
   *  filled-orange style instead. */
  sourceFilterActive?: boolean;
  /** Values the tile's own selection holds, for the clear action's
   *  "Clear selection (N)" label. Omitted or 0 leaves the count out. */
  selectionCount?: number;
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
  selectionCount,
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
  // Same reasoning as `inspect`: whether this action exists is a property of
  // the component's provenance, not of its type.
  if (metadata.catalog_source) actions.push('catalog');
  /**
   * The author's own prose about this component, from `description` in the
   * dashboard YAML. Every renderer but advanced_viz drops it on the floor, so
   * a card explaining that it exists to demonstrate `filter_expr` said that to
   * nobody. Surfacing it here rather than in each renderer keeps it out of the
   * tile's own layout: a card has room for a title and a number, an interactive
   * for a label and its control, and neither can grow a paragraph.
   *
   * advanced_viz is excluded because its renderers already print the same text
   * as a subtitle under the title, so the icon would only offer a second copy.
   */
  const description = typeof metadata.description === 'string' ? metadata.description.trim() : '';
  const hasDescription = Boolean(description) && componentType !== 'advanced_viz';
  // Sits directly before `metadata` (always first in `actionsFor`): both answer
  // "what is this component", the prose one before the structured one.
  if (hasDescription) actions.push('description');
  actions.push(...actionsFor(componentType));

  /**
   * Whether the tile draws its clear-selection action.
   *
   * A figure, table, map, image or advanced viz selection is easy to miss, and
   * nothing else on screen says the tile is filtering the dashboard, so the
   * way out stays visible while the selection lasts. It is a slot of the action
   * row, but the one slot that escapes the hover-only default: at rest it shows
   * alone, with no row frame and the other icons hidden, and on hover the whole
   * row appears around it. It sits in the slot nearest the tile corner (first
   * in a vertical row, last in a horizontal one), so the lone icon at rest
   * stays in the corner rather than floating beside empty slots.
   *
   * An interactive control is excluded. Its frame is a title line and the
   * control itself, so a corner icon lands on the slider track or the select's
   * chevron, and its active filter is already legible in the control. It keeps
   * the in-row reset, hover-only, which turns filled-orange when revealed.
   */
  const showClear =
    sourceFilterActive && Boolean(onResetFilter) && componentType !== 'interactive';
  const vertical = orientationFor(componentType) === 'vertical';

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
      case 'catalog':
        if (!metadata.catalog_source) return null;
        return <CatalogButton key="catalog" source={metadata.catalog_source} />;
      case 'description':
        if (!hasDescription) return null;
        return (
          // Hover, focus and touch all open it: the icon has no click action of
          // its own, so a viewer who never hovers (keyboard, tablet) would
          // otherwise reach a button that does nothing. Mantine's Tooltip wires
          // no aria-describedby, so the text is repeated in the aria-label,
          // which is the only copy a screen reader ever reaches.
          <Tooltip
            key="description"
            label={description}
            withArrow
            multiline
            w={260}
            openDelay={200}
            position="bottom-end"
            events={{ hover: true, focus: true, touch: true }}
          >
            <ActionIcon
              variant="subtle"
              color="teal"
              size="sm"
              aria-label={`About this component: ${description}`}
            >
              <Icon icon="mdi:text-box-outline" width={16} height={16} />
            </ActionIcon>
          </Tooltip>
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
        // Skip reset entirely when the host didn't wire one up, and on every
        // selection source: their clear action is the standalone one drawn
        // slot of its own (see `showClear`), only while there is something to
        // clear.
        if (!onResetFilter || componentType !== 'interactive') return null;
        return (
          <ResetButton
            key="reset"
            onResetFilter={onResetFilter}
            active={sourceFilterActive}
          />
        );
    }
  };

  // Analysis mode marks the components a selection can be saved from. Derived
  // from the context rather than threaded as a prop because `wrapWithChrome`
  // has ten call sites and only four component types can ever match — and the
  // context being mounted at all is the same signal that this host is
  // interactive (see the chromeExtras comment in ComponentRenderer).
  const saveGroupApi = useContext(SaveGroupContext);
  const selectionCapable =
    Boolean(saveGroupApi?.analysisEngaged) &&
    supportsSelectionGrouping(metadata, Boolean(saveGroupApi));
  const groupingColorVar = useGroupingColorVar();

  // Flatten `extraActions` once, then split the grouping action off the front.
  // It leads the stack — above metadata and the rest — because it is the only
  // action that answers "what can I do with this component *right now*"; the
  // others are always-available utilities. Flattening fragments first is what
  // lets `<>{save}{extras}</>` from ComponentRenderer contribute separately.
  const extraChildren = React.useMemo(() => {
    const collected: React.ReactNode[] = [];
    const walk = (node: React.ReactNode) => {
      if (node == null || node === false) return;
      if (Array.isArray(node)) {
        node.forEach(walk);
        return;
      }
      if (React.isValidElement(node) && node.type === React.Fragment) {
        React.Children.forEach((node.props as { children?: React.ReactNode }).children, walk);
        return;
      }
      collected.push(node);
    };
    walk(extraActions);
    return React.Children.toArray(collected);
  }, [extraActions]);
  const isGroupingAction = (child: React.ReactNode) =>
    React.isValidElement(child) &&
    (child.type === SelectionHintAction || child.type === SaveGroupAction);
  const groupingActions = extraChildren.filter(isGroupingAction);
  const otherActions = extraChildren.filter((c) => !isGroupingAction(c));

  const wrapAction = (child: React.ReactNode, key: string, extraClass = '') => (
    <span
      key={key}
      // The escape from the hover-only default has to live on THIS span, not on
      // the action inside it: the rule that hides the row targets
      // `.depictio-component-actions > *`, and `opacity` applies to the whole
      // subtree, so a class on the inner button could never win.
      className={'dgl-no-drag' + extraClass}
      style={{ display: 'inline-flex', alignItems: 'center' }}
      onMouseDown={(e) => e.stopPropagation()}
      onTouchStart={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {child}
    </span>
  );
  // The clear-selection slot, placed by orientation in the row below: the end
  // nearest the tile corner, see `showClear`.
  const clearSlot =
    showClear && onResetFilter
      ? wrapAction(
          <ClearSelectionButton onClear={onResetFilter} count={selectionCount} />,
          'clear-selection',
          ' depictio-clear-selection',
        )
      : null;

  return (
    <div
      ref={fullscreenRef as React.RefObject<HTMLDivElement>}
      className={
        'depictio-component-chrome' +
        (isFullscreenActive ? ' fullscreen-active' : '') +
        (selectionCapable ? ' depictio-selection-capable' : '')
      }
      style={
        selectionCapable
          ? ({ '--depictio-grouping-color': groupingColorVar } as React.CSSProperties)
          : undefined
      }
    >
      <Group
        gap={compact ? 2 : 4}
        className={
          'depictio-component-actions' +
          (vertical ? ' depictio-actions-vertical' : '') +
          // Cards only: the top-right corner is where a card draws its value's
          // icon, so the row moves to the quiet bottom edge. Still horizontal.
          (componentType === 'card' ? ' depictio-actions-bottom' : '') +
          // No backdrop pinned on without hover: the two slots that stay
          // visible (the analysis marker, the clear-selection action) carry
          // their own `light` tint, and a pinned backdrop framed the row's
          // empty slots around them.
          (compact ? ' is-compact' : '')
        }
        wrap="nowrap"
      >
        {vertical && clearSlot}
        {/* Grouping action first (after the grip, which stays where authors
         * expect it): the analysis marker / save-as-group action belongs above
         * metadata, not buried at the end of the utility icons. */}
        {groupingActions.map((child, i) =>
          wrapAction(
            child,
            `grouping-${i}`,
            child != null && React.isValidElement(child) && child.type === SelectionHintAction
              ? ' depictio-selection-hint'
              : '',
          ),
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
              variant="subtle"
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
          return (
            <span
              key={a}
              className="dgl-no-drag"
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
        {otherActions.map((child, i) => wrapAction(child, `extra-${i}`))}
        {!vertical && clearSlot}
      </Group>
      {children}
    </div>
  );
};

export default ComponentChrome;
