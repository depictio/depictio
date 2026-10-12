/**
 * Image properties: an image collection is a table whose `image_column`
 * names each image; the images themselves live in a folder of the root (a
 * local root) or under an S3 folder (an `s3://` root).
 */
import React from 'react';
import { Select, Stack, TextInput } from '@mantine/core';

import type { BuilderImageProps } from 'depictio-react-core';

import { FormatFields } from './TableForm';

export const ImageForm: React.FC<{
  props: BuilderImageProps;
  onChange: (props: BuilderImageProps) => void;
  columns: string[];
  remote: boolean;
}> = ({ props, onChange, columns, remote }) => (
  <Stack gap="xs">
    <FormatFields
      format={props.format}
      separator={props.separator}
      onChange={(patch) => onChange({ ...props, ...patch })}
    />
    {columns.length > 0 ? (
      <Select
        label="Image column"
        description="The column holding each image's file name or path"
        placeholder="Pick a column"
        value={props.image_column || null}
        data={columns.includes(props.image_column) || !props.image_column ? columns : [props.image_column, ...columns]}
        searchable
        onChange={(v) => onChange({ ...props, image_column: v ?? '' })}
        error={!props.image_column ? 'Required' : undefined}
        data-testid="builder-props-image-column"
      />
    ) : (
      <TextInput
        label="Image column"
        description="The column holding each image's file name or path"
        value={props.image_column}
        onChange={(e) => onChange({ ...props, image_column: e.currentTarget.value })}
        error={!props.image_column ? 'Required' : undefined}
        data-testid="builder-props-image-column"
      />
    )}
    {remote ? (
      <TextInput
        label="S3 folder of the images"
        description="Optional: where the images are, when not next to the table"
        placeholder="s3://bucket/images/"
        value={props.s3_base_folder ?? ''}
        onChange={(e) => onChange({ ...props, s3_base_folder: e.currentTarget.value })}
        spellCheck={false}
      />
    ) : (
      <TextInput
        label="Images folder"
        description="Optional: the folder holding the images, relative to the root"
        placeholder="images/"
        value={props.local_images_path ?? ''}
        onChange={(e) => onChange({ ...props, local_images_path: e.currentTarget.value })}
        spellCheck={false}
      />
    )}
  </Stack>
);
