import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** Two orthogonal axes describe a data collection, and the UI keeps them
 *  apart everywhere a DC is listed:
 *
 *    - metatype   — what the table IS: Metadata or Aggregate
 *    - capability — what the table can POWER: a lat/lon column pair makes it
 *                   usable by Map components
 *
 *  A metadata table carrying coordinates is both, so it has to read as
 *  "Metadata + Geo" instead of collapsing into a single "kind". The manager
 *  table, the DC viewer and the map preview all take their labels and colours
 *  from here so the same collection is described identically wherever it
 *  appears.
 */

/** Metatype axis. */
export const METADATA_COLOR = 'blue';
export const AGGREGATE_COLOR = 'orange';
/** Capability axis. The map preview paints its markers the same grape so the
 *  badge and the points on the map read as one signal. */
export const GEO_COLOR = 'grape';
export const GEO_ICON = 'mdi:map-marker-radius-outline';

/** The subset of a data collection these helpers classify on. */
export interface DcClassifiable {
  config?: Record<string, unknown>;
}

function dcProps(dc: DcClassifiable): Record<string, unknown> | undefined {
  return dc.config?.dc_specific_properties as Record<string, unknown> | undefined;
}

/** A DC is a "coordinates table" when its config carries explicit lat/lon
 *  column hints — backed by DCTableCoordinatesConfig server-side, but the
 *  dc_type stays "table". Mirrors validation.py:dc_has_coordinates. */
export function dcHasCoordinates(dc: DcClassifiable): boolean {
  const type = (dc.config?.type as string | undefined)?.toLowerCase();
  if (type !== 'table') return false;
  const props = dcProps(dc);
  return Boolean(props?.lat_column) && Boolean(props?.lon_column);
}

/** The lat/lon column names a coordinates table plots on, if any. */
export function dcCoordinateColumns(
  dc: DcClassifiable,
): { lat: string; lon: string } | null {
  const props = dcProps(dc);
  const lat = props?.lat_column as string | undefined;
  const lon = props?.lon_column as string | undefined;
  return lat && lon ? { lat, lon } : null;
}

export interface MetatypeMeta {
  label: string;
  color: string;
  icon: string;
}

/** Resolve the metatype axis to one consistent descriptor. An aggregate table
 *  looks the same whether the backend stamped metatype="Aggregated" or left it
 *  null (inferred from an advanced project's table DC), so both land on the
 *  same badge. Coordinates never enter here: that is the capability axis. */
export function dcMetatypeMeta(
  dc: DcClassifiable,
  projectType: 'basic' | 'advanced',
): MetatypeMeta | null {
  const type = (dc.config?.type as string | undefined)?.toLowerCase();
  const metatype = (dc.config?.metatype as string | undefined) || '';
  if (metatype.toLowerCase().startsWith('metadat')) {
    return { label: 'Metadata', color: METADATA_COLOR, icon: 'mdi:tag-outline' };
  }
  if (projectType === 'advanced' && type === 'table') {
    return {
      label: 'Aggregate',
      color: AGGREGATE_COLOR,
      icon: 'mdi:layers-triple-outline',
    };
  }
  return null;
}

/** Metadata / Aggregate badge. Renders nothing when the axis doesn't apply
 *  (an image DC in a basic project has no meaningful metatype). */
export const DcMetatypeBadge: React.FC<{
  dc: DcClassifiable;
  projectType: 'basic' | 'advanced';
}> = ({ dc, projectType }) => {
  const meta = dcMetatypeMeta(dc, projectType);
  if (!meta) return null;
  return (
    <Tooltip
      label={
        meta.label === 'Metadata'
          ? 'Metadata table: describes the samples other collections aggregate'
          : 'Aggregate table: rows fanned in from the project run'
      }
      withArrow
      withinPortal
    >
      <Badge
        color={meta.color}
        variant="light"
        size="sm"
        radius="sm"
        leftSection={<Icon icon={meta.icon} width={12} />}
      >
        {meta.label}
      </Badge>
    </Tooltip>
  );
};

/** Capability badge for a table that carries coordinates. Independent of the
 *  metatype badge, so a metadata table with lat/lon shows both. */
export const DcGeoBadge: React.FC<{ dc: DcClassifiable }> = ({ dc }) => {
  const cols = dcCoordinateColumns(dc);
  if (!cols) return null;
  return (
    <Tooltip
      label={`Geo location from ${cols.lat} / ${cols.lon}: this collection can power Map components`}
      withArrow
      withinPortal
    >
      <Badge
        color={GEO_COLOR}
        variant="light"
        size="sm"
        radius="sm"
        leftSection={<Icon icon={GEO_ICON} width={12} />}
      >
        Geo
      </Badge>
    </Tooltip>
  );
};
