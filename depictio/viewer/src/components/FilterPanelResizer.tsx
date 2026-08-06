import React from 'react';
import { FILTER_PANEL_KEYBOARD_STEP } from '../hooks/useFilterPanelWidth';

/** Width of the handle's grid column when the panel is expanded. */
export const FILTER_PANEL_RESIZER_WIDTH = 6;

interface FilterPanelResizerProps {
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  onNudge: (deltaPx: number) => void;
  /** Collapsed panel: nothing to resize, so the handle goes inert rather than
   *  unmounting — the grid keeps its three tracks, and a track count that never
   *  changes is what lets `grid-template-columns` animate the collapse. */
  collapsed?: boolean;
}

/**
 * Drag handle between the filter panel and the content column.
 *
 * Lives in its own grid column rather than floating over the panel edge: a
 * real column can't overlap the controls underneath it, so there is no z-index
 * or hit-testing to reason about.
 */
const FilterPanelResizer: React.FC<FilterPanelResizerProps> = ({
  onPointerDown,
  onNudge,
  collapsed = false,
}) => (
  <div
    role={collapsed ? undefined : 'separator'}
    aria-orientation={collapsed ? undefined : 'vertical'}
    aria-label={collapsed ? undefined : 'Resize filter panel'}
    aria-hidden={collapsed || undefined}
    tabIndex={collapsed ? -1 : 0}
    onPointerDown={collapsed ? undefined : onPointerDown}
    onKeyDown={
      collapsed
        ? undefined
        : (event) => {
            if (event.key === 'ArrowLeft') {
              event.preventDefault();
              onNudge(-FILTER_PANEL_KEYBOARD_STEP);
            } else if (event.key === 'ArrowRight') {
              event.preventDefault();
              onNudge(FILTER_PANEL_KEYBOARD_STEP);
            }
          }
    }
    style={{
      cursor: collapsed ? undefined : 'col-resize',
      // Pointer events only; the browser's own pan gesture would otherwise
      // fight the drag on touch devices.
      touchAction: 'none',
      alignSelf: 'stretch',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      overflow: 'hidden',
    }}
  >
    {/* The hit area is the full column; the visible grip is a hairline, so the
        divider reads as chrome rather than as a control. */}
    {!collapsed && (
      <div
        aria-hidden
        style={{
          width: 2,
          height: '100%',
          borderRadius: 1,
          background: 'var(--mantine-color-default-border)',
        }}
      />
    )}
  </div>
);

export default FilterPanelResizer;
