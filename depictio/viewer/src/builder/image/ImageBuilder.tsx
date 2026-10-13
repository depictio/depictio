/**
 * Image builder form. Mirrors design_image() in
 * depictio/dash/modules/image_component/design_ui.py — picks the column
 * holding image keys/filenames, an S3 base prefix, optional caption, and a
 * click behavior, with a live placeholder gallery preview on the right.
 */
import React from 'react';
import { SegmentedControl, Stack, Textarea, TextInput } from '@mantine/core';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import DesignShell from '../shared/DesignShell';
import { BuilderSection, BuilderSections, Field } from '../shared/BuilderSections';
import PlacementSection from '../shared/PlacementSection';
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
    <BuilderSections builder="image" required={['images']}>
      <BuilderSection
        value="images"
        icon="mdi:image-multiple"
        title="Images"
        subtitle="The column holding the image paths, and where they live"
      >
        <Stack gap="md">
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
        </Stack>
      </BuilderSection>

      <BuilderSection
        value="display"
        icon="mdi:card-text-outline"
        title="Display"
        subtitle="Title, caption and what a click on an image does"
      >
        <Stack gap="md">
          <TextInput
            label="Title"
            value={config.title ?? ''}
            onChange={(e) => patchConfig({ title: e.currentTarget.value })}
          />

          <Textarea
            label="Description"
            description="Caption shown below the gallery"
            autosize
            minRows={2}
            value={config.description ?? ''}
            onChange={(e) => patchConfig({ description: e.currentTarget.value })}
          />

          <Field label="Click behavior" description="What happens when a viewer clicks an image.">
            <SegmentedControl
              value={config.click_behavior ?? 'modal'}
              onChange={(val) => patchConfig({ click_behavior: val })}
              data={CLICK_BEHAVIORS}
              fullWidth
            />
          </Field>
        </Stack>
      </BuilderSection>

      <PlacementSection />
    </BuilderSections>
  );

  return <DesignShell formSlot={form} previewSlot={<ImagePreview />} />;
};

export default ImageBuilder;
