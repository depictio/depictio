import React from 'react';
import { ActionIcon, Popover, ScrollArea, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useFullscreenPortalTarget } from '../../chrome/useFullscreenPortalTarget';
import { helpTopics, type HelpContext } from './help';

/** The "?" button on the image: how to use this tile, for this image. */
const BioimageHelp: React.FC<{ context: HelpContext }> = ({ context }) => {
  const portalTarget = useFullscreenPortalTarget();
  const topics = helpTopics(context);
  return (
    <Popover
      width={340}
      position="bottom-end"
      withArrow
      shadow="md"
      withinPortal
      portalProps={{ target: portalTarget }}
    >
      <Popover.Target>
        <Tooltip label="How to use this viewer" withArrow openDelay={300}>
          <ActionIcon
            size="sm"
            variant="default"
            aria-label="How to use this viewer"
            data-testid="bioimage-help"
          >
            <Icon icon="tabler:help" width={14} height={14} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="sm" data-testid="bioimage-help-panel">
        <Text size="sm" fw={600} mb={6}>
          How to use this viewer
        </Text>
        <ScrollArea.Autosize mah={360} type="auto" offsetScrollbars>
          <Stack gap={8}>
            {topics.map((t) => (
              <div key={t.key}>
                <Text size="xs" fw={600}>
                  {t.title}
                </Text>
                <Text size="xs" c="dimmed">
                  {t.text}
                </Text>
              </div>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
};

export default BioimageHelp;
