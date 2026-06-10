import React from 'react';
import { ActionIcon, Badge, Box, Code, Divider, Group, Popover, ScrollArea, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';

interface MetadataPopoverProps {
  metadata: StoredMetadata;
}

/**
 * Read-only metadata inspector. Mirrors the behaviour of
 * `create_metadata_button` in `depictio/dash/layouts/edit.py:676-832`, but
 * trimmed to the view-accessible subset: a JSON dump of the component's
 * stored_metadata. Uses Mantine `Code` (not @mantine/code-highlight) to keep
 * the dependency footprint minimal.
 *
 * When `metadata.catalog_source` is set, shows a catalog origin section at
 * the top of the popover (tool name, output ID, description).
 */
const MetadataPopover: React.FC<MetadataPopoverProps> = ({ metadata }) => {
  const json = React.useMemo(() => JSON.stringify(metadata, null, 2), [metadata]);
  const src = metadata.catalog_source as
    | { toolName?: string; outputId?: string; description?: string }
    | undefined;

  return (
    <Popover position="bottom-end" withArrow shadow="md" width={420}>
      <Popover.Target>
        <Tooltip label="Component metadata" withArrow>
          <ActionIcon variant="light" color="cyan" size="sm" aria-label="Component metadata">
            <Icon icon="mdi:information-outline" width={16} height={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="xs">
        <ScrollArea.Autosize mah={440} type="auto">
          {src && (
            <>
              <Box px={4} py={6}>
                <Group gap="xs" mb={6} wrap="nowrap">
                  <Icon icon="mdi:database-search" width={14} color="var(--mantine-color-dimmed)" />
                  <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                    Auto-filled from catalog
                  </Text>
                </Group>
                <Stack gap={3}>
                  <Group gap={6} wrap="nowrap">
                    <Text size="xs" c="dimmed" w={56} style={{ flexShrink: 0 }}>Tool</Text>
                    <Badge size="xs" variant="light" color="gray" radius="sm" tt="none">
                      {src.toolName ?? '—'}
                    </Badge>
                  </Group>
                  <Group gap={6} wrap="nowrap">
                    <Text size="xs" c="dimmed" w={56} style={{ flexShrink: 0 }}>Output</Text>
                    <Code fz={10}>{src.outputId ?? '—'}</Code>
                  </Group>
                  {src.description && (
                    <Group gap={6} wrap="nowrap" align="flex-start">
                      <Text size="xs" c="dimmed" w={56} style={{ flexShrink: 0 }}>Desc.</Text>
                      <Text size="xs" c="dimmed" style={{ lineHeight: 1.3 }}>{src.description}</Text>
                    </Group>
                  )}
                </Stack>
              </Box>
              <Divider my={6} />
            </>
          )}
          <Code block style={{ fontSize: 11, lineHeight: 1.4 }}>
            {json}
          </Code>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
};

export default MetadataPopover;
