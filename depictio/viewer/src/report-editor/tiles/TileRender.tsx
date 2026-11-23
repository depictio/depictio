/**
 * What a tile shows of its component: the real renderer once the tile is
 * visible and a render slot is free, else (heavy kinds, a failed or slow
 * render) the preview frame's image, else the type icon. See `thumbnailMode`.
 * A tile that has been drawn stays mounted: scrolling back costs nothing.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Box, Skeleton } from '@mantine/core';
import { Icon } from '@iconify/react';

import ComponentSnapshot from '../ComponentSnapshot';
import { virtualWidthFor } from '../snapshotDoc';
import { useSnapshotSource } from '../SnapshotContext';
import { typeVisual } from '../visuals';
import { useTabComponent } from './dashboardCache';
import LiveTile from './LiveTile';
import type { LiveStatus } from './LiveTile';
import { requestRenderSlot } from './renderQueue';
import { thumbnailMode } from './thumbnailMode';

/** A live render that has not drawn by then is given up on. */
export const RENDER_TIMEOUT_MS = 8000;

/**
 * The box a live component is drawn in, about a dashboard cell of its kind.
 * Narrower tiles scale it down whole (never up), so a card keeps its layout
 * instead of being cut to the tile's height.
 */
export function virtualBox(componentType: string | null | undefined): { width: number; height: number } {
  if (componentType === 'card') return { width: 320, height: 200 };
  if (componentType === 'text') return { width: 520, height: 130 };
  return { width: 760, height: 320 };
}

/** The scale and the drawn height of a tile `width` pixels wide. */
export function tileFit(componentType: string | null | undefined, width: number) {
  const box = virtualBox(componentType);
  const virtualWidth = Math.max(width, box.width);
  const scale = width > 0 ? width / virtualWidth : 1;
  return { virtualWidth, virtualHeight: box.height, scale, height: Math.round(box.height * scale) };
}

/** True once the element has been near the viewport; stays true after. */
function useSeenOnce() {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = ref.current;
    if (seen || !el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin: '100px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [seen]);
  return { ref, seen };
}

/** The element's width, followed. */
function useWidth(ref: React.RefObject<HTMLElement>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

interface TileRenderProps {
  tileKey: string;
  tabId: string;
  componentId: string;
  componentType: string | null | undefined;
  /** The frame's PNG of a Plotly figure, when it has sent one. */
  png: string | undefined;
}

const TileRender: React.FC<TileRenderProps> = ({ tileKey, tabId, componentId, componentType, png }) => {
  const { snapshots, state } = useSnapshotSource();
  const { ref, seen } = useSeenOnce();
  const width = useWidth(ref);
  const { virtualWidth, virtualHeight, scale, height } = tileFit(componentType, width);
  const visual = typeVisual(componentType);

  const { metadata, error } = useTabComponent(tabId, componentId, seen);
  const [liveFailed, setLiveFailed] = useState(false);
  const [granted, setGranted] = useState(false);
  const [drawn, setDrawn] = useState(false);
  const releaseRef = useRef<(() => void) | null>(null);
  const timerRef = useRef<number | null>(null);

  const hasSnapshot = Boolean(snapshots[tileKey]);
  const gaveUp = liveFailed || metadata === null || Boolean(error);
  const mode = thumbnailMode({
    componentType,
    metadata,
    liveFailed: gaveUp,
    hasImage: Boolean(png) || hasSnapshot,
  });
  const live = mode === 'live';

  const finish = () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    releaseRef.current?.();
    releaseRef.current = null;
  };

  // A live tile waits for a free slot (3 in flight), then has 8 s to draw.
  useEffect(() => {
    if (!live || !metadata || granted) return;
    const cancel = requestRenderSlot((release) => {
      releaseRef.current = release;
      setGranted(true);
      timerRef.current = window.setTimeout(() => {
        setLiveFailed(true);
        finish();
      }, RENDER_TIMEOUT_MS);
    });
    return cancel;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, metadata, granted]);
  useEffect(() => finish, []);

  const onStatus = (status: LiveStatus) => {
    finish();
    if (status === 'ready') setDrawn(true);
    else setLiveFailed(true);
  };

  return (
    <Box
      ref={ref}
      className="rpt-live"
      style={{ height, position: 'relative', overflow: 'hidden', pointerEvents: 'none' }}
      data-testid={`report-live-${tileKey}`}
      data-mode={mode}
    >
      {live && granted && metadata && width > 0 && (
        <Box
          style={{
            width: virtualWidth,
            height: virtualHeight,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
        >
          <LiveTile tabId={tabId} metadata={metadata} state={state ?? null} onStatus={onStatus} />
        </Box>
      )}
      {live && !drawn && (
        <Skeleton visible style={{ position: 'absolute', inset: 0, borderRadius: 'var(--mantine-radius-sm)' }} />
      )}
      {mode === 'image' && png && (
        <img src={png} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
      )}
      {mode === 'image' && !png && width > 0 && (
        <ComponentSnapshot
          tileKey={tileKey}
          width={width}
          height={height}
          virtualWidth={virtualWidthFor(componentType)}
        />
      )}
      {mode === 'icon' && (
        <Box h="100%" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon icon={visual.icon} width={28} color={visual.color} />
        </Box>
      )}
    </Box>
  );
};

export default TileRender;
