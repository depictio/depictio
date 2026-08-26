import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** The type axis of a data collection: what kind of thing it holds, and so
 *  which components can bind to it. One entry per stored `dc_type`.
 *
 *  Shared by the Data Collections manager and the Ingestion report so the
 *  same collection looks identical across tabs. MultiQC is handled specially
 *  (renders its logo, not an mdi icon). */
export const DC_TYPE_ICON: Record<string, { icon: string; color: string; label: string }> = {
  table: { icon: 'mdi:table', color: 'teal', label: 'Table' },
  jbrowse2: { icon: 'mdi:dna', color: 'teal', label: 'JBrowse2' },
  image: { icon: 'mdi:image-outline', color: 'pink', label: 'Image' },
  geojson: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'GeoJSON' },
  map: { icon: 'mdi:map-marker-radius-outline', color: 'grape', label: 'Map' },
  phylogeny: { icon: 'mdi:graph-outline', color: 'grape', label: 'Phylo tree' },
};

/** Geomap is NOT a sibling of the types above: DCTableCoordinatesConfig
 *  subclasses DCTableConfig, so a geomap IS a table and still binds to Figure,
 *  Card, Interactive and Table components — it only adds Map. It therefore
 *  renders next to the table's own type, never in place of it, and is
 *  independent of the metatype axis: a metadata collection can be a table and
 *  a geomap at the same time.
 *
 *  Same colour and glyph wherever coordinates are announced: this badge, the
 *  upload modal's detection alert, the map preview. */
export const GEO_COLOR = 'grape';
export const GEO_ICON = 'mdi:map-marker-radius-outline';

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

/** Resolve a DC type to its icon descriptor. */
export function dcTypeMeta(
  type: string | null | undefined,
): { icon: string; color: string; label: string; isMultiqc: boolean } {
  const t = (type || '').toLowerCase();
  if (t === 'multiqc') return { icon: '', color: 'violet', label: 'MultiQC', isMultiqc: true };
  const m = DC_TYPE_ICON[t] ?? { ...FALLBACK, label: type || 'unknown' };
  return { ...m, isMultiqc: false };
}

/** Same descriptor, resolved from a whole data collection. */
export function dcTypeMetaFor(dc: DcClassifiable) {
  return dcTypeMeta(dc.config?.type as string | undefined);
}

/** What the manager's Type filter matches on: the type label, plus "geomap"
 *  for a table that also carries coordinates, so either word finds the row. */
export function dcTypeSearchKey(dc: DcClassifiable): string {
  const label = dcTypeMetaFor(dc).label.toLowerCase();
  return dcHasCoordinates(dc) ? `${label} geomap` : label;
}

/** Renders the icon for a DC type — the MultiQC logo or a coloured mdi glyph. */
export const DcTypeIcon: React.FC<{
  type: string | null | undefined;
  size?: number;
  withTooltip?: boolean;
}> = ({ type, size = 18, withTooltip = true }) => {
  const m = dcTypeMeta(type);
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

/** The additive Geomap marker, rendered beside a table's own type. Nothing
 *  when the collection carries no coordinates. */
export const DcGeomapBadge: React.FC<{ dc: DcClassifiable; size?: 'xs' | 'sm' }> = ({
  dc,
  size = 'sm',
}) => {
  const cols = dcCoordinateColumns(dc);
  if (!dcHasCoordinates(dc) || !cols) return null;
  return (
    <Tooltip
      label={`Also a geomap: ${cols.lat} / ${cols.lon} let Map components bind to this table, on top of everything a table already does`}
      withArrow
      withinPortal
    >
      <Badge
        color={GEO_COLOR}
        variant="light"
        size={size}
        radius="sm"
        leftSection={<Icon icon={GEO_ICON} width={12} />}
      >
        Geomap
      </Badge>
    </Tooltip>
  );
};
