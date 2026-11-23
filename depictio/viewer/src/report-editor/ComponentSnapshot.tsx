import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Box } from '@mantine/core';

import { VIRTUAL_WIDTH, buildSnapshotDoc } from './snapshotDoc';
import { useSnapshotSource } from './SnapshotContext';

interface ComponentSnapshotProps {
  /** `tab_id:component_id`. */
  tileKey: string;
  /** The box it is shown in, in pixels. The page is laid out 720px wide and scaled to fit. */
  width: number;
  height: number;
  /** Scrollable and clickable inside (the large view); thumbnails are neither. */
  interactive?: boolean;
  /** Mount at once instead of when scrolled into view. */
  eager?: boolean;
  /** The width the component is laid out at before scaling (`virtualWidthFor`). */
  virtualWidth?: number;
}

/** True once the element has been visible; stays true after. */
function useSeen(eager: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(eager || typeof IntersectionObserver === 'undefined');
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
      { rootMargin: '120px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [seen]);
  return { ref, seen };
}

/**
 * A component of the report as the frame shows it, drawn from the markup the
 * frame sent: a script-free iframe (`sandbox=""`) with the report's styles,
 * laid out wide and scaled down. Mounted only once visible, so a long
 * structure does not load every frame at once.
 */
const ComponentSnapshot: React.FC<ComponentSnapshotProps> = ({
  tileKey,
  width,
  height,
  interactive = false,
  eager = false,
  virtualWidth = VIRTUAL_WIDTH,
}) => {
  const { snapshots, styles, baseUrl } = useSnapshotSource();
  const html = snapshots[tileKey];
  const { ref, seen } = useSeen(eager);
  const scale = width / virtualWidth;
  const doc = useMemo(
    () => (html && seen ? buildSnapshotDoc(html, styles, baseUrl, interactive, virtualWidth) : null),
    [html, seen, styles, baseUrl, interactive, virtualWidth],
  );

  return (
    <Box
      ref={ref}
      w={width}
      h={height}
      style={{ overflow: 'hidden', position: 'relative', pointerEvents: interactive ? 'auto' : 'none' }}
      data-testid={`report-snapshot-${tileKey}`}
    >
      {doc && (
        <iframe
          title="Component preview"
          sandbox=""
          srcDoc={doc}
          tabIndex={-1}
          style={{
            border: 0,
            width: virtualWidth,
            height: height / scale,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
            display: 'block',
          }}
        />
      )}
    </Box>
  );
};

export default ComponentSnapshot;
