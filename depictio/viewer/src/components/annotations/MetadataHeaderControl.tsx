import React from 'react';
import { createPortal } from 'react-dom';
import { Drawer } from '@mantine/core';
import '../panelAccents.css';
import PanelTitle from '../PanelTitle';
import {
  beginPanelResize,
  ChromeButton,
  dispatchPanelToggle,
  endPanelResize,
  getChromeStyle,
  METADATA_PANEL_TOGGLE_EVENT,
  Z_LAYERS,
} from 'depictio-react-core';

/** The panel holds a grid, so it opens wider than Analysis. Pixels, so the
 *  apps pad their content column by exactly this much. The reader can drag
 *  its left edge to change it (`useMetadataPanelWidth`). */
export const METADATA_PANEL_WIDTH_PX = 760;
export const METADATA_PANEL_MIN_WIDTH_PX = 480;
const METADATA_PANEL_MAX_WIDTH_PX = 1600;
/** Share of the window the panel may take: past it the dashboard is gone. */
const MAX_WIDTH_FRACTION = 0.8;
const WIDTH_KEY = 'metadata-panel-width';
/** The right-hand panels (Analysis, Metadata) sit between the map card and the
 *  modals. */
export const RIGHT_PANEL_Z = Z_LAYERS.mapPanel + 10;
/** Arrow-key step of the resize handle. */
const KEYBOARD_STEP_PX = 24;

const maxWidth = (): number =>
  Math.max(
    METADATA_PANEL_MIN_WIDTH_PX,
    Math.min(
      METADATA_PANEL_MAX_WIDTH_PX,
      Math.round((typeof window === 'undefined' ? 0 : window.innerWidth) * MAX_WIDTH_FRACTION),
    ),
  );
const clampWidth = (px: number): number =>
  Math.min(maxWidth(), Math.max(METADATA_PANEL_MIN_WIDTH_PX, Math.round(px)));

function readWidth(): number {
  try {
    const parsed = Number(localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(parsed) && parsed > 0 ? clampWidth(parsed) : METADATA_PANEL_WIDTH_PX;
  } catch {
    return METADATA_PANEL_WIDTH_PX;
  }
}

/** The panel's width, remembered in this browser. A narrower window clamps it
 *  for now without forgetting the width that was chosen. */
export function useMetadataPanelWidth(): [number, (px: number) => void] {
  const [width, setWidth] = React.useState<number>(readWidth);
  const chosen = React.useRef(width);
  React.useEffect(() => {
    const onResize = () => setWidth(clampWidth(chosen.current));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const update = React.useCallback((px: number) => {
    const next = clampWidth(px);
    chosen.current = next;
    setWidth(next);
    try {
      localStorage.setItem(WIDTH_KEY, String(next));
    } catch {
      // storage off: the width lasts for this page
    }
  }, []);
  return [width, update];
}

/** Capped in vw like the Analysis panel, so a phone keeps a strip of dashboard. */
const panelWidth = (px: number) => `min(${px}px, 92vw)`;
/** Mantine's Drawer default, which the content column's padding matches. */
const PANEL_TRANSITION_MS = 250;

/**
 * Header home of the Metadata panel: the dashboard's metadata tables
 * (samplesheet, metadata sheet) in a grid, where a reader adds session labels
 * and, with the right to, edits the table.
 *
 * Built like the Analysis panel (`GroupingHeaderControl`) on purpose: same
 * button, same docked non-modal drawer below the header, same width
 * announcement to the grid. The two share the right edge, so the app opens
 * one at a time.
 */
const MetadataHeaderControl: React.FC<{
  /** Label columns across every metadata table, shown on the button. */
  labelCount: number;
  opened: boolean;
  onOpenedChange: (opened: boolean) => void;
  /** Whether the app pads its content column for this panel (false on a phone). */
  pushesContent: boolean;
  /** The panel's width, and the app's way to change it (on release of a drag). */
  width: number;
  onWidthChange: (px: number) => void;
  children: React.ReactNode;
}> = ({ labelCount, opened, onOpenedChange, pushesContent, width, onWidthChange, children }) => {
  // Announce only real toggles: the grid applies the swing as a delta.
  const announced = React.useRef(false);
  React.useEffect(() => {
    if (!announced.current) {
      announced.current = true;
      return;
    }
    if (!pushesContent) return;
    dispatchPanelToggle(METADATA_PANEL_TOGGLE_EVENT, {
      willBeOpen: opened,
      swingPx: widthRef.current,
      durationMs: PANEL_TRANSITION_MS,
    });
  }, [opened, pushesContent]);

  // ---- Resizing: drag the left edge, or use the arrow keys on it ---------------
  // The panel follows the pointer through local state, so the dashboard behind
  // is not re-rendered at every pointer move; the app learns the width once,
  // on release, and pads its content column then.
  const widthRef = React.useRef(width);
  widthRef.current = width;
  const [live, setLive] = React.useState<number | null>(null);
  const shown = live ?? width;
  // The handle waits for the panel's slide-in, or it would sit in the air.
  const [settled, setSettled] = React.useState(false);
  // Where the panel's left edge is, measured: a chrome style may leave a margin
  // between the panel and the window, so the width alone does not say.
  const [edge, setEdge] = React.useState<number | null>(null);
  React.useLayoutEffect(() => {
    if (!opened || !settled) return;
    const measure = () => {
      const panel = document.querySelector('.dc-analysis-panel.dc-panel--metadata');
      if (panel) setEdge(panel.getBoundingClientRect().left);
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [opened, settled, shown]);
  React.useEffect(() => {
    if (!opened) {
      setSettled(false);
      return;
    }
    const timer = setTimeout(() => setSettled(true), PANEL_TRANSITION_MS + 30);
    return () => clearTimeout(timer);
  }, [opened]);
  const endDragRef = React.useRef<(() => void) | null>(null);
  React.useEffect(() => () => endDragRef.current?.(), []);
  const beginResize = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    endDragRef.current?.();
    const startX = event.clientX;
    const startWidth = widthRef.current;
    let latest = startWidth;
    const onMove = (e: PointerEvent) => {
      latest = clampWidth(startWidth + (startX - e.clientX));
      setLive(latest);
    };
    const endDrag = () => {
      endDragRef.current = null;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', endDrag);
      window.removeEventListener('pointercancel', endDrag);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      setLive(null);
      onWidthChange(latest);
      endPanelResize();
      // Plotly and the grids re-measure once the content column has settled.
      setTimeout(() => window.dispatchEvent(new Event('resize')), PANEL_TRANSITION_MS + 50);
    };
    endDragRef.current = endDrag;
    beginPanelResize();
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', endDrag);
    window.addEventListener('pointercancel', endDrag);
  };
  const nudge = (deltaPx: number) => {
    onWidthChange(widthRef.current + deltaPx);
    setTimeout(() => window.dispatchEvent(new Event('resize')), PANEL_TRANSITION_MS + 50);
  };

  return (
    <>
      <ChromeButton
        role="toggle"
        collapse
        active={opened}
        icon="metadata"
        label="Metadata"
        tooltip="See the sample metadata, label samples to compare them, edit the table"
        badge={labelCount}
        aria-pressed={opened}
        className="dc-dock--metadata"
        data-testid="metadata-button"
        onClick={() => onOpenedChange(!opened)}
      />
      <Drawer
        opened={opened}
        onClose={() => onOpenedChange(false)}
        position="right"
        size={panelWidth(shown)}
        classNames={{ content: 'dc-analysis-panel dc-panel--metadata', inner: 'dc-analysis-panel-inner' }}
        padding="md"
        // Above the figures and the map card, below Settings and the other
        // modals: opened over this panel they were hidden behind it.
        zIndex={RIGHT_PANEL_Z}
        // A dock, not a modal: the charts stay live while labels change.
        withOverlay={false}
        trapFocus={false}
        lockScroll={false}
        closeOnClickOutside={false}
        // Escape in a grid cell cancels the edit; it must not close the panel.
        closeOnEscape={false}
        shadow="xl"
        styles={{ inner: { top: getChromeStyle().layout.headerHeight } }}
        title={
          <PanelTitle
            icon="mdi:table-edit"
            title="Metadata"
            subtitle="Sample table and the labels you add to it"
            count={labelCount > 0 ? `${labelCount} label column${labelCount === 1 ? '' : 's'}` : null}
          />
        }
        data-testid="metadata-panel"
      >
        {children}
      </Drawer>
      {opened &&
        settled &&
        edge !== null &&
        createPortal(
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the Metadata panel"
          aria-valuenow={shown}
          aria-valuemin={METADATA_PANEL_MIN_WIDTH_PX}
          tabIndex={0}
          onPointerDown={beginResize}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') {
              e.preventDefault();
              nudge(KEYBOARD_STEP_PX);
            } else if (e.key === 'ArrowRight') {
              e.preventDefault();
              nudge(-KEYBOARD_STEP_PX);
            }
          }}
          data-testid="metadata-panel-resizer"
          style={{
            position: 'fixed',
            top: getChromeStyle().layout.headerHeight,
            bottom: 0,
            left: (edge ?? 0) - 5,
            width: 10,
            cursor: 'col-resize',
            touchAction: 'none',
            zIndex: RIGHT_PANEL_Z + 1,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          {/* A hairline grip on a wider hit area. */}
          <div
            aria-hidden
            style={{ width: 3, height: '100%', background: 'var(--mantine-color-default-border)' }}
          />
        </div>,
        document.body,
      )}
    </>
  );
};

export default MetadataHeaderControl;
