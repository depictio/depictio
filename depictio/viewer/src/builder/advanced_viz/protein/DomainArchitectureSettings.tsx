/**
 * `domain_architecture` settings: one row per protein, or proteins grouped by
 * their architecture. The hits are the bound collection itself, so there is no
 * companion collection to pick.
 */
import React from 'react';
import { SegmentedControl, Stack, Text } from '@mantine/core';
import { str, type ProteinKindSettingsProps } from './common';

const DomainArchitectureSettings: React.FC<ProteinKindSettingsProps> = ({ config, onChange }) => (
  <Stack gap={4}>
    <Text size="sm" fw={500}>
      View
    </Text>
    <SegmentedControl
      data={[
        { value: 'proteins', label: 'Proteins' },
        { value: 'architectures', label: 'Architectures' },
      ]}
      value={str(config?.view) ?? 'proteins'}
      onChange={(v) => onChange({ view: v })}
      fullWidth
      size="xs"
    />
  </Stack>
);

export default DomainArchitectureSettings;
