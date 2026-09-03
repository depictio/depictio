import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { ActionIcon, Group, LoadingOverlay, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import CatalogButton from './CatalogButton';
import MetadataPopover from './MetadataPopover';
import FullscreenButton from './FullscreenButton';
import InspectButton from './InspectButton';
import { useInspectorControl } from './InspectorContext';
import DownloadButton from './DownloadButton';
import ResetButton from './ResetButton';
import SaveGroupAction, { SaveGroupContext, SelectionHintAction } from './SaveGroupAction';
import { supportsSelectionGrouping } from '../../selection';
import { useGroupingColorVar } from '../../selectionGroups';
import './chrome.css';

/**
 * Lets a host mark up the tiles of an AI draft from outside the chrome,
 * without threading a prop through the grid, the renderer dispatch and
 * `wrapWithChrome`'s ten call sites — the same reasoning (and the same
 * shape) as `InspectorContext` next door.
 *
 * Only marks: the decisions themselves are taken in the draft banner's
 * review bar, so a tile never grows a control of its own. Mounted only by
 * the editor, and only on a dashboard the AI generated and nobody has
 * reviewed yet. A null context — the default — is the off state: the chrome
 * paints no outline, which is every other host and every promoted dashboard.
 */
export interface DraftReviewControl {
  /** Tile still awaiting a Keep / Remove decision — painted with a subtle
   *  outline so what is left to review is legible at a glance. */
  isUnreviewed?: (metadata: StoredMetadata) => boolean;
  /** Tile whose regeneration is streaming: the chrome scrims it, so the
   *  stale render is visibly not the answer yet. */
  isBusy?: (metadata: StoredMetadata) => boolean;
  /** The one tile the review bar is currently talking about. Outlined
   *  harder than the rest, so "3 / 12" has an answer on the canvas. */
  isCurrent?: (metadata: StoredMetadata) => boolean;
}

export const DraftReviewContext = createContext<DraftReviewControl | null>(null);

/** `value={null}` is the disabled state, so a host can mount this
 *  unconditionally and decide per dashboard. */
export const DraftReviewProvider: React.FC<{
  value: DraftReviewControl | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <DraftReviewContext.Provider value={value}>{children}</DraftReviewContext.Provider>
);

export function useDraftReview(): DraftReviewControl | null {
  return useContext(DraftReviewContext);
}

export type ChromeAction =
  | 'inspect'
  | 'catalog'
  | 'ai'
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
  /** Tile of a draft that has not been reviewed yet: paints a subtle dashed
   *  outline (see `unreviewedOutline`). Falls back to the context. */
  unreviewed?: boolean;
  /** A regeneration for this tile is in flight: scrims the rendered
   *  component. Falls back to the context. */
  draftBusy?: boolean;
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
  unreviewed,
  draftBusy,
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
  // AI provenance sits next to catalog provenance: both say where the
  // component's config came from, neither depends on the component type.
  const aiPrompt =
    typeof metadata.ai_source?.prompt === 'string' ? metadata.ai_source.prompt.trim() : '';
  const aiLabel = aiPrompt ? `Authored with AI: "${aiPrompt}"` : 'Authored with AI';
  if (metadata.ai_source) actions.push('ai');
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

  // Draft review. The prop wins where a host can pass one; otherwise the
  // provider answers per component, and with neither this is all inert.
  const draftReview = useDraftReview();
  const isUnreviewed = unreviewed ?? draftReview?.isUnreviewed?.(metadata) ?? false;
  const isRegenerating = draftBusy ?? draftReview?.isBusy?.(metadata) ?? false;
  const isCurrentReview = draftReview?.isCurrent?.(metadata) ?? false;
  // Outline rather than border: the renderers already draw their own Paper,
  // and an outline is painted outside the box model, so a tile sized to the
  // pixel by the grid does not move. Dashed and inset for the same reason the
  // selection-capable marker is (see chrome.css). Cyan repeats
  // depictio-react-ai's AI_COLOR, which this package cannot import — react-ai
  // depends on react-core, not the reverse.
  const unreviewedOutline: React.CSSProperties = {
    // A hairline, and one shade lighter than the selection marker's: on a
    // fresh draft EVERY tile carries this, so it has to read as "not looked
    // at yet" across a whole dashboard without shouting on any one tile.
    outline: '1px dashed var(--mantine-color-cyan-3)',
    outlineOffset: '-1px',
    borderRadius: 'var(--mantine-radius-md)',
  };
  // The tile the review bar names. Solid and twice as thick, because exactly
  // one tile carries it at a time and it has to be findable on a canvas where
  // every other generated tile is already dashed.
  const currentReviewOutline: React.CSSProperties = {
    outline: '2px solid var(--mantine-color-cyan-6)',
    outlineOffset: '-2px',
    borderRadius: 'var(--mantine-radius-md)',
  };

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
      case 'ai':
        if (!metadata.ai_source) return null;
        return (
          // A badge, not a button: nothing to open, so like `description` the
          // tooltip is the whole payload and hover, focus and touch all reveal
          // it. The label doubles as the aria-label because Mantine's Tooltip
          // wires no aria-describedby. The icon id is a literal on purpose:
          // the icon-subset scanner reads string literals, not imports. The
          // colour repeats depictio-react-ai's AI_COLOR, which this package
          // cannot import (react-ai depends on react-core, not the reverse).
          <Tooltip
            key="ai"
            label={aiLabel}
            withArrow
            multiline
            w={260}
            openDelay={200}
            position="bottom-end"
            events={{ hover: true, focus: true, touch: true }}
          >
            <ActionIcon variant="subtle" color="cyan" size="sm" aria-label={aiLabel}>
              <Icon icon="material-symbols:auto-awesome-outline" width={16} height={16} />
            </ActionIcon>
          </Tooltip>
        );
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
      // subtree — so a class on the inner button could never win. Same reason
      // `depictio-active-reset` is set on the wrapper below.
      className={'dgl-no-drag' + extraClass}
      style={{ display: 'inline-flex', alignItems: 'center' }}
      onMouseDown={(e) => e.stopPropagation()}
      onTouchStart={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {child}
    </span>
  );

  return (
    <div
      ref={fullscreenRef as React.RefObject<HTMLDivElement>}
      className={
        'depictio-component-chrome' +
        (isFullscreenActive ? ' fullscreen-active' : '') +
        (selectionCapable ? ' depictio-selection-capable' : '')
      }
      style={{
        ...(selectionCapable
          ? ({ '--depictio-grouping-color': groupingColorVar } as React.CSSProperties)
          : {}),
        ...(isCurrentReview
          ? currentReviewOutline
          : isUnreviewed
            ? unreviewedOutline
            : {}),
      }}
    >
      <Group
        gap={compact ? 2 : 4}
        className={
          'depictio-component-actions' +
          (orientationFor(componentType) === 'vertical' ? ' depictio-actions-vertical' : '') +
          // Cards only: the top-right corner is where a card draws its value's
          // icon, so the row moves to the quiet bottom edge. Still horizontal.
          (componentType === 'card' ? ' depictio-actions-bottom' : '') +
          // Any icon that stays on screen without hover needs the backdrop to
          // stay with it: the active-reset icon and the analysis marker.
          (persistentReset || selectionCapable ? ' has-persistent-action' : '') +
          (compact ? ' is-compact' : '')
        }
        wrap="nowrap"
      >
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
        {otherActions.map((child, i) => wrapAction(child, `extra-${i}`))}
      </Group>
      {/* The tile is being rewritten server-side: what is on screen is the
       *  previous answer, so it is scrimmed rather than left to look current.
       *  Sits under the action row's z-index so the chrome stays reachable. */}
      <LoadingOverlay
        visible={isRegenerating}
        zIndex={1050}
        overlayProps={{ blur: 1 }}
        loaderProps={{ size: 'sm', color: 'cyan' }}
      />
      {children}
    </div>
  );
};

export default ComponentChrome;
