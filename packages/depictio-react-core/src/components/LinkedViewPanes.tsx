import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import { ActionIcon, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { LINKED_VIEW_MIN_PANE_PX } from './sectionGroups';
import {
  LINKED_VIEW_GUTTER_PX,
  autofitTree,
  axisOf,
  floorDeficit,
  floorTree,
  gutterRange,
  moveGutterTree,
  moveGutterWithin,
  nodeAt,
  parseStoredSplit,
  pathKey,
  resetGutter,
  sameFractions,
  sameSizes,
  serializeStoredSplit,
  snapTree,
  splitSignature,
  treeFractions,
  treeRects,
  withFractions,
} from './linkedViewSplit';
import type {
  FloorOf,
  SplitFractions,
  SplitNode,
  SplitTree,
  SplitUnit,
} from './linkedViewSplit';
import './linkedViewPanes.css';

export { LINKED_VIEW_GUTTER_PX };

/**
 * How the gutters behave.
 * - `edit`: a drag snaps to grid units and is handed to `onCommit`, which writes
 *   it into the dashboard like a resize of the grid would.
 * - `view`: a drag is the reader's own, fractional and kept in this browser
 *   (`storageKey`); the dashboard is never written. Double-click puts a gutter
 *   back where the dashboard has it.
 * - `static`: no handles, only the gap.
 */
export type LinkedViewPanesMode = 'edit' | 'view' | 'static';

/** What the panes and the header's controls both read: the linked view's split,
 *  where it stands and where its sizes are kept. */
export interface LinkedViewSplitInput {
  /** The linked view's split tree, from its stored layout (`buildSplitTree`). */
  tree: SplitTree;
  /** Height of the whole linked view, px: its rows at the fitted row height. */
  height: number;
  /** The least each tile keeps by default, px, by layout key. A tile not listed
   *  keeps `LINKED_VIEW_MIN_PANE_PX`; 0 leaves a tile (a card, a text) as short
   *  as its stored size makes it. */
  floors?: Readonly<Record<string, number>>;
  mode: LinkedViewPanesMode;
  /** `view`: where the reader's gutter positions are kept. */
  storageKey?: string;
}

export interface LinkedViewPanesProps extends LinkedViewSplitInput {
  /** The grid cell of every tile, by the layout key the tree holds. */
  cells: ReadonlyMap<string, React.ReactElement>;
  /** One grid column and one stored row in the unit the tree is counted in:
   *  the least a tile keeps, and a keyboard step. */
  unit: SplitUnit;
  /** `edit`: the tree after a gutter move, to be written to the dashboard. */
  onCommit?: (tree: SplitTree) => void;
}

// ---- The reader's gutter positions, kept in this browser ---------------------
//
// One store for the panes and for the header's Reset: both read it, and either
// may write it. A value that storage refuses (blocked, full) is held in memory
// for as long as the page lives.

const memory = new Map<string, string>();
const listeners = new Set<() => void>();

function readRaw(key: string | undefined): string | null {
  if (!key) return null;
  try {
    return window.localStorage.getItem(key) ?? memory.get(key) ?? null;
  } catch {
    return memory.get(key) ?? null;
  }
}

/** Keep `fractions` as the reader's positions for `key`, or forget them (null).
 *  Every panes and controls component reading the key follows. */
export function storeSplit(
  key: string | undefined,
  signature: string,
  fractions: SplitFractions | null,
): void {
  if (!key) return;
  const raw = fractions ? serializeStoredSplit(signature, fractions) : null;
  try {
    if (raw) window.localStorage.setItem(key, raw);
    else window.localStorage.removeItem(key);
    memory.delete(key);
  } catch {
    // Storage blocked or full: the positions last for as long as the page does.
    if (raw) memory.set(key, raw);
    else memory.delete(key);
  }
  listeners.forEach((listener) => listener());
}

function subscribeSplits(listener: () => void): () => void {
  listeners.add(listener);
  // Another tab of the same dashboard moved a gutter.
  window.addEventListener('storage', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', listener);
  };
}

/** The positions kept for `key`, for the structure `signature` names. */
function useStoredSplit(key: string | undefined, signature: string): SplitFractions | null {
  const raw = useSyncExternalStore(
    subscribeSplits,
    () => readRaw(key),
    () => null,
  );
  return useMemo(() => parseStoredSplit(raw, signature), [raw, signature]);
}

/**
 * The split as it is drawn. `base` is the dashboard's own, its stacks bent to
 * the tiles' floors at this height; `current` adds a reader's own positions
 * (`view`). `stable` is `tree` held still across renders that rebuild it.
 */
export function useLinkedViewSplit({ tree, height, floors, mode, storageKey }: LinkedViewSplitInput) {
  // The parent rebuilds the tree on every render; panes and storage care about
  // its content.
  const treeKey = JSON.stringify(tree);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stable = useMemo(() => tree, [treeKey]);
  const signature = useMemo(() => splitSignature(stable), [stable]);
  const floorsKey = JSON.stringify(floors ?? null);
  const floorOf = useMemo<FloorOf>(
    () => (key) => floors?.[key] ?? LINKED_VIEW_MIN_PANE_PX,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [floorsKey],
  );
  const base = useMemo(() => floorTree(stable, height, floorOf), [stable, height, floorOf]);
  const stored = useStoredSplit(mode === 'view' ? storageKey : undefined, signature);
  const current = useMemo(
    () => (mode === 'view' ? withFractions(base, stored) : base),
    [base, stored, mode],
  );
  return { stable, signature, base, current, stored, floorOf };
}

interface CommitTarget {
  mode: LinkedViewPanesMode;
  base: SplitTree;
  signature: string;
  storageKey?: string;
  onCommit?: (tree: SplitTree) => void;
}

/** Make `next` the linked view's layout: written to the dashboard in whole units
 *  in the editor, kept in this browser for a reader. */
function commitSplit(next: SplitTree, to: CommitTarget): void {
  if (to.mode === 'edit') {
    to.onCommit?.(snapTree(next));
  } else if (to.mode === 'view') {
    const fractions = treeFractions(next);
    const value = sameFractions(fractions, treeFractions(to.base)) ? null : fractions;
    storeSplit(to.storageKey, to.signature, value);
  }
}

interface Drag {
  pointerId: number;
  path: number[];
  gutter: number;
  start: number;
  pxPerUnit: number;
  from: SplitTree;
  latest: SplitTree;
  applied: number;
}

/**
 * A linked view drawn as nested panes with a draggable gutter between neighbours,
 * instead of react-grid-layout: dragging one moves a shared edge and every tile
 * against it follows, so a tile that sits at the wrong height is fixed once for
 * the whole stack. Tiles keep the cell the grid builds for them (chrome, hover
 * actions, `data-component-id`); only how they are placed differs.
 *
 * The cell is a `.react-grid-item` here too, and the container a
 * `.react-grid-layout`: the screenshot service waits for the former, and tiles
 * measure their share of the latter. react-grid-layout positions its items with
 * inline styles, so neither class brings positioning along.
 *
 * A drag re-renders the panes (a few divs: the tiles' own elements are the
 * grid's, unchanged) and asks the tiles to re-measure with a window `resize`,
 * throttled to a frame: Plotly, AG Grid, 3Dmol and the canvases listen for that
 * and not for their box.
 */
const LinkedViewPanes: React.FC<LinkedViewPanesProps> = ({
  tree,
  cells,
  height,
  floors,
  unit,
  mode,
  onCommit,
  storageKey,
}) => {
  const { base, current, signature, floorOf } = useLinkedViewSplit({
    tree,
    height,
    floors,
    mode,
    storageKey,
  });

  // The tree being dragged, while a drag is on.
  const [live, setLive] = useState<SplitTree | null>(null);
  const shown = live ?? current;
  const [active, setActive] = useState<string | null>(null);

  const interactive = mode !== 'static';
  const drag = useRef<Drag | null>(null);

  // One window `resize` per frame, whichever of the drag, the keyboard or a
  // saved layout moved the panes.
  const frame = useRef<number | null>(null);
  const nudgeResize = useCallback(() => {
    if (frame.current != null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      window.dispatchEvent(new Event('resize'));
    });
  }, []);
  const sizesKey = JSON.stringify([height, shown.root]);
  const firstSizes = useRef(true);
  useEffect(() => {
    if (firstSizes.current) {
      firstSizes.current = false;
      return;
    }
    nudgeResize();
  }, [sizesKey, nudgeResize]);

  const releaseBody = useCallback(() => {
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  }, []);
  useEffect(
    () => () => {
      if (frame.current != null) cancelAnimationFrame(frame.current);
      if (drag.current) releaseBody();
    },
    [releaseBody],
  );

  // What the handlers need from the latest render, without re-binding them.
  const latest = useRef({ shown, base, mode, unit, onCommit, storageKey, signature, height, floorOf });
  latest.current = { shown, base, mode, unit, onCommit, storageKey, signature, height, floorOf };

  const commit = useCallback((next: SplitTree) => commitSplit(next, latest.current), []);

  /** `delta` units of a gutter of `from`. The editor writes whole units and
   *  keeps every tile on its floor, so there a move stops where a tile would go
   *  under; a reader's is free down to one unit. */
  const moveBy = (from: SplitTree, path: number[], gutter: number, delta: number) => {
    const now = latest.current;
    if (now.mode !== 'edit') return moveGutterTree(from, path, gutter, delta, now.unit);
    const was = floorDeficit(from, now.height, now.floorOf);
    return moveGutterWithin(
      from,
      path,
      gutter,
      Math.round(delta),
      now.unit,
      (next) => floorDeficit(next, now.height, now.floorOf) <= was + 1e-6,
    );
  };

  const begin = (event: React.PointerEvent<HTMLDivElement>, path: number[], gutter: number) => {
    if (!interactive || event.button !== 0) return;
    const el = event.currentTarget;
    const before = el.previousElementSibling as HTMLElement | null;
    const after = el.nextElementSibling as HTMLElement | null;
    const node = nodeAt(shown.root, path);
    if (!before || !after || !node || node.kind !== 'split') return;
    const axis = axisOf(node.dir);
    const extent = (pane: HTMLElement) =>
      axis === 'x' ? pane.getBoundingClientRect().width : pane.getBoundingClientRect().height;
    const pxPerUnit = (extent(before) + extent(after)) / (node.sizes[gutter] + node.sizes[gutter + 1]);
    if (!(pxPerUnit > 0)) return;
    event.preventDefault();
    el.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      path,
      gutter,
      start: axis === 'x' ? event.clientX : event.clientY,
      pxPerUnit,
      from: shown,
      latest: shown,
      applied: 0,
    };
    setActive(`${pathKey(path)}#${gutter}`);
    // Keep the resize cursor off the handle and stop the drag selecting text.
    document.body.style.userSelect = 'none';
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
  };

  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.pointerId !== event.pointerId) return;
    const node = nodeAt(d.from.root, d.path);
    if (!node || node.kind !== 'split') return;
    const at = axisOf(node.dir) === 'x' ? event.clientX : event.clientY;
    // The editor stores whole units, so the handle snaps to them as it goes: what
    // is seen is what will be saved.
    const moved = moveBy(d.from, d.path, d.gutter, (at - d.start) / d.pxPerUnit);
    if (moved.delta === d.applied) return;
    d.applied = moved.delta;
    d.latest = moved.tree;
    setLive(moved.tree);
  };

  const end = (event: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.pointerId !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    releaseBody();
    setActive(null);
    // A click that moved nothing is no edit: it must not reach the dashboard.
    if (event.type !== 'pointercancel' && d.applied !== 0) commit(d.latest);
    setLive(null);
    nudgeResize();
  };

  const reset = (path: number[], gutter: number) => {
    if (latest.current.mode !== 'view') return;
    const back = resetGutter(latest.current.shown, latest.current.base, path, gutter, latest.current.unit);
    if (back.delta !== 0) commit(back.tree);
  };

  const nudge = (event: React.KeyboardEvent<HTMLDivElement>, path: number[], gutter: number) => {
    if (!interactive) return;
    const node = nodeAt(shown.root, path);
    if (!node || node.kind !== 'split') return;
    if (event.key === 'Home') {
      event.preventDefault();
      reset(path, gutter);
      return;
    }
    const keys = node.dir === 'row' ? ['ArrowLeft', 'ArrowRight'] : ['ArrowUp', 'ArrowDown'];
    const k = keys.indexOf(event.key);
    if (k < 0) return;
    event.preventDefault();
    const step = unit[axisOf(node.dir)] * (event.shiftKey ? 2 : 1);
    const moved = moveBy(shown, path, gutter, k === 0 ? -step : step);
    if (moved.delta !== 0) commit(moved.tree);
  };

  const renderNode = (node: SplitNode, path: number[], grow: number): React.ReactNode => {
    const pane: React.CSSProperties = { flex: `${grow} 1 0px`, minWidth: 0, minHeight: 0 };
    if (node.kind === 'leaf') {
      const cell = cells.get(node.key);
      if (!cell) return <div key={`tile-${node.key}`} className="depictio-linked-view-pane" style={pane} />;
      const props = cell.props as { className?: string; style?: React.CSSProperties };
      return React.cloneElement(cell as React.ReactElement<Record<string, unknown>>, {
        key: `tile-${node.key}`,
        className: ['react-grid-item', 'depictio-linked-view-pane', props.className]
          .filter(Boolean)
          .join(' '),
        // The cell is built to fill a grid box (`height: 100%`); here it is a
        // flex item of its pane.
        style: { ...props.style, ...pane, height: 'auto' },
      });
    }
    const total = node.sizes.reduce((a, b) => a + b, 0);
    return (
      <div
        key={`split-${pathKey(path)}`}
        className="depictio-linked-view-node"
        data-dir={node.dir}
        style={{ ...pane, display: 'flex', flexDirection: node.dir }}
      >
        {node.children.map((child, i) => {
          const body = renderNode(child, [...path, i], node.sizes[i]);
          if (i === 0) return body;
          const gutter = i - 1;
          const where = node.sizes.slice(0, i).reduce((a, b) => a + b, 0);
          const room = gutterRange(shown, path, gutter, unit);
          const percent = (v: number) => Math.round((100 * v) / total);
          const id = `${pathKey(path)}#${gutter}`;
          return (
            <React.Fragment key={`gutter-${i}`}>
              <div
                className="depictio-linked-view-gutter"
                data-testid="linked-view-gutter"
                data-dir={node.dir}
                data-active={active === id ? '' : undefined}
                data-static={interactive ? undefined : ''}
                role={interactive ? 'separator' : undefined}
                aria-hidden={interactive ? undefined : true}
                aria-orientation={node.dir === 'row' ? 'vertical' : 'horizontal'}
                aria-label={interactive ? 'Resize the tiles on either side' : undefined}
                aria-valuemin={interactive ? percent(where + room.min) : undefined}
                aria-valuemax={interactive ? percent(where + room.max) : undefined}
                aria-valuenow={interactive ? percent(where) : undefined}
                tabIndex={interactive ? 0 : undefined}
                title={
                  !interactive
                    ? undefined
                    : mode === 'view'
                      ? 'Drag to resize, double-click to reset'
                      : 'Drag to resize'
                }
                style={{ flex: `0 0 ${LINKED_VIEW_GUTTER_PX}px` }}
                onPointerDown={interactive ? (e) => begin(e, path, gutter) : undefined}
                onPointerMove={interactive ? move : undefined}
                onPointerUp={interactive ? end : undefined}
                onPointerCancel={interactive ? end : undefined}
                onDoubleClick={interactive ? () => reset(path, gutter) : undefined}
                onKeyDown={interactive ? (e) => nudge(e, path, gutter) : undefined}
              />
              {body}
            </React.Fragment>
          );
        })}
      </div>
    );
  };

  return (
    <div
      className={
        'depictio-linked-view-split react-grid-layout' +
        (live ? ' depictio-linked-view-split--dragging' : '')
      }
      data-testid="linked-view-split"
      data-mode={mode}
      style={{ height, width: '100%' }}
    >
      {renderNode(shown.root, [], 1)}
    </div>
  );
};

export interface LinkedViewControlsProps extends LinkedViewSplitInput {
  /** `edit`: the layout the section had when the dashboard was opened, which
   *  Reset writes back. */
  baseline?: SplitTree | null;
  /** The height each tile's content asks for, px, by layout key: what the
   *  renderers publish (`autofit.ts`). */
  demands?: Readonly<Record<string, number>>;
  /** `edit`: the tree after a reset or an autofit, to be written to the dashboard. */
  onCommit?: (tree: SplitTree) => void;
}

/**
 * The two actions of a linked view's header, beside the section's other controls:
 * Reset puts the split back to the dashboard's default, Autofit sizes each stack
 * from what its tiles ask for.
 *
 * Both act the way a drag does. A reader's result is theirs, kept in this
 * browser (Reset forgets it); the editor's goes through the layout save path
 * (Reset writes back `baseline`, the layout the section was opened with). Each
 * is greyed out, not hidden, while it would change nothing, so the header does
 * not shift as tiles load.
 */
export const LinkedViewControls: React.FC<LinkedViewControlsProps> = ({
  baseline,
  demands,
  onCommit,
  ...input
}) => {
  const { mode, storageKey } = input;
  const { stable, signature, base, current, stored, floorOf } = useLinkedViewSplit(input);
  const edit = mode === 'edit';

  const asked = useMemo(
    () => [...treeRects(current).keys()].some((key) => (demands?.[key] ?? 0) > 0),
    [current, demands],
  );
  const fitted = useMemo(
    () => autofitTree(current, input.height, (key) => demands?.[key], floorOf),
    [current, input.height, demands, floorOf],
  );
  const target = useMemo(() => (edit ? snapTree(fitted) : fitted), [edit, fitted]);

  const canFit =
    mode !== 'static' &&
    asked &&
    (edit
      ? !sameSizes(target, snapTree(current))
      : !sameFractions(treeFractions(target), treeFractions(current), 0.002));
  const canReset =
    mode === 'view' ? stored !== null : edit && !!baseline && !sameSizes(stable, baseline);
  if (mode === 'static') return null;

  const to: CommitTarget = { mode, base, signature, storageKey, onCommit };
  const reset = () => {
    if (!canReset) return;
    if (mode === 'view') storeSplit(storageKey, signature, null);
    else if (baseline) onCommit?.(baseline);
  };
  const fit = () => {
    if (canFit) commitSplit(fitted, to);
  };

  const resetTip = canReset
    ? edit
      ? 'Restore the sizes this section had when the dashboard was opened'
      : "Reset the tile sizes to the dashboard's default"
    : 'The tiles are at their default sizes';
  const fitTip = canFit
    ? 'Fit each stack of tiles to what its content needs'
    : asked
      ? 'The tiles already fit their content'
      : 'No tile has reported the height its content needs yet';

  const button = (
    label: string,
    tip: string,
    icon: string,
    enabled: boolean,
    onClick: () => void,
    testId: string,
  ) => (
    <Tooltip label={tip} withArrow multiline w={240} openDelay={300}>
      {/* `data-disabled` and not `disabled`: a disabled button takes no hover,
          and the tooltip is what says why it is greyed out. */}
      <ActionIcon
        size="sm"
        variant="subtle"
        color="gray"
        aria-label={label}
        aria-disabled={!enabled}
        data-disabled={!enabled || undefined}
        data-testid={testId}
        onClick={(event) => {
          event.stopPropagation();
          if (enabled) onClick();
        }}
      >
        <Icon icon={icon} width={16} />
      </ActionIcon>
    </Tooltip>
  );

  return (
    <Group gap={2} wrap="nowrap" data-testid="linked-view-controls">
      {button('Fit tiles to their content', fitTip, 'mdi:arrow-expand-vertical', canFit, fit, 'linked-view-autofit')}
      {button('Reset tile sizes', resetTip, 'mdi:restore', canReset, reset, 'linked-view-reset')}
    </Group>
  );
};

export default LinkedViewPanes;
