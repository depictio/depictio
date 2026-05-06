/**
 * Image builder form. Mirrors design_image() in
 * depictio/dash/modules/image_component/design_ui.py — picks the column
 * holding image keys/filenames, an S3 base prefix, optional caption, and a
 * click behavior, with a live placeholder gallery preview on the right.
 */
import React from 'react';
import {
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import DesignShell from '../shared/DesignShell';
import ImagePreview from './ImagePreview';

const CLICK_BEHAVIORS = [
  { value: 'modal', label: 'Open in modal' },
  { value: 'newtab', label: 'Open in new tab' },
  { value: 'none', label: 'No action' },
];

const ImageBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    image_column?: string;
    s3_base_folder?: string;
    description?: string;
    click_behavior?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const form = (
    <Stack gap="md">
      <Title order={6} fw={700}>
        Image Gallery configuration
      </Title>

      <TextInput
        label="Title"
        value={config.title ?? ''}
        onChange={(e) => patchConfig({ title: e.currentTarget.value })}
      />

      <ColumnSelect
        label="Image column"
        description="Column whose values are S3 keys / filenames of images."
        value={config.image_column}
        onChange={(name) => patchConfig({ image_column: name })}
        required
      />

      <TextInput
        label="S3 base folder"
        description="Prefix prepended to each image path."
        placeholder="s3://bucket/path/"
        value={config.s3_base_folder ?? ''}
        onChange={(e) => patchConfig({ s3_base_folder: e.currentTarget.value })}
      />

      <Textarea
        label="Description"
        description="Caption shown below the gallery"
        autosize
        minRows={2}
        value={config.description ?? ''}
        onChange={(e) => patchConfig({ description: e.currentTarget.value })}
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Click behavior
        </Text>
        <SegmentedControl
          value={config.click_behavior ?? 'modal'}
          onChange={(val) => patchConfig({ click_behavior: val })}
          data={CLICK_BEHAVIORS}
          fullWidth
        />
      </Stack>
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<ImagePreview />} />;
};

export default ImageBuilder;
