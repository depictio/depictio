import React from 'react';
import { Badge, Box, Code, Divider, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';

interface MetadataBodyProps {
  metadata: StoredMetadata;
}

/**
 * The component-metadata view, without the surface it is shown on.
 *
 * `MetadataPopover` renders this inside a popover; the inspector's Info tab
 * renders the same thing docked. Extracted rather than duplicated so the two
 * can't drift — which is exactly what happened to the filter panel before it
 * became one shared component.
 *
 * Read-only. Mirrors the view-accessible subset of `create_metadata_button` in
 * `depictio/dash/layouts/edit.py:676-832`: a JSON dump of the component's
 * stored_metadata, preceded by a catalog origin block when
 * `metadata.catalog_source` is set. Uses Mantine `Code` (not
 * @mantine/code-highlight) to keep the dependency footprint minimal.
 */
const MetadataBody: React.FC<MetadataBodyProps> = ({ metadata }) => {
  const json = React.useMemo(() => JSON.stringify(metadata, null, 2), [metadata]);
  const src = metadata.catalog_source as
    | { toolName?: string; outputId?: string; description?: string }
    | undefined;

  return (
    <>
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
    </>
  );
};

export default MetadataBody;
