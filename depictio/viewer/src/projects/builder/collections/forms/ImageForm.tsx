/**
 * Image properties: an image collection is a table whose `image_column`
 * names each image. The images live in a folder of the (local) root, which
 * `depictio ingest` uploads to an S3 folder. Images are refused on an
 * `s3://` root, so only local roots get here.
 */
import React from 'react';
import { Group, NumberInput, Stack, TagsInput, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import { SPATIALDATA_FORMAT } from 'depictio-react-core';
import type { BuilderCapabilities, BuilderImageProps } from 'depictio-react-core';

import type { BuilderMode } from '../../mode';
import {
  ColumnField,
  ColumnsDescription,
  FoldSection,
  FormatFields,
  OptionsSection,
  ReaderOptionsFields,
} from './shared';

/** The table formats an image list can be in: the server's, plus `mixed`. */
function imageFormats(capabilities: BuilderCapabilities): string[] {
  return [...capabilities.table_formats.filter((f) => f !== SPATIALDATA_FORMAT), 'mixed'];
}

export const ImageForm: React.FC<{
  props: BuilderImageProps;
  onChange: (props: BuilderImageProps) => void;
  columns: string[];
  capabilities: BuilderCapabilities;
  mode: BuilderMode;
}> = ({ props, onChange, columns, capabilities, mode }) => {
  const s3 = props.s3_base_folder ?? '';
  const s3Invalid = s3.trim() !== '' && !s3.trim().startsWith('s3://');
  const standaloneMissing = mode === 'standalone' && !s3.trim();
  const thumb = props.thumbnail_size;
  const thumbInvalid = typeof thumb === 'number' && (thumb < 50 || thumb > 1000);
  return (
    <Stack gap="xs">
      <FormatFields
        format={props.format}
        separator={props.separator}
        formats={imageFormats(capabilities)}
        label="Format of the image list"
        onChange={(patch) => onChange({ ...props, ...patch })}
      />
      <ColumnField
        label="Image column"
        description="The column holding each image's file name or path"
        value={props.image_column}
        columns={columns}
        required
        testId="builder-props-image-column"
        onChange={(v) => onChange({ ...props, image_column: v ?? '' })}
      />
      <Group grow align="flex-start">
        <TextInput
          label="Images folder"
          description="Optional: the folder holding the images, relative to the root"
          placeholder="images/"
          value={props.local_images_path ?? ''}
          onChange={(e) => onChange({ ...props, local_images_path: e.currentTarget.value })}
          spellCheck={false}
        />
        <TextInput
          label="S3 folder of the images"
          description={
            mode === 'standalone'
              ? 'Needed by depictio ingest: where it uploads the images'
              : 'Optional: the server picks one'
          }
          placeholder="s3://bucket/project/images/"
          value={s3}
          onChange={(e) => onChange({ ...props, s3_base_folder: e.currentTarget.value })}
          error={s3Invalid ? 'Starts with s3://' : undefined}
          spellCheck={false}
          data-testid="builder-props-s3-base-folder"
        />
      </Group>
      {standaloneMissing && (
        <Group gap={6} wrap="nowrap" data-testid="builder-props-s3-base-folder-warning">
          <Icon icon="mdi:alert-outline" width={14} color="var(--mantine-color-yellow-6)" style={{ flexShrink: 0 }} />
          <Text size="xs" c="dimmed">
            Without an S3 folder, depictio ingest has nowhere to upload the images.
          </Text>
        </Group>
      )}
      <OptionsSection>
      <ReaderOptionsFields
        format={props.format}
        reader={props.reader}
        allowed={capabilities.reader_options}
        onChange={(reader) => onChange({ ...props, reader })}
      />
      <FoldSection
        label="Thumbnails and extensions"
        description="thumbnail size, accepted image types"
        initiallyOpen={typeof thumb === 'number' || Boolean(props.supported_formats?.length)}
      >
        <Group grow align="flex-start">
          <NumberInput
            label="Thumbnail size (px)"
            description="50 to 1000; blank for 150"
            min={50}
            max={1000}
            allowDecimal={false}
            value={thumb ?? ''}
            onChange={(v) => onChange({ ...props, thumbnail_size: typeof v === 'number' ? v : null })}
            error={thumbInvalid ? '50 to 1000' : undefined}
          />
          <TagsInput
            label="Image extensions"
            description="Blank: the usual ones (.png, .jpg, .tiff...)"
            placeholder=".png, .jpg"
            value={props.supported_formats ?? []}
            onChange={(supported_formats) => onChange({ ...props, supported_formats })}
          />
        </Group>
      </FoldSection>
      <ColumnsDescription
        columns={columns}
        value={props.columns_description}
        onChange={(columns_description) => onChange({ ...props, columns_description })}
      />
      </OptionsSection>
    </Stack>
  );
};
