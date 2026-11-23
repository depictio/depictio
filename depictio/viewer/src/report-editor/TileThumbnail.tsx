import React, { useState } from 'react';
import { Box, Modal, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import ComponentSnapshot from './ComponentSnapshot';
import { virtualWidthFor } from './snapshotDoc';
import { useSnapshotSource } from './SnapshotContext';
import { typeVisual } from './visuals';

export const THUMB_W = 192;
export const THUMB_H = 120;
const LARGE_W = 480;
const LARGE_H = 360;

interface TileThumbnailProps {
  tileKey: string;
  title: string;
  componentType: string | null | undefined;
  /** The frame's PNG of a Plotly figure, when it has sent one. */
  png: string | undefined;
}

/** A card's thumbnail: the figure's PNG, else a snapshot of the component,
 *  else its type icon. Clicking it opens a larger view. */
const TileThumbnail: React.FC<TileThumbnailProps> = ({ tileKey, title, componentType, png }) => {
  const { snapshots } = useSnapshotSource();
  const [large, setLarge] = useState(false);
  const visual = typeVisual(componentType);
  const hasSnapshot = Boolean(snapshots[tileKey]);
  const hasImage = Boolean(png) || hasSnapshot;

  const frame = (
    <Box
      w={THUMB_W}
      h={THUMB_H}
      style={{
        flex: 'none',
        borderRadius: 'var(--mantine-radius-sm)',
        overflow: 'hidden',
        border: '1px solid var(--mantine-color-default-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {png ? (
        <img src={png} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
      ) : hasSnapshot ? (
        <ComponentSnapshot
          tileKey={tileKey}
          width={THUMB_W - 2}
          height={THUMB_H - 2}
          virtualWidth={virtualWidthFor(componentType)}
        />
      ) : (
        <Icon icon={visual.icon} width={28} color={visual.color} />
      )}
    </Box>
  );

  if (!hasImage) return frame;
  return (
    // The modal is a portal, but its clicks still bubble up the React tree to
    // the card: the wrapper keeps them from selecting it.
    <Box component="span" style={{ display: 'contents' }} onClick={(e: React.MouseEvent) => e.stopPropagation()}>
      <UnstyledButton
        onClick={() => setLarge(true)}
        aria-label={`Enlarge the preview of ${title}`}
        style={{ flex: 'none', display: 'flex' }}
        data-testid={`report-thumbnail-${tileKey}`}
      >
        {frame}
      </UnstyledButton>
      <Modal
        opened={large}
        onClose={() => setLarge(false)}
        title={title}
        size="auto"
        centered
      >
        {png ? (
          <img src={png} alt={title} style={{ width: LARGE_W, height: 'auto', display: 'block' }} />
        ) : (
          <Box style={{ border: '1px solid var(--mantine-color-default-border)' }}>
            <ComponentSnapshot
              tileKey={tileKey}
              width={LARGE_W}
              height={componentType === 'card' ? LARGE_W * 0.6 : LARGE_H}
              virtualWidth={virtualWidthFor(componentType)}
              interactive
              eager
            />
          </Box>
        )}
      </Modal>
    </Box>
  );
};

export default TileThumbnail;
