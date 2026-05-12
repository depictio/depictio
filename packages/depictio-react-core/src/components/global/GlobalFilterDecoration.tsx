/**
 * Visual treatment for a filter card that is currently a global filter:
 * a 3 px blue left stripe + a small globe icon prepended to the title row,
 * and (for synthetic-from-other-tab cards) a short "From [Tab name]" caption
 * below the renderer.
 *
 * Used by the unified left rail (App.tsx + InteractiveGroupCard) to mark
 * promoted filters without dropping them into a separate section.
 */

import React from 'react';
import { Box, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface GlobalDecorationInfo {
  /** True when the underlying card is rendered from a synthetic StoredMetadata
   *  (i.e. the source component lives on another tab, surfaced here so the
   *  user can still edit the value from the current tab). */
  isSynthetic: boolean;
  /** Title of the tab where the global filter was originally promoted. Shown
   *  in the small caption only for synthetics — native promotions are
   *  self-evident. */
  sourceTabName?: string;
  /** Display name of the global filter — drawn next to the globe icon. */
  label?: string;
}

export interface GlobalFilterDecorationProps {
  decoration?: GlobalDecorationInfo;
  children: React.ReactNode;
}

const GlobalFilterDecoration: React.FC<GlobalFilterDecorationProps> = ({
  decoration,
  children,
}) => {
  if (!decoration) return <>{children}</>;
  return (
    <Box
      pl="xs"
      style={{
        borderLeft: '3px solid var(--mantine-color-blue-filled)',
        borderRadius: '2px 0 0 2px',
        position: 'relative',
      }}
    >
      <Group gap={4} mb={2} wrap="nowrap" align="center">
        <Icon
          icon="tabler:world"
          width={12}
          color="var(--mantine-color-blue-filled)"
          aria-label="Global filter"
        />
        <Text size="xs" fw={600} c="blue.7" tt="uppercase" style={{ letterSpacing: 0.4 }}>
          Global{decoration.label ? ` · ${decoration.label}` : ''}
        </Text>
      </Group>
      {children}
      {decoration.isSynthetic && decoration.sourceTabName && (
        <Text size="xs" c="dimmed" mt={2} fs="italic">
          From {decoration.sourceTabName}
        </Text>
      )}
    </Box>
  );
};

export default GlobalFilterDecoration;
