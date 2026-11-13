/**
 * The data collection types the builder offers, how each is named and drawn,
 * and why one may be unavailable: the server does not build it (its
 * capabilities say why), or the current root cannot hold it.
 */
import React from 'react';
import { Icon } from '@iconify/react';

import { dcTypeAvailability } from 'depictio-react-core';
import type { BuilderCapabilities, BuilderDcType } from 'depictio-react-core';

import { DcTypeIcon } from '../../dcTypeIcon';

export const DC_TYPE_META: Record<BuilderDcType, { label: string; description: string }> = {
  table: { label: 'Table', description: 'Rows and columns: CSV, TSV, parquet...' },
  multiqc: { label: 'MultiQC', description: 'A MultiQC report, read as parquet' },
  image: { label: 'Image', description: 'A table listing image files' },
  indexed_file: { label: 'Indexed file', description: 'VCF, BAM, BED... with their index' },
  genomic_tracks: {
    label: 'Genomic tracks',
    description: 'A manifest of track files (bigWig, BAM, VCF...) for a genome browser',
  },
  bioimage: { label: 'Bioimage', description: 'OME-Zarr, OME-TIFF or SpatialData images' },
  geojson: { label: 'GeoJSON', description: 'Map shapes' },
  phylogeny: { label: 'Phylogeny', description: 'A Newick or Nexus tree' },
};

/** Why `type` cannot be used: the server does not build it, or this root
 *  cannot hold it. Null when it can. */
export function dcTypeUnavailableReason(
  type: BuilderDcType,
  remote: boolean,
  capabilities: BuilderCapabilities,
): string | null {
  const availability = dcTypeAvailability(type, capabilities);
  if (!availability.available) return availability.reason;
  if (type === 'indexed_file' && remote) {
    return "Indexed files can't be read from S3 yet; use a local folder";
  }
  if (type === 'image' && remote) {
    return 'Images are uploaded from a folder on this computer; use a local folder';
  }
  if (type === 'bioimage' && remote) {
    return 'Stores are read from local folders at ingest; use a local folder';
  }
  return null;
}

/** Why the local walk bounds are off on this root; null when they apply. */
export const S3_WALK_REASON =
  'S3 scans list the whole prefix; depth and ignore apply to local folders only';

const OWN_ICONS: Partial<Record<BuilderDcType, { icon: string; color: string }>> = {
  indexed_file: { icon: 'mdi:file-key-outline', color: 'cyan' },
  genomic_tracks: { icon: 'mdi:chart-timeline-variant', color: 'cyan' },
  bioimage: { icon: 'mdi:microscope', color: 'pink' },
};

/** A type's mark: the shared DC icons, plus the builder's own for indexed
 *  files, genomic tracks and bioimages. */
export const BuilderDcTypeIcon: React.FC<{ type: BuilderDcType; size?: number }> = ({
  type,
  size = 16,
}) => {
  const own = OWN_ICONS[type];
  return own ? (
    <Icon
      icon={own.icon}
      width={size}
      color={`var(--mantine-color-${own.color}-6)`}
      style={{ flexShrink: 0 }}
    />
  ) : (
    <DcTypeIcon type={type} size={size} withTooltip={false} />
  );
};
