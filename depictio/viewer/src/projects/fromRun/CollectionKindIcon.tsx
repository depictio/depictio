/**
 * What kind of data collection a plan row is, as one icon with a tooltip:
 * read from the plan's `kind` (a scan of files, or a table a recipe builds)
 * and the scan `mode`, with MultiQC recognised by name so it gets its logo.
 */
import React from 'react';
import { ThemeIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { Z_LAYERS } from 'depictio-react-core';
import type { FromRunDCPreview } from 'depictio-react-core';

import { DcTypeIcon } from '../dcTypeIcon';

interface KindMeta {
  /** Null for MultiQC, which renders its logo. */
  icon: string | null;
  color: string;
  label: string;
  description: string;
  /** What `matched` counts for this kind. */
  unit: 'file' | 'input';
}

export function collectionKindMeta(dc: Pick<FromRunDCPreview, 'kind' | 'mode' | 'data_collection_tag'>): KindMeta {
  if (dc.kind === 'recipe') {
    return {
      icon: 'mdi:table-cog',
      color: 'teal',
      label: 'Table',
      description: 'A table Depictio builds from files of the run.',
      unit: 'input',
    };
  }
  if (/multiqc/i.test(dc.data_collection_tag)) {
    return {
      icon: null,
      color: 'violet',
      label: 'MultiQC',
      description: 'The MultiQC report data of the run.',
      unit: 'file',
    };
  }
  switch ((dc.mode ?? '').toLowerCase()) {
    case 'recursive':
    case 's3_prefix':
      return {
        icon: 'mdi:file-tree-outline',
        color: 'blue',
        label: 'File index',
        description: 'Every matching file found in the run folder.',
        unit: 'file',
      };
    case 'single':
      return {
        icon: 'mdi:file-outline',
        color: 'blue',
        label: 'Single file',
        description: 'One file of the run.',
        unit: 'file',
      };
    case 'url':
      return {
        icon: 'mdi:link-variant',
        color: 'grape',
        label: 'Remote file',
        description: 'One file read from its own address at ingestion.',
        unit: 'file',
      };
    case 'manifest':
      return {
        icon: 'mdi:format-list-bulleted',
        color: 'grape',
        label: 'Manifest',
        description: 'Files listed in a manifest, read at ingestion.',
        unit: 'file',
      };
    default:
      return {
        icon: 'mdi:database-outline',
        color: 'gray',
        label: 'Data collection',
        description: 'Data read from the run folder.',
        unit: 'file',
      };
  }
}

export const CollectionKindIcon: React.FC<{
  dc: Pick<FromRunDCPreview, 'kind' | 'mode' | 'data_collection_tag'>;
  /** `sm` in a one-line row. */
  size?: 'sm' | 'lg';
}> = ({ dc, size = 'lg' }) => {
  const meta = collectionKindMeta(dc);
  const glyph = size === 'lg' ? 18 : 14;
  return (
    <Tooltip
      label={`${meta.label}: ${meta.description}`}
      withArrow
      multiline
      maw={260}
      zIndex={Z_LAYERS.tooltip}
    >
      <ThemeIcon
        variant="light"
        color={meta.color}
        size={size === 'lg' ? 'lg' : 'md'}
        radius="md"
        aria-label={meta.label}
        data-kind={meta.label}
      >
        {meta.icon ? (
          <Icon icon={meta.icon} width={glyph} />
        ) : (
          <DcTypeIcon type="multiqc" size={glyph} withTooltip={false} />
        )}
      </ThemeIcon>
    </Tooltip>
  );
};
