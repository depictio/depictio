import React, { Suspense, lazy, useCallback, useMemo, useState } from 'react';
import { ActionIcon, Group, Paper, Portal, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { Z_LAYERS } from '../../../zLayers';
import type { DataGridSelection, TierAnnotation } from '../../data/DataGridBody';
import { useFullscreenPortalTarget } from '../../chrome/useFullscreenPortalTarget';
import { useCardResize } from '../../mapPanel/useCardResize';
import { clampToViewport, useDraggable, type Position } from '../../mapPanel/useDraggable';
import {
  fitSize,
  initialPosition,
  parseGeometry,
  serializeGeometry,
  storageKey,
  type TableGeometry,
} from './floatingTableGeometry';

// Lazy for the reason the data popover's is: AG Grid is a chunk of its own.
const DataGridBody = lazy(() => import('../../data/DataGridBody'));

export interface FloatingDataTableProps {
  /** `String(metadata.index)`: keys the remembered position and size. */
  index: string;
  /** The tile's title, in the card's header. */
  title: string;
  dataRows: Record<string, unknown[]>;
  dataColumns?: string[];
  tierAnnotation?: TierAnnotation;
  /** Ticks the rows of the highlighted points and reports ticked rows back. */
  selection?: DataGridSelection;
  onClose: () => void;
}

function readGeometry(index: string): TableGeometry {
  try {
    return parseGeometry(window.localStorage.getItem(storageKey(index)));
  } catch {
    return parseGeometry(null);
  }
}

function writeGeometry(index: string, g: TableGeometry): void {
  try {
    window.localStorage.setItem(storageKey(index), serializeGeometry(g));
  } catch {
    // Storage can be blocked or full; the card still works, it just forgets.
  }
}

/**
 * A tile's data table lifted out into a draggable, resizable card that stays
 * open while the reader works with the plot.
 *
 * Built on the pieces of the map panel's floating card (`useDraggable`,
 * `useCardResize`, the same layer) rather than as a fourth `FloatingPanelKind`:
 * those panels are one per dashboard family, listed by the family's cross-tab
 * request and persisted in the dashboard's per-family panel state, while this is
 * a per-tile, per-viewer view of rows the tile already holds. It never touches
 * the dashboard model. Portaled to the page (or the fullscreen element) because
 * a grid tile is transformed, which would pin a `position: fixed` card to the
 * tile instead of the viewport.
 */
const FloatingDataTable: React.FC<FloatingDataTableProps> = ({
  index,
  title,
  dataRows,
  dataColumns,
  tierAnnotation,
  selection,
  onClose,
}) => {
  const portalTarget = useFullscreenPortalTarget();
  const [geometry, setGeometry] = useState<TableGeometry>(() => readGeometry(index));
  const commit = useCallback(
    (patch: Partial<TableGeometry>) =>
      setGeometry((prev) => {
        const next = { ...prev, ...patch };
        writeGeometry(index, next);
        return next;
      }),
    [index],
  );

  const { nodeRef, livePosition, dragging, handleProps } = useDraggable((pos: Position) =>
    commit({ x: pos.x, y: pos.y }),
  );
  const {
    liveSize,
    resizing,
    handleProps: resizeHandleProps,
  } = useCardResize(nodeRef, (next) => commit({ width: next.width, height: next.height }));

  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const size = liveSize ?? fitSize(geometry, viewport);
  const position = useMemo(() => {
    const raw =
      livePosition ??
      (geometry.x != null && geometry.y != null
        ? { x: geometry.x, y: geometry.y }
        : initialPosition(size, viewport));
    // A saved position can fall outside a smaller window; re-clamp before use.
    return clampToViewport(raw, size.width, size.height);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [livePosition, geometry.x, geometry.y, size.width, size.height]);

  return (
    <Portal target={portalTarget}>
      <Paper
        ref={nodeRef}
        withBorder
        shadow="md"
        radius="md"
        data-testid="floating-data-table"
        style={{
          position: 'fixed',
          zIndex: Z_LAYERS.mapPanel,
          left: position.x,
          top: position.y,
          width: size.width,
          height: size.height,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <Group
          {...handleProps}
          justify="space-between"
          wrap="nowrap"
          gap="xs"
          px="sm"
          py={6}
          style={{
            cursor: dragging ? 'grabbing' : 'grab',
            touchAction: 'none',
            userSelect: 'none',
            borderBottom: '1px solid var(--mantine-color-default-border)',
          }}
        >
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <Icon icon="tabler:table" width={16} height={16} />
            <Text size="sm" fw={600} truncate>
              {title}
            </Text>
          </Group>
          <ActionIcon
            size="sm"
            variant="subtle"
            color="gray"
            aria-label="Close the floating data table"
            data-testid="floating-data-table-close"
            onClick={onClose}
          >
            <Icon icon="tabler:x" width={16} height={16} />
          </ActionIcon>
        </Group>
        <div style={{ flex: 1, minHeight: 0, padding: 8, display: 'flex', flexDirection: 'column' }}>
          <Suspense fallback={null}>
            <DataGridBody
              dataRows={dataRows}
              dataColumns={dataColumns}
              tierAnnotation={tierAnnotation}
              selection={selection}
              height="100%"
            />
          </Suspense>
        </div>
        {/* Corner grip, the map panel's: a drawn affordance, outside the header's drag. */}
        <div
          {...resizeHandleProps}
          data-no-drag
          aria-label="Resize the data table"
          style={{
            position: 'absolute',
            right: 0,
            bottom: 0,
            width: 18,
            height: 18,
            cursor: 'nwse-resize',
            touchAction: 'none',
            zIndex: 2,
            background:
              'linear-gradient(135deg, transparent 0 50%, var(--mantine-color-dimmed) 50% 57%, transparent 57% 68%, var(--mantine-color-dimmed) 68% 75%, transparent 75%) no-repeat',
            opacity: resizing ? 0.9 : 0.55,
          }}
        />
      </Paper>
    </Portal>
  );
};

export default FloatingDataTable;
