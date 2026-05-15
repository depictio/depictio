/**
 * Text builder form. No data binding — text components document and organize
 * the dashboard. Mirrors design_text() in depictio/dash/modules/text_component
 * but trimmed to the essentials: title + heading level + alignment + body.
 */
import React from 'react';
import {
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useBuilderStore } from '../store/useBuilderStore';
import DesignShell from '../shared/DesignShell';
import TextPreview from './TextPreview';

const ORDER_OPTIONS = [
  { value: '1', label: 'H1 — Largest' },
  { value: '2', label: 'H2' },
  { value: '3', label: 'H3' },
  { value: '4', label: 'H4' },
  { value: '5', label: 'H5' },
  { value: '6', label: 'H6 — Smallest' },
];

const ALIGNMENT_OPTIONS = [
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Center' },
  { value: 'right', label: 'Right' },
];

const TextBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    order?: number | string;
    alignment?: string;
    body?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const orderStr = String(config.order ?? 1);
  const alignment = config.alignment ?? 'left';

  const form = (
    <Stack gap="md">
      <Title order={6} fw={700}>
        Text component configuration
      </Title>

      <TextInput
        label="Title"
        description="Heading text shown at the top of the block."
        placeholder="Section title"
        value={config.title ?? ''}
        onChange={(e) => patchConfig({ title: e.currentTarget.value })}
      />

      <Select
        label="Heading level"
        description="H1 is the largest; H6 the smallest."
        data={ORDER_OPTIONS}
        value={orderStr}
        onChange={(val) => patchConfig({ order: val ? Number(val) : 1 })}
        allowDeselect={false}
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Alignment
        </Text>
        <SegmentedControl
          value={alignment}
          onChange={(val) => patchConfig({ alignment: val })}
          data={ALIGNMENT_OPTIONS}
          fullWidth
        />
      </Stack>

      <Textarea
        label="Body"
        description="Optional paragraph rendered below the title."
        autosize
        minRows={3}
        value={config.body ?? ''}
        onChange={(e) => patchConfig({ body: e.currentTarget.value })}
      />
    </Stack>
  );

  return (
    <DesignShell formSlot={form} previewSlot={<TextPreview />} hideColumns />
  );
};

export default TextBuilder;
