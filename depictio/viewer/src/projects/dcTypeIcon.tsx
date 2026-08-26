import React from 'react';
import { Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** The type axis of a data collection: what kind of thing it holds, and so
 *  which components can bind to it. One entry per stored `dc_type`, plus
 *  `geomap` — a table whose config carries lat/lon columns
 *  (DCTableCoordinatesConfig, still dc_type="table" on the wire, but a
 *  distinct thing to the reader and the only table Map components accept).
 *
 *  Shared by the Data Collections manager and the Ingestion report so the
 *  same collection looks identical across tabs. MultiQC is handled specially
 *  (renders its logo, not an mdi icon). */
export const DC_TYPE_ICON: Record<string, { icon: string; color: string; label: string }> = {
  table: { icon: 'mdi:table', color: 'teal', label: 'Table' },
  geomap: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'Geomap' },
  jbrowse2: { icon: 'mdi:dna', color: 'teal', label: 'JBrowse2' },
  image: { icon: 'mdi:image-outline', color: 'pink', label: 'Image' },
  geojson: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'GeoJSON' },
  map: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'Map' },
  phylogeny: { icon: 'mdi:graph-outline', color: 'grape', label: 'Phylo tree' },
};

/** The geomap flavour's colour and glyph, reused wherever coordinates are
 *  announced outside the type badge itself (the upload modal's detection
 *  alert, the map preview). */
export const GEO_COLOR = DC_TYPE_ICON.geomap.color;
export const GEO_ICON = DC_TYPE_ICON.geomap.icon;

const FALLBACK = { icon: 'mdi:file-document-outline', color: 'gray', label: 'unknown' };

/** The subset of a data collection the type axis classifies on. */
export interface DcClassifiable {
  config?: Record<string, unknown>;
}

function dcProps(dc: DcClassifiable): Record<string, unknown> | undefined {
  return dc.config?.dc_specific_properties as Record<string, unknown> | undefined;
}

/** A table is a geomap when its config carries explicit lat/lon column hints.
 *  Mirrors validation.py:dc_has_coordinates, which is what gates the Map
 *  component's DC picker. */
export function dcHasCoordinates(dc: DcClassifiable): boolean {
  const type = (dc.config?.type as string | undefined)?.toLowerCase();
  if (type !== 'table') return false;
  const props = dcProps(dc);
  return Boolean(props?.lat_column) && Boolean(props?.lon_column);
}

/** The lat/lon column names a geomap plots on, if any. */
export function dcCoordinateColumns(
  dc: DcClassifiable,
): { lat: string; lon: string } | null {
  const props = dcProps(dc);
  const lat = props?.lat_column as string | undefined;
  const lon = props?.lon_column as string | undefined;
  return lat && lon ? { lat, lon } : null;
}

/** Resolve a DC type to its icon descriptor. `geo` promotes a table to the
 *  geomap flavour — callers that only hold a bare type string (the Ingestion
 *  report reads a report payload, not a config) can leave it out. */
export function dcTypeMeta(
  type: string | null | undefined,
  opts?: { geo?: boolean },
): { icon: string; color: string; label: string; isMultiqc: boolean } {
  const t = (type || '').toLowerCase();
  if (t === 'multiqc') return { icon: '', color: 'violet', label: 'MultiQC', isMultiqc: true };
  const key = opts?.geo && t === 'table' ? 'geomap' : t;
  const m = DC_TYPE_ICON[key] ?? { ...FALLBACK, label: type || 'unknown' };
  return { ...m, isMultiqc: false };
}

/** Same descriptor, resolved from a whole data collection so the geomap
 *  flavour is picked up without the caller re-deriving it. */
export function dcTypeMetaFor(dc: DcClassifiable) {
  return dcTypeMeta(dc.config?.type as string | undefined, { geo: dcHasCoordinates(dc) });
}

/** Renders the icon for a DC type — the MultiQC logo or a coloured mdi glyph. */
export const DcTypeIcon: React.FC<{
  type: string | null | undefined;
  geo?: boolean;
  size?: number;
  withTooltip?: boolean;
}> = ({ type, geo, size = 18, withTooltip = true }) => {
  const m = dcTypeMeta(type, { geo });
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
