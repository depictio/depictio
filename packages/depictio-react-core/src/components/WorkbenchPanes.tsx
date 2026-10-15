import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  axisOf,
  gutterRange,
  moveGutterTree,
  nodeAt,
  parseStoredSplit,
  pathKey,
  resetGutter,
  sameFractions,
  serializeStoredSplit,
  splitSignature,
  treeFractions,
  withFractions,
} from './workbenchSplit';
import type { SplitFractions, SplitNode, SplitTree, SplitUnit } from './workbenchSplit';
import './workbenchPanes.css';

/** Thickness of a gutter, in px. Also the gap between two neighbouring tiles. */
export const WORKBENCH_GUTTER_PX = 8;

/**
 * How the gutters behave.
 * - `edit`: a drag snaps to grid units and is handed to `onCommit`, which writes
 *   it into the dashboard like a resize of the grid would.
 * - `view`: a drag is the reader's own, fractional and kept in this browser
 *   (`storageKey`); the dashboard is never written. Double-click puts a gutter
 *   back where the dashboard has it.
 * - `static`: no handles, only the gap.
 */
export type WorkbenchPanesMode = 'edit' | 'view' | 'static';

export interface WorkbenchPanesProps {
  /** The workbench's split tree, from its stored layout (`buildSplitTree`). */
  tree: SplitTree;
  /** The grid cell of every tile, by the layout key the tree holds. */
  cells: ReadonlyMap<string, React.ReactElement>;
  /** Height of the whole workbench, px: its rows at the fitted row height. */
  height: number;
  /** One grid column and one stored row in the unit the tree is counted in:
   *  the least a tile keeps, and a keyboard step. */
  unit: SplitUnit;
  mode: WorkbenchPanesMode;
  /** `edit`: the tree after a gutter move, to be written to the dashboard. */
  onCommit?: (tree: SplitTree) => void;
  /** `view`: where the reader's gutter positions are kept. */
  storageKey?: string;
}

function readStored(key: string | undefined, signature: string): SplitFractions | null {
  if (!key) return null;
  try {
    return parseStoredSplit(window.localStorage.getItem(key), signature);
  } catch {
    return null;
  }
}

function writeStored(key: string | undefined, signature: string, fractions: SplitFractions | null) {
  if (!key) return;
  try {
    if (fractions) window.localStorage.setItem(key, serializeStoredSplit(signature, fractions));
    else window.localStorage.removeItem(key);
  } catch {
    // Storage blocked or full: the positions last for as long as the page does.
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
 * A workbench drawn as nested panes with a draggable gutter between neighbours,
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
const WorkbenchPanes: React.FC<WorkbenchPanesProps> = ({
  tree,
  cells,
  height,
  unit,
  mode,
  onCommit,
  storageKey,
}) => {
  // The parent rebuilds the tree on every render; panes and storage care about
  // its content.
  const treeKey = JSON.stringify(tree);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const base = useMemo(() => tree, [treeKey]);
  const signature = useMemo(() => splitSignature(base), [base]);

  // The reader's own gutter positions. Read once on mount, so the first paint
  // is already theirs, and again when the structure or key changes under us.
  const [stored, setStored] = useState<SplitFractions | null>(() =>
    mode === 'view' ? readStored(storageKey, signature) : null,
  );
  const loadedFor = useRef({ storageKey, signature });
  useEffect(() => {
    if (loadedFor.current.storageKey === storageKey && loadedFor.current.signature === signature) {
      return;
    }
    loadedFor.current = { storageKey, signature };
    setStored(mode === 'view' ? readStored(storageKey, signature) : null);
  }, [storageKey, signature, mode]);

  const current = useMemo(
    () => (mode === 'view' ? withFractions(base, stored) : base),
    [base, stored, mode],
  );
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
  const latest = useRef({ shown, base, mode, unit, onCommit, storageKey, signature });
  latest.current = { shown, base, mode, unit, onCommit, storageKey, signature };

  /** Make `next` the workbench's layout: written to the dashboard in the
   *  editor, kept in this browser for a reader. */
  const commit = useCallback((next: SplitTree) => {
    const now = latest.current;
    if (now.mode === 'edit') {
      now.onCommit?.(next);
    } else if (now.mode === 'view') {
      const fractions = treeFractions(next);
      const value = sameFractions(fractions, treeFractions(now.base)) ? null : fractions;
      setStored(value);
      writeStored(now.storageKey, now.signature, value);
    }
  }, []);

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
    const wanted = (at - d.start) / d.pxPerUnit;
    // The editor stores whole units, so the handle snaps to them as it goes: what
    // is seen is what will be saved.
    const moved = moveGutterTree(
      d.from,
      d.path,
      d.gutter,
      latest.current.mode === 'edit' ? Math.round(wanted) : wanted,
      latest.current.unit,
    );
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
    const moved = moveGutterTree(shown, path, gutter, k === 0 ? -step : step, unit);
    if (moved.delta !== 0) commit(moved.tree);
  };

  const renderNode = (node: SplitNode, path: number[], grow: number): React.ReactNode => {
    const pane: React.CSSProperties = { flex: `${grow} 1 0px`, minWidth: 0, minHeight: 0 };
    if (node.kind === 'leaf') {
      const cell = cells.get(node.key);
      if (!cell) return <div key={`tile-${node.key}`} className="depictio-workbench-pane" style={pane} />;
      const props = cell.props as { className?: string; style?: React.CSSProperties };
      return React.cloneElement(cell as React.ReactElement<Record<string, unknown>>, {
        key: `tile-${node.key}`,
        className: ['react-grid-item', 'depictio-workbench-pane', props.className]
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
        className="depictio-workbench-node"
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
                className="depictio-workbench-gutter"
                data-testid="workbench-gutter"
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
                style={{ flex: `0 0 ${WORKBENCH_GUTTER_PX}px` }}
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
        'depictio-workbench-split react-grid-layout' +
        (live ? ' depictio-workbench-split--dragging' : '')
      }
      data-testid="workbench-split"
      data-mode={mode}
      style={{ height, width: '100%' }}
    >
      {renderNode(shown.root, [], 1)}
    </div>
  );
};

export default WorkbenchPanes;
