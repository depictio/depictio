import React, { useEffect, useState } from 'react';
import { Box, Group, Modal, Skeleton, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import ComponentSnapshot from '../ComponentSnapshot';
import { virtualWidthFor } from '../snapshotDoc';
import { useSnapshotSource } from '../SnapshotContext';
import { typeVisual } from '../visuals';
import { useTabComponent } from './dashboardCache';
import LiveTile from './LiveTile';
import { enlargedCanBeLive } from './thumbnailMode';

interface EnlargedTileProps {
  opened: boolean;
  onClose: () => void;
  tileKey: string;
  tabId: string;
  componentId: string;
  title: string;
  componentType: string | null | undefined;
  png: string | undefined;
}

/** The component at full size, in the real renderer and interactive. Only a
 *  render that failed (or a type the renderer does not draw) shows the
 *  preview frame's image instead. */
const EnlargedTile: React.FC<EnlargedTileProps> = ({
  opened,
  onClose,
  tileKey,
  tabId,
  componentId,
  title,
  componentType,
  png,
}) => {
  const { state } = useSnapshotSource();
  const visual = typeVisual(componentType);
  const [failed, setFailed] = useState(false);
  const [drawn, setDrawn] = useState(false);
  const { metadata, error } = useTabComponent(tabId, componentId, opened);
  useEffect(() => {
    if (opened) {
      setFailed(false);
      setDrawn(false);
    }
  }, [opened]);
  const live = enlargedCanBeLive(componentType) && !failed && metadata !== null && !error;
  // A card keeps a dashboard card's proportions; the rest get the screen.
  const isCard = componentType === 'card';
  const isText = componentType === 'text';
  const height = isCard ? 240 : isText ? 'auto' : 'min(72vh, 680px)';
  const size = isCard ? 440 : isText ? 'lg' : '80rem';

  return (
    // The modal is a portal, but its clicks still bubble up the React tree to
    // the card: the wrapper keeps them from selecting it.
    <Box component="span" style={{ display: 'contents' }} onClick={(e: React.MouseEvent) => e.stopPropagation()}>
      <Modal
        opened={opened}
        onClose={onClose}
        size={size}
        centered
        title={
          <Group gap="xs" wrap="nowrap">
            <Icon icon={visual.icon} width={18} color={visual.color} />
            <Text fw={600} truncate>
              {title}
            </Text>
            <Text size="sm" c="dimmed">
              {visual.label}
            </Text>
          </Group>
        }
        data-testid="report-tile-enlarged"
      >
        <Box style={{ height, position: 'relative' }}>
          {live && metadata && (
            <LiveTile
              tabId={tabId}
              metadata={metadata}
              state={state ?? null}
              onStatus={(s) => (s === 'ready' ? setDrawn(true) : setFailed(true))}
            />
          )}
          {live && !drawn && (
            <Skeleton visible style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }} />
          )}
          {!live && png && (
            <img src={png} alt={title} style={{ maxWidth: '100%', maxHeight: '100%', display: 'block', margin: '0 auto' }} />
          )}
          {!live && !png && (
            <ComponentSnapshot
              tileKey={tileKey}
              width={720}
              height={isCard ? 240 : 420}
              virtualWidth={virtualWidthFor(componentType)}
              interactive
              eager
            />
          )}
        </Box>
      </Modal>
    </Box>
  );
};

export default EnlargedTile;
