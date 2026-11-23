import React from 'react';
import { Card, Group, Stack, TagsInput, Text, TextInput } from '@mantine/core';
import type { ReportCover, ReportLayer } from 'depictio-react-core';

import { EMPTY_COVER, setCoverField } from './model';

interface CoverFormProps {
  layer: ReportLayer;
  defaults: ReportCover;
  onEdit: (change: (layer: ReportLayer) => ReportLayer) => void;
}

/** The report's cover. An empty field means "use the default", whose value is
 *  the placeholder. */
const CoverForm: React.FC<CoverFormProps> = ({ layer, defaults, onEdit }) => {
  const cover = layer.cover ?? EMPTY_COVER;
  const set = (patch: Partial<ReportCover>) => onEdit((l) => setCoverField(l, patch));

  return (
    <Card withBorder radius="md" p="md" data-testid="report-cover">
      <Stack gap="sm">
        <Text fw={600}>Cover</Text>
        <Text size="xs" c="dimmed">
          Leave a field empty to use the default shown in it.
        </Text>
        <Group grow align="flex-start">
          <TextInput
            label="Title"
            value={cover.title ?? ''}
            placeholder={defaults.title ?? ''}
            onChange={(e) => set({ title: e.currentTarget.value || null })}
          />
          <TextInput
            label="Subtitle"
            value={cover.subtitle ?? ''}
            placeholder={defaults.subtitle ?? ''}
            onChange={(e) => set({ subtitle: e.currentTarget.value || null })}
          />
        </Group>
        <Group grow align="flex-start">
          <TagsInput
            label="Authors"
            value={cover.authors}
            placeholder={cover.authors.length ? undefined : defaults.authors.join(', ')}
            onChange={(authors) => set({ authors })}
          />
          <TextInput
            label="Date"
            value={cover.date ?? ''}
            placeholder={defaults.date ?? ''}
            onChange={(e) => set({ date: e.currentTarget.value || null })}
          />
        </Group>
      </Stack>
    </Card>
  );
};

export default CoverForm;
