import React from 'react';
import { Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** Per-DC-type icon mapping, shared by the Data Collections manager and the
 *  Ingestion report so the same type always looks identical across tabs.
 *  MultiQC is handled specially (renders its logo, not an mdi icon). */
export const DC_TYPE_ICON: Record<string, { icon: string; color: string; label: string }> = {
  table: { icon: 'mdi:table', color: 'teal', label: 'Table' },
  jbrowse2: { icon: 'mdi:dna', color: 'teal', label: 'JBrowse2' },
  image: { icon: 'mdi:image-outline', color: 'pink', label: 'Image' },
  geojson: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'GeoJSON' },
  map: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'Map' },
  phylogeny: { icon: 'mdi:graph-outline', color: 'grape', label: 'Phylogeny' },
};

const FALLBACK = { icon: 'mdi:file-document-outline', color: 'gray', label: 'unknown' };

/** Resolve a DC type (+ optional coordinates flag) to its icon descriptor. */
export function dcTypeMeta(
  type: string | null | undefined,
  isCoord?: boolean,
): { icon: string; color: string; label: string; isMultiqc: boolean } {
  const t = (type || '').toLowerCase();
  if (t === 'multiqc') return { icon: '', color: 'violet', label: 'MultiQC', isMultiqc: true };
  if (isCoord)
    return {
      icon: 'mdi:map-marker-radius-outline',
      color: 'grape',
      label: 'Coordinates',
      isMultiqc: false,
    };
  const m = DC_TYPE_ICON[t] ?? { ...FALLBACK, label: type || 'unknown' };
  return { ...m, isMultiqc: false };
}

/** Renders the icon for a DC type — the MultiQC logo or a coloured mdi glyph. */
export const DcTypeIcon: React.FC<{
  type: string | null | undefined;
  isCoord?: boolean;
  size?: number;
  withTooltip?: boolean;
}> = ({ type, isCoord, size = 18, withTooltip = true }) => {
  const m = dcTypeMeta(type, isCoord);
  const el = m.isMultiqc ? (
    <img
      src={`${import.meta.env.BASE_URL}logos/multiqc_icon_color.svg`}
      alt="MultiQC"
      width={size}
      height={size}
      style={{ objectFit: 'contain', display: 'block', flexShrink: 0 }}
    />
  ) : (
    <Icon
      icon={m.icon}
      width={size}
      color={`var(--mantine-color-${m.color}-6)`}
      style={{ flexShrink: 0 }}
    />
  );
  if (!withTooltip) return <span style={{ display: 'inline-flex', flexShrink: 0 }}>{el}</span>;
  return (
    <Tooltip label={m.label} withArrow withinPortal>
      <span style={{ display: 'inline-flex', flexShrink: 0 }}>{el}</span>
    </Tooltip>
  );
};
