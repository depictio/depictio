/**
 * The data collection types the builder offers, how each is named and drawn,
 * and why one may be unavailable on the current root.
 */
import React from 'react';
import { Icon } from '@iconify/react';

import type { BuilderDcType } from 'depictio-react-core';

import { DcTypeIcon } from '../../dcTypeIcon';

export const DC_TYPE_META: Record<BuilderDcType, { label: string; description: string }> = {
  table: { label: 'Table', description: 'Rows and columns: CSV, TSV, parquet...' },
  multiqc: { label: 'MultiQC', description: 'A MultiQC report, read as parquet' },
  image: { label: 'Image', description: 'A table listing image files' },
  indexed_file: { label: 'Indexed file', description: 'VCF, BAM, BED... with their index' },
  geojson: { label: 'GeoJSON', description: 'Map shapes' },
  phylogeny: { label: 'Phylogeny', description: 'A Newick or Nexus tree' },
};

/** Why `type` cannot be used on this root; null when it can. */
export function dcTypeUnavailableReason(type: BuilderDcType, remote: boolean): string | null {
  if (type === 'indexed_file' && remote) {
    return "Indexed files can't be read from S3 yet; use a local folder";
  }
  if (type === 'image' && remote) {
    return 'Images are uploaded from a folder on this computer; use a local folder';
  }
  return null;
}

/** Why the local walk bounds are off on this root; null when they apply. */
export const S3_WALK_REASON =
  'S3 scans list the whole prefix; depth and ignore apply to local folders only';

/** A type's mark: the shared DC icons, plus one for indexed files. */
export const BuilderDcTypeIcon: React.FC<{ type: BuilderDcType; size?: number }> = ({
  type,
  size = 16,
}) =>
  type === 'indexed_file' ? (
    <Icon
      icon="mdi:file-key-outline"
      width={size}
      color="var(--mantine-color-cyan-6)"
      style={{ flexShrink: 0 }}
    />
  ) : (
    <DcTypeIcon type={type} size={size} withTooltip={false} />
  );
